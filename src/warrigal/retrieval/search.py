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
    term_span: int | None
    title_matched_terms: tuple[str, ...]
    title_query_coverage: float

def _terms(text: str) -> set[str]:
    """Normalize text into searchable terms."""

    return {
        word.strip(".,!?;:()[]{}\"'").lower()
        for word in text.split()
        if word.strip(".,!?;:()[]{}\"'")
    }

def _term_span(
    text: str,
    matched_terms: tuple[str, ...],
) -> int | None:
    """Measure the smallest word span containing the matched query terms."""

    if len(matched_terms) < 2:
        return None

    words = [
        word.strip(".,!?;:()[]{}\"'").lower()
        for word in text.split()
    ]

    required_terms = set(matched_terms)
    best_span: int | None = None

    for start in range(len(words)):
        if words[start] not in required_terms:
            continue

        found_terms: set[str] = set()

        for end in range(start, len(words)):
            if words[end] in required_terms:
                found_terms.add(words[end])

            if found_terms == required_terms:
                span = end - start + 1

                if best_span is None or span < best_span:
                    best_span = span

                break

    return best_span

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

        term_span = _term_span(
            passage.text,
            matching_terms,
        )

        title_terms = _terms(passage.source_title or "")
        title_matched_terms = tuple(sorted(query_terms & title_terms))

        title_query_coverage = (
            len(title_matched_terms) / len(query_terms)
            if query_terms
            else 0.0
        )

        if score > 0 or title_query_coverage > 0:
            results.append(
                SearchResult(
                    passage=passage,
                    score=score,
                    matched_terms=matching_terms,
                    query_coverage=query_coverage,
                    term_span=term_span,
                    title_matched_terms=title_matched_terms,
                    title_query_coverage=title_query_coverage,
                )
            )

    results.sort(
        key=lambda result: result.score,
        reverse=True,
    )

    return results