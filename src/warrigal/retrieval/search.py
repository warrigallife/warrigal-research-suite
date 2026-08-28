from __future__ import annotations

from dataclasses import dataclass

from warrigal.retrieval.passages import Passage


@dataclass
class SearchResult:
    """A passage ranked for relevance to a query."""

    passage: Passage
    score: float

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
        matching_terms = query_terms & passage_terms

        score = float(len(matching_terms))

        if score > 0:
            results.append(
                SearchResult(
                    passage=passage,
                    score=score,
                )
            )

    results.sort(
        key=lambda result: result.score,
        reverse=True,
    )

    return results