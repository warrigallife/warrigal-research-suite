from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from warrigal.acquisition.manifest import ManifestResource
from warrigal.acquisition.service import AcquisitionService
from warrigal.acquisition.web import WebFetcher
from warrigal.acquisition.web_documents import (
    WebDocumentResult,
    ingest_web_pdf,
)
from warrigal.models import Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


PdfIngestor = Callable[..., WebDocumentResult]

_PRESERVED_PDF_STATUSES = {
    "ingested",
    "duplicate",
    "no_text",
    "repaired",
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
            "original_object_id": result.original_object_id,
            "original_acquisition_id": result.original_acquisition_id,
            "original_sha256": result.original_sha256,
            "original_size_bytes": result.original_size_bytes,
            "repair_tool": result.repair_tool,
            "repair_error": result.error,
        }

    return handle



def make_web_archive_manifest_handler(
    *,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    discovery_metadata: dict[str, Any] | None = None,
    fetcher: WebFetcher | None = None,
    service_factory: Callable[..., AcquisitionService] = AcquisitionService,
):
    """
    Build a bounded manifest handler for raw web archive preservation.

    The handler preserves the fetched archive bytes as one Warrigal object.
    It deliberately does not inspect, unpack, or interpret archive contents.
    """

    fetcher = fetcher or WebFetcher()
    base_discovery_metadata = dict(discovery_metadata or {})

    def handle(resource: ManifestResource) -> dict[str, Any]:
        if resource.media_type != "application/zip":
            raise ValueError(
                "Web archive manifest handler received unsupported resource: "
                f"{resource.media_type!r}"
            )

        response = fetcher.fetch(resource.url)

        filename = unquote(
            PurePosixPath(urlparse(response.final_url).path).name
        ) or None

        metadata = {
            **base_discovery_metadata,
            **resource.metadata,
            "requested_url": resource.url,
            "final_url": response.final_url,
            "content_type": response.content_type,
            "manifest_resource_url": resource.url,
            "manifest_resource_status": resource.status,
            "manifest_resource_expected_size_bytes": (
                resource.expected_size_bytes
            ),
            "archive_contents_processed": False,
        }

        source = Source(
            source_type="web_archive",
            locator=resource.url,
            final_locator=response.final_url,
            title=filename,
            metadata=metadata,
        )
        repository.save_source(source)

        service = service_factory(
            repository=repository,
            object_store=object_store,
        )

        acquisition = service.acquire_bytes(
            data=response.data,
            source_id=source.source_id,
            job_id=job_id,
            node_id=node_id,
            batch_id=batch_id,
            method="web_archive",
            mime_type=response.content_type or resource.media_type,
            original_filename=filename,
            collection_id=collection_id,
            http_status=response.status,
            metadata=metadata,
        )

        return {
            "object_id": acquisition.object_id,
            "acquisition_id": acquisition.acquisition_id,
            "sha256": acquisition.sha256,
            "size_bytes": acquisition.size_bytes,
            "deduplicated": acquisition.deduplicated,
            "archive_path": acquisition.archive_path,
            "final_url": response.final_url,
            "archive_contents_processed": False,
        }

    return handle


_GENERIC_DOCUMENT_MEDIA_TYPES = {
    "application/msword",
    "text/plain",
    "text/csv",
    "image/vnd.djvu",
}


def extract_generic_document_text(
    data: bytes,
    *,
    media_type: str,
    filename: str | None,
) -> tuple[str, str]:
    """
    Extract readable text without modifying the preserved original.

    Returns (text, extraction_status). DJVU is preserved but deliberately
    left uninterpreted until a dedicated DJVU extractor is installed.
    """
    import subprocess
    from pathlib import Path
    from tempfile import TemporaryDirectory

    if media_type in {"text/plain", "text/csv"}:
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return data.decode(encoding), f"decoded:{encoding}"
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace"), "decoded:replacement"

    if media_type == "application/msword":
        textutil = Path("/usr/bin/textutil")
        if not textutil.is_file():
            raise RuntimeError(
                "macOS textutil is required for legacy Word extraction."
            )

        suffix = PurePosixPath(filename or "document.doc").suffix or ".doc"

        with TemporaryDirectory(
            prefix="warrigal-document-extraction-"
        ) as temporary:
            source = Path(temporary) / f"source{suffix}"
            source.write_bytes(data)

            process = subprocess.run(
                [
                    str(textutil),
                    "-convert",
                    "txt",
                    "-stdout",
                    str(source),
                ],
                capture_output=True,
            )

            if process.returncode:
                diagnostic = (
                    process.stderr.decode(
                        "utf-8",
                        errors="replace",
                    ).strip()
                    or f"textutil exited with status {process.returncode}"
                )
                raise RuntimeError(
                    f"Legacy Word extraction failed: {diagnostic}"
                )

            return (
                process.stdout.decode("utf-8", errors="replace"),
                "extracted:textutil",
            )

    if media_type == "image/vnd.djvu":
        return "", "preserved:extraction_not_supported"

    raise ValueError(
        f"Unsupported generic-document media type: {media_type!r}"
    )


def make_generic_document_manifest_handler(
    *,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    discovery_metadata: dict[str, Any] | None = None,
    fetcher: WebFetcher | None = None,
    extractor: Callable[..., tuple[str, str]] = (
        extract_generic_document_text
    ),
):
    """
    Preserve DOC, TXT, CSV and DJVU originals and index readable text.

    Extraction failure never discards an acquired original. The failure
    is returned as metadata for later recovery or review.
    """
    from warrigal.models import Passage as PassageRecord
    from warrigal.retrieval.passages import split_into_passages

    fetcher = fetcher or WebFetcher()
    base_discovery_metadata = dict(discovery_metadata or {})

    def handle(resource: ManifestResource) -> dict[str, Any]:
        if resource.media_type not in _GENERIC_DOCUMENT_MEDIA_TYPES:
            raise ValueError(
                "Generic document handler received unsupported resource: "
                f"{resource.media_type!r}"
            )

        response = fetcher.fetch(resource.url)

        filename = unquote(
            PurePosixPath(urlparse(response.final_url).path).name
        ) or None

        metadata = {
            **base_discovery_metadata,
            **resource.metadata,
            "requested_url": resource.url,
            "final_url": response.final_url,
            "content_type": response.content_type,
            "manifest_resource_url": resource.url,
            "manifest_resource_status": resource.status,
            "manifest_resource_expected_size_bytes": (
                resource.expected_size_bytes
            ),
            "evidence_role": "original_remote_document",
        }

        source = Source(
            source_type="web_document",
            locator=resource.url,
            final_locator=response.final_url,
            title=filename,
            metadata=metadata,
        )
        repository.save_source(source)

        service = AcquisitionService(
            repository=repository,
            object_store=object_store,
        )

        acquisition = service.acquire_bytes(
            data=response.data,
            source_id=source.source_id,
            job_id=job_id,
            node_id=node_id,
            batch_id=batch_id,
            method="web_document_generic",
            mime_type=(
                response.content_type
                or resource.media_type
                or "application/octet-stream"
            ),
            original_filename=filename,
            collection_id=collection_id,
            http_status=response.status,
            metadata=metadata,
        )

        passage_count = 0
        extraction_status = "not_attempted"
        extraction_error = None

        if repository.object_has_passages(acquisition.object_id):
            extraction_status = "already_indexed"
        else:
            try:
                text, extraction_status = extractor(
                    response.data,
                    media_type=resource.media_type,
                    filename=filename,
                )

                if text.strip():
                    passages = split_into_passages(
                        text,
                        source_url=response.final_url,
                        source_title=filename or response.final_url,
                        object_id=acquisition.object_id,
                        acquisition_id=acquisition.acquisition_id,
                    )

                    for passage in passages:
                        repository.save_passage(
                            PassageRecord(
                                object_id=acquisition.object_id,
                                acquisition_id=(
                                    acquisition.acquisition_id
                                ),
                                passage_index=passage.index,
                                text=passage.text,
                                source_url=passage.source_url,
                                source_title=passage.source_title,
                            )
                        )

                    passage_count = len(passages)

            except Exception as exc:
                extraction_status = "preserved:extraction_failed"
                extraction_error = f"{type(exc).__name__}: {exc}"

        return {
            "web_document_status": "preserved",
            "object_id": acquisition.object_id,
            "acquisition_id": acquisition.acquisition_id,
            "sha256": acquisition.sha256,
            "size_bytes": acquisition.size_bytes,
            "passage_count": passage_count,
            "deduplicated": acquisition.deduplicated,
            "final_url": response.final_url,
            "text_extraction_status": extraction_status,
            "text_extraction_error": extraction_error,
            "original_filename": filename,
        }

    return handle
