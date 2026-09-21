"""Structured scripture/text corpus import for the Warrigal Name Calculator."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from warrigal.name_calculator import calculate_fingerprint, default_records_root, save_fingerprint


@dataclass(frozen=True)
class TextUnit:
    book: str
    chapter: str
    verse: str
    original_text: str
    translation_text: str
    source_title: str = ""
    source_reference: str = ""
    item_type: str = "verse"
    item_id: str = ""
    label: str = ""
    source_attachment_path: str = ""
    source_attachment_sha256: str = ""

    @property
    def reference(self) -> str:
        parts = [part for part in (self.book, self.chapter) if part]
        base = " ".join(parts)
        if self.verse:
            return f"{base}:{self.verse}" if base else self.verse
        return base or self.label or self.item_id or self.source_reference


REFERENCE_LINE = re.compile(
    r"^\s*(?:(?P<book>(?:[1-3]\s*)?[A-Za-z][A-Za-z .'-]*?)\s+)?"
    r"(?P<chapter>\d+)\s*:\s*(?P<verse>\d+[A-Za-z]?)\s+"
    r"(?P<text>.+?)\s*$"
)
VERSE_LINE = re.compile(r"^\s*(?:v(?:erse)?\.?\s*)?(?P<verse>\d+[A-Za-z]?)[.)]?\s+(?P<text>.+?)\s*$", re.I)


def parse_labelled_text(
    text: str,
    *,
    default_book: str = "",
    default_chapter: str = "",
    source_title: str = "",
    source_reference: str = "",
    original_language: bool = False,
) -> list[TextUnit]:
    """Parse one labelled verse per line without guessing unlabelled boundaries."""
    units: list[TextUnit] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        match = REFERENCE_LINE.match(line)
        if match:
            book = (match.group("book") or default_book).strip()
            chapter = match.group("chapter")
            verse = match.group("verse")
            body = match.group("text").strip()
        else:
            match = VERSE_LINE.match(line)
            if not match or not default_chapter:
                raise ValueError(
                    f"Line {line_number} has no recognised verse label. "
                    "Use ‘Book 1:1 text’, ‘1:1 text’, or enter a default chapter and use ‘1 text’."
                )
            book = default_book.strip()
            chapter = default_chapter.strip()
            verse = match.group("verse")
            body = match.group("text").strip()
        units.append(TextUnit(
            book=book,
            chapter=chapter,
            verse=verse,
            original_text=body if original_language else "",
            translation_text="" if original_language else body,
            source_title=source_title.strip(),
            source_reference=source_reference.strip(),
        ))
    if not units:
        raise ValueError("No labelled verses were found.")
    return units


def _row_unit(row: dict, *, source_title: str, source_reference: str) -> TextUnit:
    return TextUnit(
        book=str(row.get("book", "")).strip(),
        chapter=str(row.get("chapter", "")).strip(),
        verse=str(row.get("verse", "")).strip(),
        original_text=str(row.get("original_text", row.get("original", ""))).strip(),
        translation_text=str(row.get("translation_text", row.get("translation", row.get("text", "")))).strip(),
        source_title=str(row.get("source_title", source_title)).strip(),
        source_reference=str(row.get("source_reference", source_reference)).strip(),
        item_type=str(row.get("item_type", "text_item")).strip() or "text_item",
        item_id=str(row.get("item_id", row.get("id", ""))).strip(),
        label=str(row.get("label", row.get("title", ""))).strip(),
        source_attachment_path=str(row.get("source_attachment_path", "")).strip(),
        source_attachment_sha256=str(row.get("source_attachment_sha256", "")).strip(),
    )


def load_text_units(path: Path, *, source_title: str = "", source_reference: str = "") -> list[TextUnit]:
    """Load TXT, CSV, JSON, or a text-based PDF into structured units."""
    path = path.expanduser().resolve()
    suffix = path.suffix.lower()
    title = source_title or path.stem
    reference = source_reference or str(path)
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            units = [_row_unit(row, source_title=title, source_reference=reference) for row in csv.DictReader(handle)]
    elif suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("verses", payload.get("units", [])) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("JSON must be a list, or contain a ‘verses’/‘units’ list.")
        units = [_row_unit(row, source_title=title, source_reference=reference) for row in rows if isinstance(row, dict)]
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF import needs pypdf installed in Warrigal’s virtual environment.") from exc
        pages = [page.extract_text() or "" for page in PdfReader(path).pages]
        units = parse_labelled_text("\n".join(pages), source_title=title, source_reference=reference)
    elif suffix in {".txt", ".md"}:
        units = parse_labelled_text(path.read_text(encoding="utf-8-sig"), source_title=title, source_reference=reference)
    else:
        raise ValueError("Supported files are TXT, Markdown, CSV, JSON and text-based PDF.")
    units = [unit for unit in units if unit.original_text or unit.translation_text]
    if not units:
        raise ValueError("The file contained no usable text units.")
    return units


def align_units(original: list[TextUnit], translation: list[TextUnit]) -> list[TextUnit]:
    """Align two corpora by book/chapter/verse and refuse ambiguous mismatches."""
    originals = {(u.book.casefold(), u.chapter, u.verse): u for u in original}
    translations = {(u.book.casefold(), u.chapter, u.verse): u for u in translation}
    keys = sorted(originals.keys() | translations.keys())
    aligned = []
    for key in keys:
        left = originals.get(key)
        right = translations.get(key)
        template = left or right
        assert template is not None
        aligned.append(TextUnit(
            book=template.book,
            chapter=template.chapter,
            verse=template.verse,
            original_text=left.original_text if left else "",
            translation_text=right.translation_text if right else "",
            source_title=right.source_title if right else left.source_title,
            source_reference=right.source_reference if right else left.source_reference,
            item_type=template.item_type,
            item_id=template.item_id,
            label=template.label,
            source_attachment_path=template.source_attachment_path,
            source_attachment_sha256=template.source_attachment_sha256,
        ))
    return aligned


def save_text_batch(units: list[TextUnit], *, mapping_profile: str, root: Path | None = None) -> Path:
    """Calculate and save every translatable unit plus a resumable batch manifest."""
    if not units:
        raise ValueError("No text units supplied.")
    records_root = root or default_records_root()
    records_root.mkdir(parents=True, exist_ok=True)
    batch_identity = json.dumps([asdict(unit) for unit in units], ensure_ascii=False, sort_keys=True)
    batch_id = "WRG-CORPUS-" + hashlib.sha256(batch_identity.encode("utf-8")).hexdigest()[:16].upper()
    saved = []
    skipped = []
    failed = []
    for unit in units:
        if not unit.translation_text:
            skipped.append({"reference": unit.reference, "reason": "No translation/mapped-language text"})
            continue
        try:
            fingerprint = calculate_fingerprint(
                unit.translation_text,
                mapping_profile=mapping_profile,
                original_text=unit.original_text,
                translation_text=unit.translation_text,
                source_title=unit.source_title,
                source_reference=unit.reference or unit.source_reference,
                source_attachment_path=unit.source_attachment_path,
                source_attachment_sha256=unit.source_attachment_sha256,
            )
            path = save_fingerprint(fingerprint, records_root)
            saved.append({"reference": unit.reference, "fingerprint_id": fingerprint.fingerprint_id, "record": str(path)})
        except Exception as exc:
            failed.append({"reference": unit.reference, "error": str(exc)})
    manifest = {
        "schema_version": "warrigal-text-corpus-v1",
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mapping_profile": mapping_profile,
        "unit_count": len(units),
        "saved_count": len(saved),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "saved": saved,
        "skipped": skipped,
        "failed": failed,
    }
    destination = records_root.parent / "batches" / f"{batch_id}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def preserve_source_file(path: Path, root: Path | None = None) -> tuple[Path, str]:
    """Preserve a photo/PDF/source once by SHA-256 and return its stable copy."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    source_root = root or (default_records_root().parent / "sources")
    source_root.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    destination = source_root / f"{digest}{suffix}"
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(path, temporary)
        temporary.replace(destination)
    metadata = source_root / f"{digest}.json"
    if not metadata.exists():
        metadata.write_text(json.dumps({
            "schema_version": "warrigal-name-source-v1",
            "sha256": digest,
            "stored_path": str(destination),
            "original_filename": path.name,
            "original_path": str(path),
            "preserved_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination, digest
