from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from warrigal.config import CONFIG


@dataclass(frozen=True)
class VideoFrame:
    index: int
    timestamp_ms: int
    image_bytes: bytes


def extract_video_frames(
    source_path: str | Path,
    *,
    interval_seconds: float = 10.0,
    ffmpeg_path: str = CONFIG.ffmpeg,
    ffprobe_path: str = CONFIG.ffprobe,
) -> tuple[VideoFrame, ...]:
    """Extract representative JPEG frames with deterministic timestamps."""
    source = Path(source_path).expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(source)

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    probe = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    duration_seconds = float(probe.stdout.strip())

    timestamps: list[float] = []
    timestamp = 0.0

    while timestamp < duration_seconds:
        timestamps.append(timestamp)
        timestamp += interval_seconds

    frames: list[VideoFrame] = []

    with tempfile.TemporaryDirectory(prefix="warrigal-frames-") as directory:
        workdir = Path(directory)

        for index, timestamp_seconds in enumerate(timestamps):
            output = workdir / f"frame-{index:06d}.jpg"

            subprocess.run(
                [
                    ffmpeg_path,
                    "-nostdin",
                    "-y",
                    "-ss",
                    f"{timestamp_seconds:.3f}",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(output),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            frames.append(
                VideoFrame(
                    index=index,
                    timestamp_ms=round(timestamp_seconds * 1000),
                    image_bytes=output.read_bytes(),
                )
            )

    return tuple(frames)
