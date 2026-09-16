from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from warrigal.models import VisualTransition
from warrigal.qwen_visual import (
    extract_model_response,
    prompt_sha256,
)


TRANSITION_PROMPT = """Compare these two video frames directly.

The first image is BEFORE.
The second image is AFTER.

Report only changes supported by comparing the two images.

Rules:
1. Distinguish real visual change from differences in wording.
2. Identify appearances, disappearances, movement, position changes,
   colour changes, shape changes, scale changes, and scene cuts.
3. Do not infer movement when only two static samples are available.
4. If geometry differs but direction or animation is uncertain, say so.
5. Transcribe changed or persistent readable text when relevant.
6. State explicitly when no definite change is visible.
7. Do not invent content outside the two frames.

Return exactly these headings:
TRANSITION SUMMARY
APPEARED
DISAPPEARED
MOVED OR REPOSITIONED
SHAPE SCALE OR COLOUR CHANGE
PERSISTENT ELEMENTS
READABLE TEXT CHANGE
UNCERTAINTY
"""


@dataclass(frozen=True)
class FrameTransitionResult:
    text: str
    diagnostics: str
    command: tuple[str, ...]


Runner = Callable[
    [list[str], int],
    subprocess.CompletedProcess[str],
]


def _default_runner(
    command: list[str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def clean_transition_response(
    output: str,
    prompt: str,
) -> str:
    """Remove llama.cpp interface output from a transition response."""

    response = extract_model_response(output, prompt)
    heading = response.find("TRANSITION SUMMARY")

    if heading >= 0:
        response = response[heading:]

    return response.strip()


class QwenFrameTransitionAnalyser:
    """Compare two archived video frames using local Qwen vision."""

    def __init__(
        self,
        *,
        model_path: str | Path,
        projector_path: str | Path,
        executable: str = "llama-cli",
        analyser_version: str | None = None,
        runner: Runner = _default_runner,
        timeout_seconds: int = 900,
    ):
        self.model_path = Path(model_path).expanduser().resolve()
        self.projector_path = (
            Path(projector_path).expanduser().resolve()
        )
        self.executable = executable
        self.analyser_version = analyser_version
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def validate(
        self,
        start_image: str | Path,
        end_image: str | Path,
    ) -> tuple[Path, Path]:
        if shutil.which(self.executable) is None:
            raise FileNotFoundError(
                f"Visual runtime not found: {self.executable}"
            )
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Qwen model not found: {self.model_path}"
            )
        if not self.projector_path.is_file():
            raise FileNotFoundError(
                f"Qwen projector not found: {self.projector_path}"
            )

        start = Path(start_image).expanduser().resolve()
        end = Path(end_image).expanduser().resolve()

        if not start.is_file():
            raise FileNotFoundError(
                f"Start frame not found: {start}"
            )
        if not end.is_file():
            raise FileNotFoundError(
                f"End frame not found: {end}"
            )

        return start, end

    def analyse(
        self,
        start_image: str | Path,
        end_image: str | Path,
        *,
        prompt: str = TRANSITION_PROMPT,
    ) -> FrameTransitionResult:
        start, end = self.validate(start_image, end_image)

        command = [
            self.executable,
            "--single-turn",
            "--simple-io",
            "--model",
            str(self.model_path),
            "--mmproj",
            str(self.projector_path),
            "--image",
            str(start),
            "--image",
            str(end),
            "--ctx-size",
            "8192",
            "--n-gpu-layers",
            "99",
            "--image-min-tokens",
            "1024",
            "--image-max-tokens",
            "1024",
            "--temp",
            "0.1",
            "--predict",
            "900",
            "--prompt",
            prompt,
        ]

        process = self.runner(command, self.timeout_seconds)

        if process.returncode != 0:
            diagnostic = (
                process.stderr or process.stdout
            ).strip()
            raise RuntimeError(
                "Qwen frame-transition analysis failed: "
                + diagnostic[-4000:]
            )

        response = clean_transition_response(
            process.stdout,
            prompt,
        )

        if not response:
            raise RuntimeError(
                "Qwen frame-transition analysis returned no response."
            )

        return FrameTransitionResult(
            text=response,
            diagnostics=process.stderr.strip(),
            command=tuple(command),
        )


def analyse_and_persist_transition(
    *,
    video_object_id: str,
    start_frame,
    end_frame,
    start_image_path: str | Path,
    end_image_path: str | Path,
    repository,
    analyser: QwenFrameTransitionAnalyser,
    prompt: str = TRANSITION_PROMPT,
) -> VisualTransition:
    """Analyse an adjacent frame pair and preserve its provenance."""

    if end_frame.timestamp_ms <= start_frame.timestamp_ms:
        raise ValueError(
            "End-frame timestamp must be after start-frame timestamp."
        )

    result = analyser.analyse(
        start_image_path,
        end_image_path,
        prompt=prompt,
    )

    start_path = Path(start_image_path).expanduser().resolve()
    end_path = Path(end_image_path).expanduser().resolve()

    transition = VisualTransition(
        video_object_id=video_object_id,
        start_frame_object_id=start_frame.frame_object_id,
        start_frame_acquisition_id=(
            start_frame.frame_acquisition_id
        ),
        start_timestamp_ms=start_frame.timestamp_ms,
        end_frame_object_id=end_frame.frame_object_id,
        end_frame_acquisition_id=end_frame.frame_acquisition_id,
        end_timestamp_ms=end_frame.timestamp_ms,
        text=result.text,
        analyser="Qwen3-VL-8B-Instruct-GGUF-frame-pair",
        analyser_version=analyser.analyser_version,
        status="derived_unreviewed",
        confidence=None,
        metadata={
            "prompt": prompt,
            "prompt_sha256": prompt_sha256(prompt),
            "start_image_path": str(start_path),
            "end_image_path": str(end_path),
            "start_image_size_bytes": start_path.stat().st_size,
            "end_image_size_bytes": end_path.stat().st_size,
            "model_filename": analyser.model_path.name,
            "projector_filename": analyser.projector_path.name,
            "runtime": analyser.executable,
            "runtime_diagnostics":
                result.diagnostics[-4000:],
            "comparison_type": "adjacent_sampled_frames",
            "continuous_motion_inferred": False,
            "review_status": "UNREVIEWED",
        },
    )

    repository.save_visual_transition(transition)
    return transition
