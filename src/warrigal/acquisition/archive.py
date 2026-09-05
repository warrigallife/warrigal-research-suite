from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from warrigal.acquisition.content import extract_pdf_content
from warrigal.acquisition.service import AcquisitionService
from warrigal.models import Passage as PassageRecord
from warrigal.models import Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.retrieval.passages import split_into_passages


@dataclass(frozen=True)
class ArchiveFileResult:
    """Outcome for one PDF encountered during archive ingestion."""

    path: Path
    status: str
    object_id: str | None = None
    acquisition_id: str | None = None
    sha256: str | None = None
    passage_count: int = 0
    deduplicated: bool = False
    error: str | None = None


@dataclass(frozen=True)
class ArchiveIngestionResult:
    """Summary of one recursive archive ingestion run."""

    root: Path
    files: tuple[ArchiveFileResult, ...]

    @property
    def discovered_count(self) -> int:
        return len(self.files)

    @property
    def ingested_count(self) -> int:
        return sum(result.status == "ingested" for result in self.files)

    @property
    def duplicate_count(self) -> int:
        return sum(result.status == "duplicate" for result in self.files)

    @property
    def no_text_count(self) -> int:
        return sum(result.status == "no_text" for result in self.files)

    @property
    def failed_count(self) -> int:
        return sum(result.status == "failed" for result in self.files)

    @property
    def passage_count(self) -> int:
        return sum(result.passage_count for result in self.files)


def discover_pdf_files(root: Path) -> list[Path]:
    """Return PDFs beneath root in deterministic path order."""

    root = root.expanduser().resolve()

    if not root.is_dir():
        raise NotADirectoryError(f"Archive directory not found: {root}")

    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda path: str(path).casefold(),
    )


def ingest_pdf_archive(
    root: Path,
    *,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
) -> ArchiveIngestionResult:
    """Recursively ingest PDFs while preserving provenance and deduplication."""

    root = root.expanduser().resolve()
    pdf_files = discover_pdf_files(root)

    service = AcquisitionService(
        repository=repository,
        object_store=object_store,
    )

    results: list[ArchiveFileResult] = []

    for pdf_path in pdf_files:
        try:
            data = pdf_path.read_bytes()

            source = Source(
                source_type="file",
                locator=str(pdf_path),
                final_locator=str(pdf_path),
                title=pdf_path.name,
                metadata={
                    "content_type": "application/pdf",
                    "filename": pdf_path.name,
                    "archive_root": str(root),
                    "relative_path": str(pdf_path.relative_to(root)),
                },
            )
            repository.save_source(source)

            acquisition = service.acquire_bytes(
                data=data,
                source_id=source.source_id,
                job_id=job_id,
                node_id=node_id,
                batch_id=batch_id,
                method="archive_pdf",
                mime_type="application/pdf",
                original_filename=pdf_path.name,
                collection_id=collection_id,
                metadata={
                    "path": str(pdf_path),
                    "archive_root": str(root),
                    "relative_path": str(pdf_path.relative_to(root)),
                },
            )

            if repository.object_has_passages(acquisition.object_id):
                results.append(
                    ArchiveFileResult(
                        path=pdf_path,
                        status="duplicate",
                        object_id=acquisition.object_id,
                        acquisition_id=acquisition.acquisition_id,
                        sha256=acquisition.sha256,
                        deduplicated=True,
                    )
                )
                continue

            content = extract_pdf_content(data)

            if not content.text.strip():
                results.append(
                    ArchiveFileResult(
                        path=pdf_path,
                        status="no_text",
                        object_id=acquisition.object_id,
                        acquisition_id=acquisition.acquisition_id,
                        sha256=acquisition.sha256,
                        deduplicated=acquisition.deduplicated,
                    )
                )
                continue

            passages = split_into_passages(
                content.text,
                source_url=str(pdf_path),
                source_title=content.title or pdf_path.name,
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

            results.append(
                ArchiveFileResult(
                    path=pdf_path,
                    status="ingested",
                    object_id=acquisition.object_id,
                    acquisition_id=acquisition.acquisition_id,
                    sha256=acquisition.sha256,
                    passage_count=len(passages),
                    deduplicated=acquisition.deduplicated,
                )
            )

        except Exception as exc:
            results.append(
                ArchiveFileResult(
                    path=pdf_path,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    return ArchiveIngestionResult(
        root=root,
        files=tuple(results),
    )
