"""Versioned text-to-number calculations for Warrigal/JUFE research.

The language mapping layer is deliberately separate from JUFE interpretation.
Only mappings declared in ``MAPPING_PROFILES`` are executable.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "warrigal-name-fingerprint-v1"
ALGORITHM_VERSION = "english-custom-double9-v1"

ENGLISH_CUSTOM_VALUES = {
    **{chr(64 + value): value for value in range(1, 11)},
    **{
        "K": 20, "L": 30, "M": 40, "N": 50, "O": 60,
        "P": 70, "Q": 80, "R": 90, "S": 100, "T": 200,
        "U": 300, "V": 400, "W": 500, "X": 600, "Y": 700,
        "Z": 800,
    },
}

MAPPING_PROFILES = {
    "English — Warrigal custom scale": {
        "profile_id": "english-warrigal-custom-v1",
        "language": "English",
        "status": "IMPLEMENTED",
        "values": ENGLISH_CUSTOM_VALUES,
    },
}


def node18_root(value: int) -> int:
    """Return a Double-9 node, preserving 18 rather than reducing it to 9."""
    value = abs(int(value))
    if value == 0:
        return 0
    remainder = value % 18
    return 18 if remainder == 0 else remainder


def digital_root_9(value: int) -> int:
    value = abs(int(value))
    return 0 if value == 0 else 1 + ((value - 1) % 9)


def double9_layer(node: int) -> str:
    if 1 <= node <= 9:
        return "Lower Nine"
    if 10 <= node <= 18:
        return "Upper Nine"
    return "Zero"


def normalize_english(text: str) -> str:
    """Normalise case while retaining word boundaries and recorded raw input."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_text.upper()).strip()


@dataclass(frozen=True)
class WordResult:
    word: str
    symbols: list[str]
    ordinal_values: list[int]
    mapped_values: list[int]
    total: int
    node18_root: int
    digital_root_9: int
    layer: str


@dataclass(frozen=True)
class Fingerprint:
    schema_version: str
    algorithm_version: str
    fingerprint_id: str
    created_at: str
    raw_input: str
    original_text: str
    translation_text: str
    source_title: str
    source_reference: str
    source_attachment_path: str
    source_attachment_sha256: str
    notes: str
    mapping_profile: str
    mapping_profile_id: str
    mapping_status: str
    language: str
    normalized_text: str
    words: list[WordResult]
    mapped_sequence: list[int]
    word_totals: list[int]
    word_roots_18: list[int]
    total: int
    total_root_18: int
    total_root_9: int
    double9_layer: str
    frequency_candidates_hz: list[int]
    frequency_mapping_status: str
    jufe_runtime_status: str

    def to_dict(self) -> dict:
        return asdict(self)


def _symbols(text: str, values: dict[str, int]) -> Iterable[tuple[str, list[str]]]:
    for token in text.split():
        symbols = [symbol for symbol in token if symbol in values]
        if symbols:
            yield token, symbols


def calculate_fingerprint(
    text: str,
    *,
    mapping_profile: str = "English — Warrigal custom scale",
    original_text: str = "",
    translation_text: str = "",
    source_title: str = "",
    source_reference: str = "",
    source_attachment_path: str = "",
    source_attachment_sha256: str = "",
    notes: str = "",
    created_at: str | None = None,
) -> Fingerprint:
    """Calculate a reproducible fingerprint without claiming a JUFE runtime map."""
    raw_input = text.strip()
    if not raw_input:
        raise ValueError("Enter a name, word, verse or passage.")
    try:
        profile = MAPPING_PROFILES[mapping_profile]
    except KeyError as exc:
        raise ValueError(f"Mapping profile is not implemented: {mapping_profile}") from exc

    values = profile["values"]
    normalized = normalize_english(raw_input)
    words: list[WordResult] = []
    sequence: list[int] = []

    for token, symbols in _symbols(normalized, values):
        ordinal = [ord(symbol) - ord("A") + 1 for symbol in symbols]
        mapped = [values[symbol] for symbol in symbols]
        total = sum(mapped)
        root18 = node18_root(total)
        words.append(WordResult(
            word=token,
            symbols=symbols,
            ordinal_values=ordinal,
            mapped_values=mapped,
            total=total,
            node18_root=root18,
            digital_root_9=digital_root_9(total),
            layer=double9_layer(root18),
        ))
        sequence.extend(mapped)

    if not words:
        raise ValueError("The selected mapping found no supported symbols in the input.")

    total = sum(sequence)
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    identity_payload = {
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "mapping_profile_id": profile["profile_id"],
        "raw_input": raw_input,
        "original_text": original_text,
        "translation_text": translation_text,
        "source_title": source_title,
        "source_reference": source_reference,
        "source_attachment_path": source_attachment_path,
        "source_attachment_sha256": source_attachment_sha256,
    }
    digest = hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    return Fingerprint(
        schema_version=SCHEMA_VERSION,
        algorithm_version=ALGORITHM_VERSION,
        fingerprint_id=f"WRG-NAME-{digest.upper()}",
        created_at=timestamp,
        raw_input=raw_input,
        original_text=original_text.strip(),
        translation_text=translation_text.strip(),
        source_title=source_title.strip(),
        source_reference=source_reference.strip(),
        source_attachment_path=source_attachment_path.strip(),
        source_attachment_sha256=source_attachment_sha256.strip(),
        notes=notes.strip(),
        mapping_profile=mapping_profile,
        mapping_profile_id=profile["profile_id"],
        mapping_status=profile["status"],
        language=profile["language"],
        normalized_text=normalized,
        words=words,
        mapped_sequence=sequence,
        word_totals=[word.total for word in words],
        word_roots_18=[word.node18_root for word in words],
        total=total,
        total_root_18=node18_root(total),
        total_root_9=digital_root_9(total),
        double9_layer=double9_layer(node18_root(total)),
        frequency_candidates_hz=sequence,
        frequency_mapping_status=(
            "PROVISIONAL: mapped values are exposed as direct Hz candidates; "
            "no additional Tom/JUFE frequency transform has been asserted."
        ),
        jufe_runtime_status=(
            "RESEARCH EXPORT ONLY: the authoritative JUFE 64-cell input mapping "
            "remains unresolved and is not guessed here."
        ),
    )


def default_records_root() -> Path:
    return (
        Path.home()
        / "Desktop"
        / "INFORMATION_ARCHIVE"
        / "COLLECTIONS"
        / "JUFE"
        / "NAME_CALCULATOR"
        / "records"
    )


def save_fingerprint(fingerprint: Fingerprint, root: Path | None = None) -> Path:
    """Save one deterministic record; identical source inputs reuse one filename."""
    target_root = root or default_records_root()
    target_root.mkdir(parents=True, exist_ok=True)
    destination = target_root / f"{fingerprint.fingerprint_id}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(fingerprint.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
