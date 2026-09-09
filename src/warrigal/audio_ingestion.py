from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from warrigal.acquisition.service import AcquisitionService
from warrigal.audio import TranscriptResult, transcribe_audio
from warrigal.models import Passage, Source


@dataclass(frozen=True)
class AudioIngestionResult:
    transcript_object_id: str
    transcript_acquisition_id: str
    passage_count: int
    transcript: TranscriptResult


def ingest_audio_object(
    *,
    source_object_id: str,
    source_acquisition_id: str,
    source_path: str | Path,
    source_url: str,
    source_title: str,
    model_path: str | Path,
    repository,
    object_store,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str | None = None,
    transcriber=transcribe_audio,
) -> AudioIngestionResult:
    """Preserve a derived transcript and its timestamped passages."""

    source_object = repository.get_object(source_object_id)
    if source_object is None:
        raise ValueError("Source object does not exist")

    transcript = transcriber(source_path, model_path=model_path)

    source = Source(
        source_type="audio_transcript",
        locator=source_url,
        title=source_title,
        metadata={
            "derived_from_object_id": source_object_id,
            "derived_from_acquisition_id": source_acquisition_id,
            "model_path": str(model_path),
        },
    )
    repository.save_source(source)

    service = AcquisitionService(repository, object_store)
    acquired = service.acquire_bytes(
        data=transcript.raw_json,
        source_id=source.source_id,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        method="whisper_cpp_transcription",
        mime_type="application/json",
        original_filename="transcript.json",
        collection_id=collection_id,
        metadata={
            "derived_from_object_id": source_object_id,
            "derived_from_acquisition_id": source_acquisition_id,
            "segment_count": len(transcript.segments),
        },
    )

    passage_count = 0
    if not repository.object_has_passages(acquired.object_id):
        for segment in transcript.segments:
            if not segment.text:
                continue

            repository.save_passage(
                Passage(
                    object_id=acquired.object_id,
                    acquisition_id=acquired.acquisition_id,
                    passage_index=segment.index,
                    text=segment.text,
                    source_url=source_url,
                    source_title=source_title,
                    metadata={
                        "source_field": "transcription",
                        "start_ms": segment.start_ms,
                        "end_ms": segment.end_ms,
                        "derived_from_object_id": source_object_id,
                        "derived_from_acquisition_id": source_acquisition_id,
                    },
                )
            )
            passage_count += 1

    return AudioIngestionResult(
        transcript_object_id=acquired.object_id,
        transcript_acquisition_id=acquired.acquisition_id,
        passage_count=passage_count,
        transcript=transcript,
    )
