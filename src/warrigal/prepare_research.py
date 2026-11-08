"""Prepare a local, provenance-carrying evidence packet for a research question.

Retrieves and ranks already-archived WRS passages for a query using the
existing deterministic `search_passages` function -- the same backend used by
`warrigal.cli search` and the Archive Search source-panel action -- and writes
a compact Markdown packet to disk. No Claude or Ollama inference is used to
retrieve, rank, or compose the packet; a Claude session can read the written
file directly instead of repeating that retrieval work itself.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from warrigal.database import initialize_database
from warrigal.publish_instagram_collection import atomic_write_text, safe_name
from warrigal.repository import WarrigalRepository
from warrigal.retrieval.passages import passages_from_rows
from warrigal.retrieval.search import SearchResult, search_passages

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "reports" / "research-briefs"
)


def build_evidence_packet_markdown(
    query: str,
    results: list[SearchResult],
    repository: WarrigalRepository,
    generated_at: str,
) -> str:
    """Render ranked search results as a compact, provenance-carrying packet."""

    lines = [
        f"# Research brief: {query}",
        "",
        f"- Generated: {generated_at}",
        f"- Results: {len(results)}",
        "",
        "Prepared locally by `warrigal.prepare_research` using the existing "
        "deterministic `search_passages` ranking function. No Claude or "
        "Ollama inference was used to retrieve or rank this evidence.",
        "",
    ]

    if not results:
        lines.append("_No archived passages matched this query._")
        return "\n".join(lines) + "\n"

    for position, result in enumerate(results, start=1):
        passage = result.passage
        acquisition = repository.get_acquisition(passage.acquisition_id)
        method = acquisition["method"] if acquisition is not None else "unknown"

        lines.extend(
            [
                f"## {position}. {passage.source_title or 'Untitled source'}",
                "",
                f"- Score: {result.score}",
                f"- Query coverage: {result.query_coverage:.2f}",
                f"- Matched terms: {', '.join(result.matched_terms) or 'none'}",
                f"- Source URL: {passage.source_url or 'unknown'}",
                f"- Object ID: {passage.object_id}",
                f"- Acquisition ID: {passage.acquisition_id}",
                f"- Acquisition method: {method}",
                "",
                "> " + passage.text.replace("\n", "\n> "),
                "",
            ]
        )

    return "\n".join(lines) + "\n"


def prepare_research_packet(
    query: str,
    *,
    database: sqlite3.Connection,
    output_dir: Path,
    min_query_coverage: float = 0.0,
    max_results: int = 10,
) -> Path:
    """Retrieve, rank and write a local evidence packet for `query`.

    Reuses `WarrigalRepository.list_passages()` and the existing
    `search_passages()` ranking function -- the same already-tested,
    deterministic retrieval path `warrigal.cli search` uses -- so this
    introduces no new retrieval logic and no Claude/Ollama inference.
    """

    repository = WarrigalRepository(database)
    rows = repository.list_passages()
    passages = passages_from_rows(rows)
    results = search_passages(
        query,
        passages,
        min_query_coverage=min_query_coverage,
        max_results=max_results,
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    markdown = build_evidence_packet_markdown(query, results, repository, generated_at)

    slug = safe_name(query.lower(), fallback="research-brief")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"{slug}-{timestamp}.md"

    atomic_write_text(path, markdown)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a local, provenance-carrying evidence packet for a "
            "research question from already-archived WRS passages."
        )
    )
    parser.add_argument("query", help="Research question or search query.")
    parser.add_argument(
        "--min-query-coverage",
        type=float,
        default=0.0,
        help="Minimum fraction of query terms a passage must match (0.0-1.0).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum number of passages to include in the packet.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write the evidence packet into.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    database = initialize_database()
    try:
        path = prepare_research_packet(
            args.query,
            database=database,
            output_dir=args.output_dir,
            min_query_coverage=args.min_query_coverage,
            max_results=args.max_results,
        )
    finally:
        database.close()

    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
