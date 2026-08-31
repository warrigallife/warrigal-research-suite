from __future__ import annotations

from dataclasses import dataclass

from warrigal.retrieval.passages import Passage


@dataclass
class SearchResult:
    """A passage ranked for relevance to a query."""

    passage: Passage
    score: float
    matched_terms: tuple[str, ...]
    query_coverage: float

def _terms(text: str) -> set[str]:
    """Normalize text into searchable terms."""

    return {
        word.strip(".,!?;:()[]{}\"'").lower()
        for word in text.split()
        if word.strip(".,!?;:()[]{}\"'")
    }

def search_passages(
    query: str,
    passages: list[Passage],
) -> list[SearchResult]:
    """Rank passages by their relevance to a query."""

    query_terms = _terms(query)
    results: list[SearchResult] = []

    for passage in passages:
        passage_terms = _terms(passage.text)
        matching_terms = tuple(sorted(query_terms & passage_terms))

        query_coverage = (
            len(matching_terms) / len(query_terms)
            if query_terms
            else 0.0
        )

        score = float(len(matching_terms))

        if score > 0:
            results.append(
                SearchResult(
                    passage=passage,
                    score=score,
                    matched_terms=matching_terms,
                    query_coverage=query_coverage,
                )
            )

    results.sort(
        key=lambda result: result.score,
        reverse=True,
    )

    return results