from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from warrigal.qwen_visual import (
    QwenVisualAnalyser,
    analyse_and_persist,
)


VIDEO_FRAME_PROMPT = """Describe this video frame concisely.

Return these headings:
VISIBLE SUBJECTS:
VISIBLE OBJECTS:
READABLE TEXT:
ACTION OR CHANGE:
TECHNICAL DETAILS:
UNCERTAINTY:

Report only visible evidence. Do not invent context. If a field cannot
be determined from this frame, write UNKNOWN.
"""


@dataclass(frozen=True)
class VideoVisualCampaignResult:
    selected: int
    completed: int
    failed: int
    skipped: int
    checkpoint_path: Path


def load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {
            "version": 1,
            "completed": {},
            "failed": {},
        }

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("Video visual checkpoint must be an object.")

    payload.setdefault("version", 1)
    payload.setdefault("completed", {})
    payload.setdefault("failed", {})
    return payload


def save_checkpoint(path: Path, checkpoint: dict) -> None:
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


def run_qwen_video_campaign(
    frames: Iterable,
    *,
    repository,
    object_store,
    analyser: QwenVisualAnalyser,
    checkpoint_path: str | Path,
    max_frames: int | None = None,
    prompt: str = VIDEO_FRAME_PROMPT,
    analyse_function: Callable = analyse_and_persist,
) -> VideoVisualCampaignResult:
    checkpoint_path = Path(checkpoint_path)
    checkpoint = load_checkpoint(checkpoint_path)

    pending = [
        frame
        for frame in frames
        if frame.frame_object_id not in checkpoint["completed"]
    ]

    if max_frames is not None:
        if max_frames < 1:
            raise ValueError("max_frames must be at least 1")
        pending = pending[:max_frames]

    completed = 0
    failed = 0

    for number, frame in enumerate(pending, start=1):
        print(
            f"[{number}/{len(pending)}] "
            f"{frame.timestamp_ms / 1000:.3f}s | "
            f"{frame.frame_object_id}",
            flush=True,
        )

        try:
            object_row = repository.get_object(
                frame.frame_object_id
            )
            if object_row is None:
                raise ValueError(
                    "Archived frame object does not exist: "
                    + frame.frame_object_id
                )

            image_path = object_store.path_for_hash(
                object_row["sha256"]
            )
            if not image_path.is_file():
                raise FileNotFoundError(
                    f"Archived frame bytes are missing: {image_path}"
                )

            observation = analyse_function(
                image_path=image_path,
                frame_object_id=frame.frame_object_id,
                frame_acquisition_id=frame.frame_acquisition_id,
                timestamp_ms=frame.timestamp_ms,
                repository=repository,
                analyser=analyser,
                prompt=prompt,
            )

        except Exception as exc:
            failed += 1
            checkpoint["failed"][frame.frame_object_id] = {
                "frame_acquisition_id":
                    frame.frame_acquisition_id,
                "frame_index": frame.frame_index,
                "timestamp_ms": frame.timestamp_ms,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            print(
                f"  FAILED: {type(exc).__name__}: {exc}",
                flush=True,
            )
        else:
            completed += 1
            checkpoint["completed"][frame.frame_object_id] = {
                "frame_acquisition_id":
                    frame.frame_acquisition_id,
                "frame_index": frame.frame_index,
                "timestamp_ms": frame.timestamp_ms,
                "observation_id": observation.observation_id,
                "status": observation.status,
            }
            checkpoint["failed"].pop(
                frame.frame_object_id,
                None,
            )
            print(
                f"  COMPLETED: {observation.observation_id}",
                flush=True,
            )

        save_checkpoint(checkpoint_path, checkpoint)

    skipped = len(tuple(frames)) - len(pending)

    return VideoVisualCampaignResult(
        selected=len(pending),
        completed=completed,
        failed=failed,
        skipped=skipped,
        checkpoint_path=checkpoint_path.resolve(),
    )
