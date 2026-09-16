from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from warrigal.acquisition.content import extract_pdf_content
from warrigal.acquisition.service import AcquisitionService
from warrigal.acquisition.web import WebFetcher
from warrigal.models import Passage as PassageRecord
from warrigal.models import Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.retrieval.passages import split_into_passages


PdfRepairer = Callable[[bytes], bytes]


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

    original_object_id: str | None = None
    original_acquisition_id: str | None = None
    original_sha256: str | None = None
    original_size_bytes: int = 0
    repair_tool: str | None = None


def repair_pdf_with_qpdf(data: bytes) -> bytes:
    """
    Produce a repaired PDF derivative using qpdf.

    The original bytes are never changed. qpdf exit status 3 means it
    produced output while reporting warnings, which remains acceptable
    only if Warrigal can subsequently parse the produced derivative.
    """

    executable = shutil.which("qpdf")
    if executable is None:
        raise RuntimeError(
            "qpdf is required for damaged-PDF recovery but is not installed."
        )

    with TemporaryDirectory(prefix="warrigal-pdf-repair-") as temporary:
        root = Path(temporary)
        source = root / "original.pdf"
        repaired = root / "repaired.pdf"

        source.write_bytes(data)

        process = subprocess.run(
            [
                executable,
                "--object-streams=generate",
                str(source),
                str(repaired),
            ],
            capture_output=True,
            text=True,
        )

        if process.returncode not in {0, 3}:
            diagnostic = (
                process.stderr.strip()
                or process.stdout.strip()
                or f"qpdf exited with status {process.returncode}"
            )
            raise RuntimeError(f"qpdf repair failed: {diagnostic}")

        if not repaired.is_file():
            raise RuntimeError("qpdf reported success but produced no output.")

        repaired_data = repaired.read_bytes()

        if not repaired_data.startswith(b"%PDF-"):
            raise RuntimeError(
                "qpdf output did not contain a valid PDF signature."
            )

        return repaired_data


def _save_passages(
    content,
    *,
    source_url: str,
    source_title: str,
    object_id: str,
    acquisition_id: str,
    repository: WarrigalRepository,
) -> int:
    if not content.text.strip():
        return 0

    passages = split_into_passages(
        content.text,
        source_url=source_url,
        source_title=source_title,
        object_id=object_id,
        acquisition_id=acquisition_id,
    )

    for passage in passages:
        repository.save_passage(
            PassageRecord(
                object_id=object_id,
                acquisition_id=acquisition_id,
                passage_index=passage.index,
                text=passage.text,
                source_url=passage.source_url,
                source_title=passage.source_title,
            )
        )

    return len(passages)


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
    repairer: PdfRepairer | None = repair_pdf_with_qpdf,
) -> WebDocumentResult:
    """
    Fetch, preserve and index one remote PDF.

    Original remote bytes are acquired before parsing. If normal parsing
    fails, a repaired derivative may be created and acquired separately.
    """

    fetcher = fetcher or WebFetcher()
    response = None
    original_acquisition = None

    try:
        response = fetcher.fetch(url)

        filename = unquote(
            PurePosixPath(urlparse(response.final_url).path).name
        ) or None

        metadata = {
            "requested_url": url,
            "final_url": response.final_url,
            "content_type": response.content_type,
            "evidence_role": "original_remote_document",
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

        original_acquisition = service.acquire_bytes(
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

        if repository.object_has_passages(original_acquisition.object_id):
            return WebDocumentResult(
                url=url,
                final_url=response.final_url,
                status="duplicate",
                object_id=original_acquisition.object_id,
                acquisition_id=original_acquisition.acquisition_id,
                sha256=original_acquisition.sha256,
                size_bytes=original_acquisition.size_bytes,
                deduplicated=True,
            )

        try:
            content = extract_pdf_content(response.data)
        except Exception as parse_error:
            if repairer is None:
                return WebDocumentResult(
                    url=url,
                    final_url=response.final_url,
                    status="preserved_damaged",
                    object_id=original_acquisition.object_id,
                    acquisition_id=original_acquisition.acquisition_id,
                    sha256=original_acquisition.sha256,
                    size_bytes=original_acquisition.size_bytes,
                    deduplicated=original_acquisition.deduplicated,
                    original_object_id=original_acquisition.object_id,
                    original_acquisition_id=(
                        original_acquisition.acquisition_id
                    ),
                    original_sha256=original_acquisition.sha256,
                    original_size_bytes=original_acquisition.size_bytes,
                    error=f"{type(parse_error).__name__}: {parse_error}",
                )

            try:
                repaired_data = repairer(response.data)
                repaired_content = extract_pdf_content(repaired_data)
            except Exception as repair_error:
                return WebDocumentResult(
                    url=url,
                    final_url=response.final_url,
                    status="preserved_damaged",
                    object_id=original_acquisition.object_id,
                    acquisition_id=original_acquisition.acquisition_id,
                    sha256=original_acquisition.sha256,
                    size_bytes=original_acquisition.size_bytes,
                    deduplicated=original_acquisition.deduplicated,
                    original_object_id=original_acquisition.object_id,
                    original_acquisition_id=(
                        original_acquisition.acquisition_id
                    ),
                    original_sha256=original_acquisition.sha256,
                    original_size_bytes=original_acquisition.size_bytes,
                    repair_tool="qpdf",
                    error=(
                        f"Original parse failed: "
                        f"{type(parse_error).__name__}: {parse_error}; "
                        f"repair failed: "
                        f"{type(repair_error).__name__}: {repair_error}"
                    ),
                )

            repaired_filename = (
                f"{PurePosixPath(filename).stem}.repaired.pdf"
                if filename
                else "repaired-document.pdf"
            )

            repaired_metadata = {
                **metadata,
                "evidence_role": "repaired_derivative",
                "derivation_method": "qpdf",
                "derived_from_object_id": original_acquisition.object_id,
                "derived_from_acquisition_id": (
                    original_acquisition.acquisition_id
                ),
                "derived_from_sha256": original_acquisition.sha256,
                "original_parse_error": (
                    f"{type(parse_error).__name__}: {parse_error}"
                ),
            }

            repaired_source = Source(
                source_type="derived_pdf",
                locator=(
                    f"warrigal:pdf-repair:"
                    f"{original_acquisition.acquisition_id}"
                ),
                final_locator=response.final_url,
                title=repaired_filename,
                metadata=repaired_metadata,
            )
            repository.save_source(repaired_source)

            repaired_acquisition = service.acquire_bytes(
                data=repaired_data,
                source_id=repaired_source.source_id,
                job_id=job_id,
                node_id=node_id,
                batch_id=batch_id,
                method="pdf_repair_qpdf",
                mime_type="application/pdf",
                original_filename=repaired_filename,
                collection_id=collection_id,
                http_status=response.status,
                metadata=repaired_metadata,
            )

            passage_count = 0
            if not repository.object_has_passages(
                repaired_acquisition.object_id
            ):
                passage_count = _save_passages(
                    repaired_content,
                    source_url=response.final_url,
                    source_title=(
                        repaired_content.title
                        or repaired_filename
                        or response.final_url
                    ),
                    object_id=repaired_acquisition.object_id,
                    acquisition_id=repaired_acquisition.acquisition_id,
                    repository=repository,
                )

            return WebDocumentResult(
                url=url,
                final_url=response.final_url,
                status="repaired",
                object_id=repaired_acquisition.object_id,
                acquisition_id=repaired_acquisition.acquisition_id,
                sha256=repaired_acquisition.sha256,
                size_bytes=repaired_acquisition.size_bytes,
                passage_count=passage_count,
                deduplicated=repaired_acquisition.deduplicated,
                original_object_id=original_acquisition.object_id,
                original_acquisition_id=original_acquisition.acquisition_id,
                original_sha256=original_acquisition.sha256,
                original_size_bytes=original_acquisition.size_bytes,
                repair_tool="qpdf",
                error=f"{type(parse_error).__name__}: {parse_error}",
            )

        if not content.text.strip():
            return WebDocumentResult(
                url=url,
                final_url=response.final_url,
                status="no_text",
                object_id=original_acquisition.object_id,
                acquisition_id=original_acquisition.acquisition_id,
                sha256=original_acquisition.sha256,
                size_bytes=original_acquisition.size_bytes,
                deduplicated=original_acquisition.deduplicated,
            )

        passage_count = _save_passages(
            content,
            source_url=response.final_url,
            source_title=content.title or filename or response.final_url,
            object_id=original_acquisition.object_id,
            acquisition_id=original_acquisition.acquisition_id,
            repository=repository,
        )

        return WebDocumentResult(
            url=url,
            final_url=response.final_url,
            status="ingested",
            object_id=original_acquisition.object_id,
            acquisition_id=original_acquisition.acquisition_id,
            sha256=original_acquisition.sha256,
            size_bytes=original_acquisition.size_bytes,
            passage_count=passage_count,
            deduplicated=original_acquisition.deduplicated,
        )

    except Exception as exc:
        final_url = response.final_url if response is not None else url

        return WebDocumentResult(
            url=url,
            final_url=final_url,
            status="failed",
            object_id=(
                original_acquisition.object_id
                if original_acquisition is not None
                else None
            ),
            acquisition_id=(
                original_acquisition.acquisition_id
                if original_acquisition is not None
                else None
            ),
            sha256=(
                original_acquisition.sha256
                if original_acquisition is not None
                else None
            ),
            size_bytes=(
                original_acquisition.size_bytes
                if original_acquisition is not None
                else 0
            ),
            error=f"{type(exc).__name__}: {exc}",
        )
