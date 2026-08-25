from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from warrigal.models import Acquisition, Object, StorageLocation
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


@dataclass
class AcquisitionResult:
    """Result returned after Warrigal preserves acquired bytes."""

    object_id: str
    acquisition_id: str
    sha256: str
    size_bytes: int
    archive_path: str
    deduplicated: bool


class AcquisitionService:
    """Coordinate preservation, deduplication, and provenance."""

    def __init__(
        self,
        repository: WarrigalRepository,
        object_store: ObjectStore,
    ):
        self.repository = repository
        self.object_store = object_store

    def acquire_bytes(
        self,
        *,
        data: bytes,
        source_id: str,
        job_id: str,
        node_id: str,
        batch_id: str,
        method: str,
        mime_type: str | None = None,
        original_filename: str | None = None,
        collection_id: str | None = None,
        http_status: int | None = None,
        metadata: dict | None = None,
    ) -> AcquisitionResult:
        """Preserve bytes and record their acquisition provenance."""

        stored = self.object_store.store_bytes(data)

        existing = self.repository.get_object_by_hash(stored.sha256)

        if existing is not None:
            object_id = existing["object_id"]
            deduplicated = True
        else:
            obj = Object(
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                mime_type=mime_type,
                original_filename=original_filename,
            )
            self.repository.save_object(obj)
            object_id = obj.object_id
            deduplicated = False

        storage = StorageLocation(
            object_id=object_id,
            location_type="local_archive",
            path=str(stored.path),
            node_id=node_id,
            verified_at=datetime.now(timezone.utc),
        )
        self.repository.save_storage_location(storage)

        acquisition = Acquisition(
            source_id=source_id,
            object_id=object_id,
            job_id=job_id,
            node_id=node_id,
            batch_id=batch_id,
            method=method,
            status="success",
            http_status=http_status,
            metadata=metadata or {},
        )
        self.repository.save_acquisition(acquisition)

        if collection_id is not None:
            self.repository.add_object_to_collection(
                collection_id,
                object_id,
            )

        return AcquisitionResult(
            object_id=object_id,
            acquisition_id=acquisition.acquisition_id,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            archive_path=str(stored.path),
            deduplicated=deduplicated,
        )