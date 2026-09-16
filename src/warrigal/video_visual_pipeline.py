from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from warrigal.database import initialize_database
from warrigal.object_store import ObjectStore
from warrigal.qwen_frame_transition import (
    QwenFrameTransitionAnalyser,
)
from warrigal.qwen_transition_campaign import (
    run_qwen_transition_campaign,
)
from warrigal.qwen_video_campaign import (
    load_checkpoint,
    run_qwen_video_campaign,
    save_checkpoint,
)
from warrigal.qwen_visual import QwenVisualAnalyser
from warrigal.repository import WarrigalRepository
from warrigal.video_frame_ingestion import ingest_video_frames
from warrigal.video_frames_cli import select_acquisition
from warrigal.video_motion_synthesis import (
    QwenMotionSynthesiser,
    ordered_transition_timeline,
    synthesise_motion_and_persist,
)


def collect_adjacent_transitions(
    *,
    video_object_id: str,
    frames,
    repository,
):
    """Return exactly one latest transition for every adjacent pair."""

    ordered = sorted(
        tuple(frames),
        key=lambda frame: (
            frame.timestamp_ms,
            frame.frame_index,
            frame.frame_object_id,
        ),
    )

    if len(ordered) < 2:
        raise ValueError(
            "Video visual pipeline requires at least two frames."
        )

    transitions = []

    for start, end in zip(ordered, ordered[1:]):
        rows = repository.get_visual_transition_for_pair(
            video_object_id=video_object_id,
            start_frame_object_id=start.frame_object_id,
            end_frame_object_id=end.frame_object_id,
        )

        if not rows:
            raise ValueError(
                "Missing transition for adjacent frames: "
                f"{start.timestamp_ms}ms -> {end.timestamp_ms}ms"
            )

        transitions.append(rows[-1])

    # Performs the authoritative contiguity validation.
    ordered_transition_timeline(transitions)
    return transitions


def matching_motion_synthesis(
    *,
    video_object_id: str,
    transition_ids: list[str],
    repository,
):
    """Return an existing synthesis built from the same evidence."""

    for row in repository.get_video_motion_syntheses(
        video_object_id
    ):
        stored_ids = json.loads(row["transition_ids_json"])

        if (
            stored_ids == transition_ids
            and row["status"] == "derived_unreviewed"
        ):
            return row

    return None


def recover_frame_observations(
    *,
    frames,
    repository,
    checkpoint_path: str | Path,
) -> int:
    """Recover already-persisted observations into a checkpoint."""

    checkpoint_path = Path(checkpoint_path)
    checkpoint = load_checkpoint(checkpoint_path)
    recovered = 0

    for frame in frames:
        if frame.frame_object_id in checkpoint["completed"]:
            continue

        stored = repository.get_visual_observations_for_frame(
            frame.frame_object_id
        )

        if not stored:
            continue

        latest = stored[-1]

        checkpoint["completed"][frame.frame_object_id] = {
            "frame_acquisition_id":
                latest["frame_acquisition_id"],
            "frame_index": frame.frame_index,
            "timestamp_ms": frame.timestamp_ms,
            "observation_id": latest["observation_id"],
            "status": latest["status"],
            "recovered_from_database": True,
        }
        checkpoint["failed"].pop(
            frame.frame_object_id,
            None,
        )
        recovered += 1

    save_checkpoint(checkpoint_path, checkpoint)
    return recovered


def run_archived_video_visual_pipeline(
    object_id: str,
    *,
    model_path: str | Path,
    projector_path: str | Path,
    interval_seconds: float = 1.0,
    acquisition_id: str | None = None,
    checkpoint_root: str | Path = "workspace",
    repository=None,
    object_store=None,
) -> int:
    """Run Warrigal's complete local visual analysis for one video."""

    if interval_seconds <= 0:
        raise ValueError(
            "interval_seconds must be greater than zero."
        )

    model = Path(model_path).expanduser().resolve()
    projector = Path(projector_path).expanduser().resolve()

    if not model.is_file():
        raise FileNotFoundError(
            f"Qwen model not found: {model}"
        )
    if not projector.is_file():
        raise FileNotFoundError(
            f"Qwen projector not found: {projector}"
        )

    checkpoint_root = Path(
        checkpoint_root
    ).expanduser().resolve()
    checkpoint_root.mkdir(parents=True, exist_ok=True)

    database = None

    if repository is None:
        database = initialize_database()
        repository = WarrigalRepository(database)

    if object_store is None:
        object_store = ObjectStore()

    try:
        object_row = repository.get_object(object_id)

        if object_row is None:
            raise ValueError(
                f"Unknown Warrigal video object: {object_id}"
            )

        source_path = object_store.path_for_hash(
            object_row["sha256"]
        )

        if not source_path.is_file():
            raise FileNotFoundError(
                f"Archived video bytes are missing: {source_path}"
            )

        acquisitions = repository.get_acquisitions_for_object(
            object_id
        )
        acquisition = select_acquisition(
            acquisitions,
            acquisition_id,
        )

        source = repository.get_source(acquisition["source_id"])

        if source is None:
            raise ValueError(
                "Video acquisition source does not exist: "
                + acquisition["source_id"]
            )

        source_url = (
            source["final_locator"]
            or source["locator"]
            or f"warrigal:{object_id}"
        )
        source_title = source["title"] or object_id

        print("=== WARRIGAL ARCHIVED VIDEO VISUAL PIPELINE ===")
        print("VIDEO OBJECT:", object_id)
        print("ACQUISITION:", acquisition["acquisition_id"])
        print("TITLE:", source_title)
        print("INTERVAL:", f"{interval_seconds:g} seconds")

        frame_result = ingest_video_frames(
            source_object_id=object_id,
            source_acquisition_id=acquisition["acquisition_id"],
            source_path=source_path,
            source_url=source_url,
            source_title=source_title,
            repository=repository,
            object_store=object_store,
            job_id=acquisition["job_id"],
            node_id=acquisition["node_id"],
            batch_id=acquisition["batch_id"],
            interval_seconds=interval_seconds,
        )

        frames = frame_result.frames

        if len(frames) < 2:
            raise ValueError(
                "Frame extraction produced fewer than two frames."
            )

        frame_checkpoint = (
            checkpoint_root
            / f"qwen-frames-{object_id}.checkpoint.json"
        )
        transition_checkpoint = (
            checkpoint_root
            / f"qwen-transitions-{object_id}.checkpoint.json"
        )

        recovered_frames = recover_frame_observations(
            frames=frames,
            repository=repository,
            checkpoint_path=frame_checkpoint,
        )

        visual_analyser = QwenVisualAnalyser(
            model_path=model,
            projector_path=projector,
            executable="llama-cli",
            analyser_version="Q4_K_M / visual-pipeline-v1",
        )

        print()
        print("=== FRAME OBSERVATION CAMPAIGN ===")
        print(
            "RECOVERED FROM DATABASE:",
            recovered_frames,
        )

        frame_campaign = run_qwen_video_campaign(
            frames,
            repository=repository,
            object_store=object_store,
            analyser=visual_analyser,
            checkpoint_path=frame_checkpoint,
        )

        if frame_campaign.failed:
            raise RuntimeError(
                "Frame observation campaign has failures: "
                f"{frame_campaign.failed}. Resume the same command."
            )

        transition_analyser = QwenFrameTransitionAnalyser(
            model_path=model,
            projector_path=projector,
            executable="llama-cli",
            analyser_version="Q4_K_M / transition-pipeline-v1",
        )

        print()
        print("=== ADJACENT-FRAME TRANSITION CAMPAIGN ===")

        transition_campaign = run_qwen_transition_campaign(
            video_object_id=object_id,
            frames=frames,
            repository=repository,
            object_store=object_store,
            analyser=transition_analyser,
            checkpoint_path=transition_checkpoint,
        )

        if (
            transition_campaign.failed
            or transition_campaign.remaining
        ):
            raise RuntimeError(
                "Transition campaign is incomplete: "
                f"failed={transition_campaign.failed}, "
                f"remaining={transition_campaign.remaining}. "
                "Resume the same command."
            )

        transitions = collect_adjacent_transitions(
            video_object_id=object_id,
            frames=frames,
            repository=repository,
        )
        timeline = ordered_transition_timeline(transitions)
        transition_ids = [
            item["transition_id"]
            for item in timeline
        ]

        existing = matching_motion_synthesis(
            video_object_id=object_id,
            transition_ids=transition_ids,
            repository=repository,
        )

        if existing is None:
            print()
            print("=== VIDEO MOTION SYNTHESIS ===")

            motion_analyser = QwenMotionSynthesiser(
                model_path=model,
                executable="llama-cli",
                analyser_version=(
                    "Q4_K_M / motion-prompt-v2 / "
                    "visual-pipeline-v1"
                ),
            )

            synthesis = synthesise_motion_and_persist(
                video_object_id=object_id,
                video_acquisition_id=(
                    acquisition["acquisition_id"]
                ),
                transitions=transitions,
                repository=repository,
                analyser=motion_analyser,
            )

            synthesis_id = synthesis.synthesis_id
            synthesis_status = synthesis.status
            synthesis_text = synthesis.text
        else:
            synthesis_id = existing["synthesis_id"]
            synthesis_status = existing["status"]
            synthesis_text = existing["text"]

            print()
            print("=== EXISTING MOTION SYNTHESIS REUSED ===")

        print()
        print("=== VIDEO VISUAL PIPELINE COMPLETE ===")
        print("VIDEO OBJECT:", object_id)
        print("FRAMES:", len(frames))
        print("TRANSITIONS:", len(transitions))
        print("COVERAGE:", (
            f"{timeline[0]['start_timestamp_ms']}ms"
            " -> "
            f"{timeline[-1]['end_timestamp_ms']}ms"
        ))
        print("SYNTHESIS:", synthesis_id)
        print("STATUS:", synthesis_status)
        print("FRAME CHECKPOINT:", frame_checkpoint)
        print("TRANSITION CHECKPOINT:", transition_checkpoint)
        print()
        print(synthesis_text)

        return 0

    finally:
        if database is not None:
            database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run local Qwen visual analysis over an archived "
            "Warrigal video object."
        )
    )
    parser.add_argument(
        "object_id",
        help="Archived Warrigal video object ID.",
    )
    parser.add_argument(
        "--acquisition-id",
        help=(
            "Explicit acquisition when the object has multiple "
            "provenance records."
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between sampled frames (default: 1).",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("WARRIGAL_QWEN_MODEL"),
        help=(
            "Qwen GGUF model path, or set "
            "WARRIGAL_QWEN_MODEL."
        ),
    )
    parser.add_argument(
        "--projector",
        default=os.environ.get("WARRIGAL_QWEN_PROJECTOR"),
        help=(
            "Qwen multimodal projector path, or set "
            "WARRIGAL_QWEN_PROJECTOR."
        ),
    )
    parser.add_argument(
        "--checkpoint-root",
        default="workspace",
        help="Checkpoint directory (default: workspace).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if not args.model:
        raise SystemExit(
            "Provide --model or set WARRIGAL_QWEN_MODEL."
        )
    if not args.projector:
        raise SystemExit(
            "Provide --projector or set "
            "WARRIGAL_QWEN_PROJECTOR."
        )

    return run_archived_video_visual_pipeline(
        args.object_id,
        model_path=args.model,
        projector_path=args.projector,
        interval_seconds=args.interval,
        acquisition_id=args.acquisition_id,
        checkpoint_root=args.checkpoint_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
