from __future__ import annotations

from typing import Any, Callable

from warrigal.acquisition.manifest import ManifestResource
from warrigal.acquisition.web import WebFetcher
from warrigal.acquisition.web_documents import (
    WebDocumentResult,
    ingest_web_pdf,
)
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


PdfIngestor = Callable[..., WebDocumentResult]

_PRESERVED_PDF_STATUSES = {
    "ingested",
    "duplicate",
    "no_text",
}


def make_pdf_manifest_handler(
    *,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    discovery_metadata: dict[str, Any] | None = None,
    fetcher: WebFetcher | None = None,
    ingestor: PdfIngestor = ingest_web_pdf,
):
    """
    Build a manifest-runner handler backed by Warrigal web PDF ingestion.

    The handler performs no discovery. It accepts only the resource handed
    to it by the bounded manifest runner.
    """

    base_discovery_metadata = dict(discovery_metadata or {})

    def handle(resource: ManifestResource) -> dict[str, Any]:
        if resource.media_type != "application/pdf":
            raise ValueError(
                "PDF manifest handler received non-PDF resource: "
                f"{resource.media_type!r}"
            )

        metadata = {
            **base_discovery_metadata,
            "manifest_resource_url": resource.url,
            "manifest_resource_status": resource.status,
            "manifest_resource_expected_size_bytes": (
                resource.expected_size_bytes
            ),
            **resource.metadata,
        }

        result = ingestor(
            resource.url,
            repository=repository,
            object_store=object_store,
            job_id=job_id,
            node_id=node_id,
            batch_id=batch_id,
            collection_id=collection_id,
            discovery_metadata=metadata,
            fetcher=fetcher,
        )

        if result.status not in _PRESERVED_PDF_STATUSES:
            raise RuntimeError(
                "Warrigal PDF ingestion did not complete successfully: "
                f"status={result.status!r}, error={result.error!r}"
            )

        if result.object_id is None:
            raise RuntimeError(
                "Warrigal PDF ingestion returned no object_id."
            )

        if result.acquisition_id is None:
            raise RuntimeError(
                "Warrigal PDF ingestion returned no acquisition_id."
            )

        if result.sha256 is None:
            raise RuntimeError(
                "Warrigal PDF ingestion returned no sha256."
            )

        return {
            "web_document_status": result.status,
            "object_id": result.object_id,
            "acquisition_id": result.acquisition_id,
            "sha256": result.sha256,
            "size_bytes": result.size_bytes,
            "passage_count": result.passage_count,
            "deduplicated": result.deduplicated,
            "final_url": result.final_url,
        }

    return handle
