from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from warrigal.qwen_frame_transition import (
    QwenFrameTransitionAnalyser,
    analyse_and_persist_transition,
)


@dataclass(frozen=True)
class TransitionCampaignResult:
    video_object_id: str
    selected: int
    completed: int
    failed: int
    skipped: int
    remaining: int
    checkpoint_path: Path


def transition_key(start_frame, end_frame) -> str:
    return (
        f"{start_frame.frame_object_id}"
        f"->{end_frame.frame_object_id}"
    )


def load_transition_checkpoint(
    path: Path,
    *,
    video_object_id: str,
) -> dict:
    if not path.exists():
        return {
            "video_object_id": video_object_id,
            "completed": {},
            "failed": {},
        }

    payload = json.loads(path.read_text(encoding="utf-8"))

    if payload.get("video_object_id") != video_object_id:
        raise ValueError(
            "Transition checkpoint belongs to a different video: "
            f"{payload.get('video_object_id')!r} != "
            f"{video_object_id!r}"
        )

    payload.setdefault("completed", {})
    payload.setdefault("failed", {})
    return payload


def save_transition_checkpoint(
    path: Path,
    checkpoint: dict,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            checkpoint,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_qwen_transition_campaign(
    *,
    video_object_id: str,
    frames: Iterable,
    repository,
    object_store,
    analyser: QwenFrameTransitionAnalyser,
    checkpoint_path: str | Path,
    max_transitions: int | None = None,
    analyse_function: Callable = analyse_and_persist_transition,
) -> TransitionCampaignResult:
    """
    Compare adjacent timestamped frames with safe checkpoint resumption.

    Completed frame pairs are skipped. Failed pairs remain retryable.
    Existing database transitions are recovered into the checkpoint.
    """

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
            "Transition campaign requires at least two frames."
        )

    checkpoint_path = Path(checkpoint_path)
    checkpoint = load_transition_checkpoint(
        checkpoint_path,
        video_object_id=video_object_id,
    )

    pairs = list(zip(ordered, ordered[1:]))

    # Recover completed database work if the checkpoint was lost.
    for start_frame, end_frame in pairs:
        key = transition_key(start_frame, end_frame)

        if key in checkpoint["completed"]:
            continue

        existing = repository.get_visual_transition_for_pair(
            video_object_id=video_object_id,
            start_frame_object_id=start_frame.frame_object_id,
            end_frame_object_id=end_frame.frame_object_id,
        )

        if existing:
            latest = existing[-1]
            checkpoint["completed"][key] = {
                "transition_id": latest["transition_id"],
                "status": latest["status"],
                "start_frame_object_id":
                    start_frame.frame_object_id,
                "end_frame_object_id":
                    end_frame.frame_object_id,
                "start_timestamp_ms":
                    start_frame.timestamp_ms,
                "end_timestamp_ms":
                    end_frame.timestamp_ms,
                "recovered_from_database": True,
            }
            checkpoint["failed"].pop(key, None)

    save_transition_checkpoint(checkpoint_path, checkpoint)

    all_pending = [
        pair
        for pair in pairs
        if transition_key(*pair)
        not in checkpoint["completed"]
    ]
    skipped_completed = len(pairs) - len(all_pending)
    pending = all_pending

    if max_transitions is not None:
        if max_transitions < 1:
            raise ValueError(
                "max_transitions must be at least 1"
            )
        pending = pending[:max_transitions]

    completed = 0
    failed = 0

    for number, (start_frame, end_frame) in enumerate(
        pending,
        start=1,
    ):
        key = transition_key(start_frame, end_frame)

        print(
            f"[{number}/{len(pending)}] "
            f"{start_frame.timestamp_ms / 1000:.3f}s"
            " → "
            f"{end_frame.timestamp_ms / 1000:.3f}s",
            flush=True,
        )

        try:
            start_object = repository.get_object(
                start_frame.frame_object_id
            )
            end_object = repository.get_object(
                end_frame.frame_object_id
            )

            if start_object is None:
                raise ValueError(
                    "Missing start-frame object: "
                    + start_frame.frame_object_id
                )
            if end_object is None:
                raise ValueError(
                    "Missing end-frame object: "
                    + end_frame.frame_object_id
                )

            start_path = object_store.path_for_hash(
                start_object["sha256"]
            )
            end_path = object_store.path_for_hash(
                end_object["sha256"]
            )

            if not start_path.is_file():
                raise FileNotFoundError(
                    f"Missing start-frame bytes: {start_path}"
                )
            if not end_path.is_file():
                raise FileNotFoundError(
                    f"Missing end-frame bytes: {end_path}"
                )

            transition = analyse_function(
                video_object_id=video_object_id,
                start_frame=start_frame,
                end_frame=end_frame,
                start_image_path=start_path,
                end_image_path=end_path,
                repository=repository,
                analyser=analyser,
            )

        except Exception as exc:
            failed += 1
            checkpoint["failed"][key] = {
                "start_frame_object_id":
                    start_frame.frame_object_id,
                "end_frame_object_id":
                    end_frame.frame_object_id,
                "start_timestamp_ms":
                    start_frame.timestamp_ms,
                "end_timestamp_ms":
                    end_frame.timestamp_ms,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            print(
                f"  FAILED: {type(exc).__name__}: {exc}",
                flush=True,
            )
        else:
            completed += 1
            checkpoint["completed"][key] = {
                "transition_id": transition.transition_id,
                "status": transition.status,
                "start_frame_object_id":
                    start_frame.frame_object_id,
                "end_frame_object_id":
                    end_frame.frame_object_id,
                "start_timestamp_ms":
                    start_frame.timestamp_ms,
                "end_timestamp_ms":
                    end_frame.timestamp_ms,
                "recovered_from_database": False,
            }
            checkpoint["failed"].pop(key, None)
            print(
                f"  COMPLETED: {transition.transition_id}",
                flush=True,
            )

        save_transition_checkpoint(
            checkpoint_path,
            checkpoint,
        )

    return TransitionCampaignResult(
        video_object_id=video_object_id,
        selected=len(pending),
        completed=completed,
        failed=failed,
        skipped=skipped_completed,
        remaining=len(all_pending) - len(pending),
        checkpoint_path=checkpoint_path.resolve(),
    )
