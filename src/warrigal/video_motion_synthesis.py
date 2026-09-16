from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from warrigal.models import VideoMotionSynthesis
from warrigal.qwen_visual import extract_model_response


MOTION_PROMPT = """Create one evidence-linked account of a video's visual
progression from these ordered adjacent-frame comparisons.

Rules:
1. Use only the supplied transition evidence.
2. Cite timestamps for each important change.
3. Distinguish newly appearing objects from evolving versions of the
   same object.
4. Identify persistent elements separately from changing elements.
5. Do not claim continuous movement beyond what adjacent sampled frames
   support.
6. Preserve uncertainty and contradictions found in the transition
   evidence.
7. Do not repeat every sentence; synthesize the progression concisely.
8. Do not introduce outside knowledge, including claims that a
   pattern is a known or recognised iteration.
9. Every claim under MAJOR VISUAL CHANGES must agree exactly with the
   corresponding interval under CHRONOLOGICAL PROGRESSION.
10. Preserve interval direction: BEFORE describes the start timestamp
    and AFTER describes the end timestamp.
11. Before answering, check the completed account for contradictory
    descriptions of the same timestamp interval.

Return exactly these headings:
VIDEO MOTION OVERVIEW
CHRONOLOGICAL PROGRESSION
PERSISTENT ELEMENTS
MAJOR VISUAL CHANGES
UNCERTAINTIES AND LIMITS
EVIDENCE COVERAGE
"""


@dataclass(frozen=True)
class MotionAnalysisResult:
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


def ordered_transition_timeline(
    transitions: Iterable,
) -> list[dict[str, Any]]:
    """Normalize and validate one contiguous transition sequence."""

    ordered = sorted(
        tuple(transitions),
        key=lambda row: (
            row["start_timestamp_ms"],
            row["end_timestamp_ms"],
            row["transition_id"],
        ),
    )

    if not ordered:
        raise ValueError(
            "Motion synthesis requires at least one transition."
        )

    timeline = []

    for index, row in enumerate(ordered):
        start = int(row["start_timestamp_ms"])
        end = int(row["end_timestamp_ms"])

        if end <= start:
            raise ValueError(
                f"Invalid transition timestamps: {start} -> {end}"
            )

        if index:
            previous_end = timeline[-1]["end_timestamp_ms"]
            if start != previous_end:
                raise ValueError(
                    "Transition sequence is not contiguous: "
                    f"{previous_end} -> {start}"
                )

        timeline.append(
            {
                "transition_id": row["transition_id"],
                "start_timestamp_ms": start,
                "end_timestamp_ms": end,
                "status": row["status"],
                "text": row["text"],
            }
        )

    return timeline


class QwenMotionSynthesiser:
    """Synthesize a complete motion account from direct comparisons."""

    def __init__(
        self,
        *,
        model_path: str | Path,
        executable: str = "llama-cli",
        analyser_version: str | None = None,
        runner: Runner = _default_runner,
        timeout_seconds: int = 900,
    ):
        self.model_path = Path(model_path).expanduser().resolve()
        self.executable = executable
        self.analyser_version = analyser_version
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def analyse(
        self,
        timeline: list[dict[str, Any]],
    ) -> MotionAnalysisResult:
        if shutil.which(self.executable) is None:
            raise FileNotFoundError(
                f"Motion runtime not found: {self.executable}"
            )
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Motion model not found: {self.model_path}"
            )

        evidence = [
            {
                "transition_id": item["transition_id"],
                "start_timestamp_ms":
                    item["start_timestamp_ms"],
                "end_timestamp_ms":
                    item["end_timestamp_ms"],
                "comparison": item["text"],
            }
            for item in timeline
        ]

        prompt = (
            MOTION_PROMPT
            + "\nOrdered transition evidence:\n"
            + json.dumps(
                evidence,
                indent=2,
                ensure_ascii=False,
            )
        )

        command = [
            self.executable,
            "--single-turn",
            "--simple-io",
            "--model",
            str(self.model_path),
            "--ctx-size",
            "16384",
            "--n-gpu-layers",
            "99",
            "--temp",
            "0.1",
            "--predict",
            "1400",
            "--prompt",
            prompt,
        ]

        process = self.runner(command, self.timeout_seconds)

        if process.returncode != 0:
            diagnostic = (
                process.stderr or process.stdout
            ).strip()
            raise RuntimeError(
                "Qwen motion synthesis failed: "
                + diagnostic[-4000:]
            )

        response = extract_model_response(
            process.stdout,
            prompt,
        )
        heading = response.find("VIDEO MOTION OVERVIEW")

        if heading >= 0:
            response = response[heading:].strip()

        if not response:
            raise RuntimeError(
                "Qwen motion synthesis returned no response."
            )

        return MotionAnalysisResult(
            text=response,
            diagnostics=process.stderr.strip(),
            command=tuple(command),
        )


def synthesise_motion_and_persist(
    *,
    video_object_id: str,
    video_acquisition_id: str,
    transitions: Iterable,
    repository,
    analyser: QwenMotionSynthesiser,
) -> VideoMotionSynthesis:
    """Create and preserve one video-level direct-motion account."""

    timeline = ordered_transition_timeline(transitions)
    result = analyser.analyse(timeline)

    synthesis = VideoMotionSynthesis(
        video_object_id=video_object_id,
        video_acquisition_id=video_acquisition_id,
        text=result.text,
        start_timestamp_ms=timeline[0]["start_timestamp_ms"],
        end_timestamp_ms=timeline[-1]["end_timestamp_ms"],
        transition_ids=[
            item["transition_id"]
            for item in timeline
        ],
        timeline=timeline,
        analyser="Qwen3-VL-8B-Instruct-GGUF-motion-synthesis",
        analyser_version=analyser.analyser_version,
        status="derived_unreviewed",
        metadata={
            "method": "semantic_synthesis_of_direct_frame_pairs",
            "transition_count": len(timeline),
            "continuous_motion_inferred": False,
            "model_filename": analyser.model_path.name,
            "runtime": analyser.executable,
            "runtime_diagnostics":
                result.diagnostics[-4000:],
            "review_status": "UNREVIEWED",
        },
    )

    repository.save_video_motion_synthesis(synthesis)
    return synthesis
