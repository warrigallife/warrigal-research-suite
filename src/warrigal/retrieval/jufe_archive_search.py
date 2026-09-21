"""Evidence-preserving trigger search across Warrigal passages."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class JUFESearchHit:
    passage_id: str
    text: str
    source_url: str | None
    source_title: str | None
    author_id: str | None
    author: str | None
    source_type: str
    matched_triggers: tuple[str, ...]
    relevance_score: int
    review_status: str = "UNREVIEWED"


def load_triggers(path: str | Path) -> tuple[str, ...]:
    """Load unique, non-comment trigger phrases in source order."""

    triggers: list[str] = []
    seen: set[str] = set()
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        trigger = raw_line.strip()
        key = trigger.casefold()
        if not trigger or trigger.startswith("#") or key in seen:
            continue
        seen.add(key)
        triggers.append(trigger)
    if not triggers:
        raise ValueError("trigger file contains no searchable terms")
    return tuple(triggers)


def _metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row["metadata_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _contains(text: str, trigger: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(trigger) + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def search_jufe_archive(
    passages: Iterable[Mapping[str, Any]],
    triggers: Iterable[str],
    *,
    max_results: int,
) -> list[JUFESearchHit]:
    """Return ranked, bounded passage matches without changing the archive."""

    if max_results < 1:
        raise ValueError("max_results must be at least 1")
    trigger_list = tuple(triggers)
    hits: list[JUFESearchHit] = []
    for row in passages:
        text = str(row["text"])
        matches = tuple(t for t in trigger_list if _contains(text, t))
        if not matches:
            continue
        metadata = _metadata(row)
        # Phrase length rewards specific multi-word matches without pretending
        # this deterministic retrieval score is scientific confidence.
        score = sum(max(1, len(trigger.split())) for trigger in matches)
        hits.append(
            JUFESearchHit(
                passage_id=str(row["passage_id"]),
                text=text,
                source_url=row["source_url"],
                source_title=row["source_title"],
                author_id=(
                    str(metadata["author_id"])
                    if metadata.get("author_id") else None
                ),
                author=(
                    str(metadata.get("author") or metadata.get("author_handle"))
                    if metadata.get("author") or metadata.get("author_handle")
                    else None
                ),
                source_type=str(
                    metadata.get("source_type")
                    or metadata.get("context_role")
                    or "unspecified"
                ),
                matched_triggers=matches,
                relevance_score=score,
            )
        )
    hits.sort(
        key=lambda hit: (
            -hit.relevance_score,
            -len(hit.matched_triggers),
            hit.passage_id,
        )
    )
    return hits[:max_results]


def export_jufe_search(
    hits: Iterable[JUFESearchHit],
    *,
    output_path: str | Path,
    triggers: Iterable[str],
) -> tuple[Path, Path, int]:
    """Write human-readable Markdown and machine-readable JSON evidence."""

    records = list(hits)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    json_output = output.with_suffix(".json")
    trigger_list = list(triggers)
    payload = {
        "schema": "warrigal.jufe-trigger-search.v1",
        "review_status": "UNREVIEWED",
        "triggers": trigger_list,
        "result_count": len(records),
        "results": [hit.__dict__ for hit in records],
    }
    json_output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        "# JUFE Archive Trigger Search",
        "",
        "- Review status: `UNREVIEWED`",
        f"- Results: {len(records)}",
        f"- Triggers: {len(trigger_list)}",
        "- Scores rank deterministic term overlap; they are not proof or confidence.",
        "",
    ]
    for number, hit in enumerate(records, start=1):
        lines.extend([
            f"## Result {number}",
            "",
            f"- Passage ID: `{hit.passage_id}`",
            f"- Review status: `{hit.review_status}`",
            f"- Relevance score: {hit.relevance_score}",
            f"- Matched triggers: {', '.join(hit.matched_triggers)}",
            f"- Author: {hit.author or 'UNAVAILABLE'}",
            f"- Author ID: `{hit.author_id or 'UNAVAILABLE'}`",
            f"- Source type: `{hit.source_type}`",
            f"- Source title: {hit.source_title or 'UNAVAILABLE'}",
            f"- Source: {hit.source_url or 'UNAVAILABLE'}",
            "",
            hit.text,
            "",
        ])
    output.write_text("\n".join(lines), encoding="utf-8")
    return output, json_output, len(records)
