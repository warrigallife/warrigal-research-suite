from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from warrigal.models import VideoTemporalSynthesis


_SECTION = re.compile(
    r"(?ms)^([A-Z][A-Z /&]+):\s*\n(.*?)(?=^[A-Z][A-Z /&]+:\s*\n|\Z)"
)


def parse_observation_sections(text: str) -> dict[str, list[str]]:
    """Parse the structured sections produced by the frame prompt."""

    sections: dict[str, list[str]] = {}

    for heading, body in _SECTION.findall(text):
        values = [
            line.strip(" -*\t")
            for line in body.splitlines()
            if line.strip(" -*\t")
        ]
        sections[heading.strip()] = values

    return sections


def _meaningful(values: Iterable[str]) -> list[str]:
    ignored = {"UNKNOWN", "NONE", "N/A", "NOT VISIBLE"}
    return [
        value
        for value in values
        if value.strip().upper() not in ignored
    ]


def _evidence_terms(
    sections: dict[str, list[str]],
) -> list[str]:
    terms: list[str] = []

    for heading in (
        "VISIBLE SUBJECTS",
        "VISIBLE OBJECTS",
        "READABLE TEXT",
    ):
        for value in _meaningful(sections.get(heading, [])):
            if value not in terms:
                terms.append(value)

    return terms


def _frame_summary(
    timestamp_ms: int,
    terms: list[str],
) -> str:
    seconds = timestamp_ms / 1000

    if not terms:
        return f"At {seconds:.3f}s, no definite visual content was recorded."

    return f"At {seconds:.3f}s, the observation records: " + "; ".join(terms)


def synthesise_temporal_change(
    *,
    video_object_id: str,
    video_acquisition_id: str,
    frames: Iterable,
    repository,
) -> VideoTemporalSynthesis:
    """
    Compare ordered frame observations and create an evidence-linked timeline.

    This comparator does not inspect pixels or invent motion between samples.
    It reports only differences between the stored frame observations.
    """

    ordered_frames = sorted(
        tuple(frames),
        key=lambda frame: (
            frame.timestamp_ms,
            frame.frame_index,
            frame.frame_object_id,
        ),
    )

    if not ordered_frames:
        raise ValueError("Temporal synthesis requires at least one frame.")

    evidence: list[dict[str, Any]] = []
    missing: list[str] = []

    for frame in ordered_frames:
        observations = repository.get_visual_observations_for_frame(
            frame.frame_object_id
        )

        if not observations:
            missing.append(frame.frame_object_id)
            continue

        latest = observations[-1]
        sections = parse_observation_sections(latest["text"])
        terms = _evidence_terms(sections)

        evidence.append(
            {
                "frame_index": frame.frame_index,
                "timestamp_ms": frame.timestamp_ms,
                "frame_object_id": frame.frame_object_id,
                "frame_acquisition_id":
                    frame.frame_acquisition_id,
                "observation_id": latest["observation_id"],
                "observation_status": latest["status"],
                "terms": terms,
                "sections": sections,
                "frame_summary": _frame_summary(
                    frame.timestamp_ms,
                    terms,
                ),
            }
        )

    if missing:
        raise ValueError(
            "Temporal synthesis stopped because frames lack observations: "
            + ", ".join(missing)
        )

    timeline: list[dict[str, Any]] = []
    previous_terms: list[str] = []

    for index, item in enumerate(evidence):
        terms = item["terms"]
        added = [
            term for term in terms
            if term not in previous_terms
        ]
        removed = [
            term for term in previous_terms
            if term not in terms
        ]

        if index == 0:
            change = "Initial sampled state."
        elif added and removed:
            change = (
                "Newly recorded: "
                + "; ".join(added)
                + ". No longer recorded in this sample: "
                + "; ".join(removed)
                + "."
            )
        elif added:
            change = "Newly recorded: " + "; ".join(added) + "."
        elif removed:
            change = (
                "No longer recorded in this sample: "
                + "; ".join(removed)
                + "."
            )
        else:
            change = "No textual observation change detected."

        timeline.append(
            {
                **item,
                "added_terms": added,
                "removed_terms": removed,
                "change_from_previous_sample": change,
            }
        )
        previous_terms = terms

    lines = [
        "VIDEO TEMPORAL SYNTHESIS",
        "",
        (
            f"Compared {len(timeline)} sampled frames in chronological "
            "order."
        ),
        (
            "This account describes differences between sampled frame "
            "observations; it does not claim continuous motion between "
            "timestamps."
        ),
        "",
        "TIMELINE:",
    ]

    for item in timeline:
        seconds = item["timestamp_ms"] / 1000
        lines.extend(
            [
                "",
                f"{seconds:.3f}s",
                item["frame_summary"],
                item["change_from_previous_sample"],
                (
                    "Evidence: "
                    f"{item['frame_object_id']} / "
                    f"{item['observation_id']}"
                ),
            ]
        )

    return VideoTemporalSynthesis(
        video_object_id=video_object_id,
        video_acquisition_id=video_acquisition_id,
        text="\n".join(lines),
        frame_count=len(timeline),
        observation_ids=[
            item["observation_id"]
            for item in timeline
        ],
        timeline=timeline,
        metadata={
            "method": "ordered_structured_observation_comparison",
            "continuous_motion_inferred": False,
            "sampled_frame_count": len(timeline),
            "review_status": "UNREVIEWED",
        },
    )


def synthesise_and_persist(
    *,
    video_object_id: str,
    video_acquisition_id: str,
    frames: Iterable,
    repository,
) -> VideoTemporalSynthesis:
    """Create and persist a video-level temporal synthesis."""

    synthesis = synthesise_temporal_change(
        video_object_id=video_object_id,
        video_acquisition_id=video_acquisition_id,
        frames=frames,
        repository=repository,
    )
    repository.save_video_temporal_synthesis(synthesis)
    return synthesis


@dataclass(frozen=True)
class TemporalAnalysisResult:
    """Text-only semantic analysis of ordered frame evidence."""

    text: str
    diagnostics: str
    command: tuple[str, ...]


class QwenTemporalAnalyser:
    """Use a local model to interpret an evidence-linked frame timeline."""

    def __init__(
        self,
        *,
        model_path: str | Path,
        executable: str = "llama-cli",
        analyser_version: str | None = None,
        runner=None,
        timeout_seconds: int = 900,
    ):
        import subprocess

        self.model_path = Path(model_path).expanduser().resolve()
        self.executable = executable
        self.analyser_version = analyser_version
        self.timeout_seconds = timeout_seconds

        if runner is None:
            def runner(command, timeout):
                return subprocess.run(
                    command,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )

        self.runner = runner

    def analyse_timeline(
        self,
        timeline: list[dict[str, Any]],
    ) -> TemporalAnalysisResult:
        import json
        import shutil

        from warrigal.qwen_visual import extract_model_response

        if shutil.which(self.executable) is None:
            raise FileNotFoundError(
                f"Temporal runtime not found: {self.executable}"
            )
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Temporal model not found: {self.model_path}"
            )

        evidence = [
            {
                "timestamp_ms": item["timestamp_ms"],
                "frame_object_id": item["frame_object_id"],
                "observation_id": item["observation_id"],
                "observation_sections": item.get(
                    "sections",
                    {},
                ),
            }
            for item in timeline
        ]

        prompt = """Analyse this ordered set of sampled video-frame evidence.

Rules:
1. Treat synonymous or paraphrased descriptions as potentially the same object.
2. Do not report disappearance merely because later wording differs.
3. READABLE TEXT records labels only. A named object is not visually
   present unless VISIBLE SUBJECTS or VISIBLE OBJECTS supports it.
4. Separate initial state, newly appearing elements, persistent elements,
   disappearing elements, and genuinely uncertain changes.
5. Do not claim continuous motion between sampled timestamps.
6. Do not invent anything absent from the evidence.
7. Cite timestamps for every claimed change.
8. State explicitly when the samples cannot establish whether geometry,
   movement, or appearance changed.
9. Finish with a concise overall account of the sampled video progression.

Return these headings:
INITIAL STATE
OBSERVED TEMPORAL CHANGES
PERSISTENT ELEMENTS
UNCERTAIN OR UNRESOLVED CHANGES
OVERALL SAMPLED PROGRESSION

Evidence:
""" + json.dumps(evidence, indent=2, ensure_ascii=False)

        command = [
            self.executable,
            "--single-turn",
            "--simple-io",
            "--model",
            str(self.model_path),
            "--ctx-size",
            "8192",
            "--n-gpu-layers",
            "99",
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
                "Qwen temporal synthesis failed: "
                + diagnostic[-4000:]
            )

        response = extract_model_response(
            process.stdout,
            prompt,
        )
        heading_position = response.find("INITIAL STATE")
        if heading_position >= 0:
            response = response[heading_position:].strip()

        if not response:
            raise RuntimeError(
                "Qwen temporal synthesis returned no response."
            )

        return TemporalAnalysisResult(
            text=response,
            diagnostics=process.stderr.strip(),
            command=tuple(command),
        )


def semantic_synthesise_and_persist(
    *,
    video_object_id: str,
    video_acquisition_id: str,
    frames: Iterable,
    repository,
    analyser: QwenTemporalAnalyser,
) -> VideoTemporalSynthesis:
    """
    Preserve a semantic video-level synthesis over deterministic evidence.

    The underlying ordered timeline remains attached to the record so the
    model's interpretation can always be audited against its source frames.
    """

    baseline = synthesise_temporal_change(
        video_object_id=video_object_id,
        video_acquisition_id=video_acquisition_id,
        frames=frames,
        repository=repository,
    )

    result = analyser.analyse_timeline(baseline.timeline)

    synthesis = VideoTemporalSynthesis(
        video_object_id=video_object_id,
        video_acquisition_id=video_acquisition_id,
        text=result.text,
        frame_count=baseline.frame_count,
        observation_ids=baseline.observation_ids,
        timeline=baseline.timeline,
        analyser="Qwen3-VL-8B-Instruct-GGUF-temporal",
        analyser_version=analyser.analyser_version,
        status="derived_unreviewed",
        metadata={
            **baseline.metadata,
            "semantic_temporal_synthesis": True,
            "semantic_pipeline_version": 2,
            "semantic_temperature": 0.1,
            "semantic_maximum_output_tokens": 900,
            "model_filename": analyser.model_path.name,
            "runtime": analyser.executable,
            "runtime_diagnostics":
                result.diagnostics[-4000:],
            "review_status": "UNREVIEWED",
        },
    )

    repository.save_video_temporal_synthesis(synthesis)
    return synthesis
