from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from warrigal.models import VisualObservation


DEFAULT_PROMPT = """Analyse this image carefully.

1. Describe its overall structure and purpose.
2. Transcribe every readable label in its apparent order.
3. Identify scientific inaccuracies, ambiguities, or speculative claims.
4. Distinguish directly visible evidence from inference.
5. State clearly when something is unreadable or uncertain.
"""


@dataclass(frozen=True)
class QwenVisualResult:
    text: str
    diagnostics: str
    command: tuple[str, ...]


Runner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


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


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def extract_model_response(output: str, prompt: str) -> str:
    """Remove llama.cpp interface text from the model response."""

    cleaned = output.strip()
    prompt_marker = "> " + prompt.strip()

    if prompt_marker in cleaned:
        cleaned = cleaned.split(prompt_marker, 1)[1]

    for boundary in (
        "\n[ Prompt:",
        "\nExiting...",
    ):
        if boundary in cleaned:
            cleaned = cleaned.split(boundary, 1)[0]

    return cleaned.strip()


class QwenVisualAnalyser:
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
        self.projector_path = Path(projector_path).expanduser().resolve()
        self.executable = executable
        self.analyser_version = analyser_version
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def validate(self, image_path: str | Path) -> Path:
        image = Path(image_path).expanduser().resolve()

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
                f"Visual projector not found: {self.projector_path}"
            )
        if not image.is_file():
            raise FileNotFoundError(f"Image not found: {image}")

        return image

    def analyse(
        self,
        image_path: str | Path,
        *,
        prompt: str = DEFAULT_PROMPT,
    ) -> QwenVisualResult:
        image = self.validate(image_path)

        command = [
            self.executable,
            "--single-turn",
            "--simple-io",
            "--model",
            str(self.model_path),
            "--mmproj",
            str(self.projector_path),
            "--image",
            str(image),
            "--ctx-size",
            "8192",
            "--n-gpu-layers",
            "99",
            "--image-min-tokens",
            "1024",
            "--image-max-tokens",
            "1024",
            "--temp",
            "0.2",
            "--predict",
            "1200",
            "--prompt",
            prompt,
        ]

        process = self.runner(command, self.timeout_seconds)

        if process.returncode != 0:
            diagnostic = (process.stderr or process.stdout).strip()
            raise RuntimeError(
                "Qwen visual analysis failed: "
                + diagnostic[-4000:]
            )

        text = extract_model_response(process.stdout, prompt)
        if not text:
            raise RuntimeError(
                "Qwen visual analysis returned no response text."
            )

        return QwenVisualResult(
            text=text,
            diagnostics=process.stderr.strip(),
            command=tuple(command),
        )


def analyse_and_persist(
    *,
    image_path: str | Path,
    frame_object_id: str,
    frame_acquisition_id: str,
    timestamp_ms: int,
    repository,
    analyser: QwenVisualAnalyser,
    prompt: str = DEFAULT_PROMPT,
) -> VisualObservation:
    result = analyser.analyse(image_path, prompt=prompt)
    image = Path(image_path).expanduser().resolve()

    observation = VisualObservation(
        frame_object_id=frame_object_id,
        frame_acquisition_id=frame_acquisition_id,
        timestamp_ms=timestamp_ms,
        text=result.text,
        analyser="Qwen3-VL-8B-Instruct-GGUF",
        analyser_version=analyser.analyser_version,
        status="derived_unreviewed",
        confidence=None,
        metadata={
            "prompt": prompt,
            "prompt_sha256": prompt_sha256(prompt),
            "image_path": str(image),
            "image_size_bytes": image.stat().st_size,
            "model_filename": analyser.model_path.name,
            "model_size_bytes": analyser.model_path.stat().st_size,
            "projector_filename": analyser.projector_path.name,
            "projector_size_bytes":
                analyser.projector_path.stat().st_size,
            "runtime": analyser.executable,
            "runtime_diagnostics": result.diagnostics[-4000:],
            "image_min_tokens": 1024,
            "context_size": 8192,
            "maximum_output_tokens": 1200,
            "temperature": 0.2,
            "review_status": "UNREVIEWED",
        },
    )

    repository.save_visual_observation(observation)
    return observation
