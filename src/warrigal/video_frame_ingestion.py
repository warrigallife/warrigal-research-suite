from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from warrigal.acquisition.service import AcquisitionService
from warrigal.models import Source
from warrigal.video_frames import VideoFrame, extract_video_frames


@dataclass(frozen=True)
class ArchivedVideoFrame:
    frame_object_id: str
    frame_acquisition_id: str
    timestamp_ms: int
    frame_index: int


@dataclass(frozen=True)
class VideoFrameIngestionResult:
    source_object_id: str
    frames: tuple[ArchivedVideoFrame, ...]


def ingest_video_frames(
    *,
    source_object_id: str,
    source_acquisition_id: str,
    source_path: str | Path,
    source_url: str,
    source_title: str,
    repository,
    object_store,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str | None = None,
    interval_seconds: float = 10.0,
    extractor=extract_video_frames,
) -> VideoFrameIngestionResult:
    """Extract and archive timestamped visual evidence from an archived video."""
    source_object = repository.get_object(source_object_id)

    if source_object is None:
        raise ValueError("Source object does not exist")

    extracted = extractor(
        source_path,
        interval_seconds=interval_seconds,
    )

    service = AcquisitionService(repository, object_store)
    archived_frames: list[ArchivedVideoFrame] = []

    for frame in extracted:
        if not isinstance(frame, VideoFrame):
            raise TypeError("Extractor returned an invalid frame")

        source = Source(
            source_type="video_frame",
            locator=source_url,
            title=f"{source_title} @ {frame.timestamp_ms} ms",
            metadata={
                "derived_from_object_id": source_object_id,
                "derived_from_acquisition_id": source_acquisition_id,
                "frame_index": frame.index,
                "timestamp_ms": frame.timestamp_ms,
            },
        )
        repository.save_source(source)

        acquired = service.acquire_bytes(
            data=frame.image_bytes,
            source_id=source.source_id,
            job_id=job_id,
            node_id=node_id,
            batch_id=batch_id,
            method="video_frame_extraction",
            mime_type="image/jpeg",
            original_filename=f"frame-{frame.index:06d}.jpg",
            collection_id=collection_id,
            metadata={
                "derived_from_object_id": source_object_id,
                "derived_from_acquisition_id": source_acquisition_id,
                "frame_index": frame.index,
                "timestamp_ms": frame.timestamp_ms,
                "source_url": source_url,
            },
        )

        archived_frames.append(
            ArchivedVideoFrame(
                frame_object_id=acquired.object_id,
                frame_acquisition_id=acquired.acquisition_id,
                timestamp_ms=frame.timestamp_ms,
                frame_index=frame.index,
            )
        )

    return VideoFrameIngestionResult(
        source_object_id=source_object_id,
        frames=tuple(archived_frames),
    )
