from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from warrigal.acquisition.content import extract_pdf_content
from warrigal.acquisition.service import AcquisitionService
from warrigal.acquisition.web import WebFetcher
from warrigal.models import Passage as PassageRecord
from warrigal.models import Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.retrieval.passages import split_into_passages


@dataclass(frozen=True)
class WebDocumentResult:
    """Outcome of ingesting one remote document."""

    url: str
    final_url: str
    status: str
    object_id: str | None = None
    acquisition_id: str | None = None
    sha256: str | None = None
    size_bytes: int = 0
    passage_count: int = 0
    deduplicated: bool = False
    error: str | None = None


def ingest_web_pdf(
    url: str,
    *,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    discovery_metadata: dict | None = None,
    fetcher: WebFetcher | None = None,
) -> WebDocumentResult:
    """Fetch, preserve, and index one remote PDF with discovery provenance."""

    fetcher = fetcher or WebFetcher()

    try:
        response = fetcher.fetch(url)

        filename = unquote(
            PurePosixPath(urlparse(response.final_url).path).name
        ) or None

        metadata = {
            "requested_url": url,
            "final_url": response.final_url,
            "content_type": response.content_type,
            **(discovery_metadata or {}),
        }

        source = Source(
            source_type="web_document",
            locator=url,
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
            method="web_document",
            mime_type=response.content_type or "application/pdf",
            original_filename=filename,
            collection_id=collection_id,
            http_status=response.status,
            metadata=metadata,
        )

        if repository.object_has_passages(acquisition.object_id):
            return WebDocumentResult(
                url=url,
                final_url=response.final_url,
                status="duplicate",
                object_id=acquisition.object_id,
                acquisition_id=acquisition.acquisition_id,
                sha256=acquisition.sha256,
                size_bytes=acquisition.size_bytes,
                deduplicated=True,
            )

        content = extract_pdf_content(response.data)

        if not content.text.strip():
            return WebDocumentResult(
                url=url,
                final_url=response.final_url,
                status="no_text",
                object_id=acquisition.object_id,
                acquisition_id=acquisition.acquisition_id,
                sha256=acquisition.sha256,
                size_bytes=acquisition.size_bytes,
                deduplicated=acquisition.deduplicated,
            )

        passages = split_into_passages(
            content.text,
            source_url=response.final_url,
            source_title=content.title or filename or response.final_url,
            object_id=acquisition.object_id,
            acquisition_id=acquisition.acquisition_id,
        )

        for passage in passages:
            repository.save_passage(
                PassageRecord(
                    object_id=acquisition.object_id,
                    acquisition_id=acquisition.acquisition_id,
                    passage_index=passage.index,
                    text=passage.text,
                    source_url=passage.source_url,
                    source_title=passage.source_title,
                )
            )

        return WebDocumentResult(
            url=url,
            final_url=response.final_url,
            status="ingested",
            object_id=acquisition.object_id,
            acquisition_id=acquisition.acquisition_id,
            sha256=acquisition.sha256,
            size_bytes=acquisition.size_bytes,
            passage_count=len(passages),
            deduplicated=acquisition.deduplicated,
        )

    except Exception as exc:
        return WebDocumentResult(
            url=url,
            final_url=url,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
