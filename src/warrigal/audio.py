from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TranscriptSegment:
    index: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    source_path: Path
    segments: tuple[TranscriptSegment, ...]
    raw_json: bytes
    model_path: Path

    @property
    def text(self) -> str:
        return " ".join(segment.text for segment in self.segments)


def _run_command(command: list[str]) -> None:
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def transcribe_audio(
    source_path: str | Path,
    *,
    model_path: str | Path,
    ffmpeg_path: str = "/opt/homebrew/bin/ffmpeg",
    whisper_path: str = "/opt/homebrew/bin/whisper-cli",
    language: str = "en",
) -> TranscriptResult:
    """Transcribe local audio without modifying the source file."""

    source = Path(source_path).expanduser().resolve()
    model = Path(model_path).expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(source)
    if not model.is_file():
        raise FileNotFoundError(model)

    with tempfile.TemporaryDirectory(prefix="warrigal-audio-") as directory:
        workdir = Path(directory)
        wav_path = workdir / "input.wav"
        output_prefix = workdir / "transcript"

        _run_command([
            ffmpeg_path,
            "-nostdin",
            "-y",
            "-i", str(source),
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(wav_path),
        ])

        _run_command([
            whisper_path,
            "-m", str(model),
            "-f", str(wav_path),
            "-l", language,
            "-oj",
            "-of", str(output_prefix),
        ])

        raw_json = output_prefix.with_suffix(".json").read_bytes()
        payload = json.loads(raw_json)

        segments = []
        for index, item in enumerate(payload["transcription"]):
            offsets = item["offsets"]
            start_ms = int(offsets["from"])
            end_ms = int(offsets["to"])

            if start_ms < 0 or end_ms < start_ms:
                raise ValueError("Invalid transcript segment timing")

            segments.append(
                TranscriptSegment(
                    index=index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=str(item["text"]).strip(),
                )
            )

        return TranscriptResult(
            source_path=source,
            segments=tuple(segments),
            raw_json=raw_json,
            model_path=model,
        )
