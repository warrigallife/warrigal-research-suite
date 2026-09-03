from __future__ import annotations

from dataclasses import dataclass

from warrigal.retrieval.passages import Passage
from warrigal.retrieval.query import analyze_query, canonical_word


@dataclass
class SearchResult:
    """A passage ranked for relevance to a query."""

    passage: Passage
    score: float
    matched_terms: tuple[str, ...]
    exact_matched_terms: tuple[str, ...]
    family_matched_terms: tuple[str, ...]
    query_term_frequency: tuple[tuple[str, int], ...]
    query_coverage: float
    term_span: int | None
    title_matched_terms: tuple[str, ...]
    title_exact_matched_terms: tuple[str, ...]
    title_family_matched_terms: tuple[str, ...]
    title_query_coverage: float

def _terms(text: str) -> set[str]:
    """Normalize text into searchable terms."""

    return {
        word.strip(".,!?;:()[]{}\"'").lower()
        for word in text.split()
        if word.strip(".,!?;:()[]{}\"'")
    }


def _match_query_terms(
    query_terms: set[str],
    document_terms: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Separate exact matches from conservative word-family matches."""

    exact_matched_terms = query_terms & document_terms

    document_canonical_terms = {
        canonical_word(term)
        for term in document_terms
    }

    matched_terms = {
        term
        for term in query_terms
        if canonical_word(term) in document_canonical_terms
    }

    family_matched_terms = matched_terms - exact_matched_terms

    return (
        tuple(sorted(matched_terms)),
        tuple(sorted(exact_matched_terms)),
        tuple(sorted(family_matched_terms)),
    )

def _query_term_frequency(
    text: str,
    matched_terms: tuple[str, ...],
) -> tuple[tuple[str, int], ...]:
    """Count occurrences of matched query terms, including known word-family forms."""

    words = [
        canonical_word(word.strip(".,!?;:()[]{}\"'").lower())
        for word in text.split()
        if word.strip(".,!?;:()[]{}\"'")
    ]

    frequencies = []

    for term in matched_terms:
        canonical = canonical_word(term)
        count = sum(
            1
            for word in words
            if word == canonical
        )
        frequencies.append((term, count))

    return tuple(frequencies)


def _term_span(
    text: str,
    matched_terms: tuple[str, ...],
) -> int | None:
    """Measure the smallest word span containing the matched query terms."""

    if len(matched_terms) < 2:
        return None

    words = [
        canonical_word(word.strip(".,!?;:()[]{}\"'").lower())
        for word in text.split()
    ]

    required_terms = {
        canonical_word(term)
        for term in matched_terms
    }
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
    min_query_coverage: float = 0.0,
) -> list[SearchResult]:
    """Rank passages by their relevance to a query."""

    if not 0.0 <= min_query_coverage <= 1.0:
        raise ValueError(
            "min_query_coverage must be between 0.0 and 1.0"
        )

    query_analysis = analyze_query(query)
    query_terms = set(query_analysis.retrieval_terms)
    results: list[SearchResult] = []

    for passage in passages:
        passage_terms = _terms(passage.text)
        (
            matching_terms,
            exact_matched_terms,
            family_matched_terms,
        ) = _match_query_terms(query_terms, passage_terms)

        query_coverage = (
            len(matching_terms) / len(query_terms)
            if query_terms
            else 0.0
        )

        if query_coverage < min_query_coverage:
            continue

        score = float(len(matching_terms))

        query_term_frequency = _query_term_frequency(
            passage.text,
            matching_terms,
        )

        term_span = _term_span(
            passage.text,
            matching_terms,
        )

        title_terms = _terms(passage.source_title or "")
        (
            title_matched_terms,
            title_exact_matched_terms,
            title_family_matched_terms,
        ) = _match_query_terms(query_terms, title_terms)

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
                    exact_matched_terms=exact_matched_terms,
                    family_matched_terms=family_matched_terms,
                    query_term_frequency=query_term_frequency,
                    query_coverage=query_coverage,
                    term_span=term_span,
                    title_matched_terms=title_matched_terms,
                    title_exact_matched_terms=title_exact_matched_terms,
                    title_family_matched_terms=title_family_matched_terms,
                    title_query_coverage=title_query_coverage,
                )
            )

    def ranking_key(
        result: SearchResult,
    ) -> tuple[float, int, float, int, int]:
        """Build an explainable deterministic relevance ranking key."""

        exact_match_count = len(result.exact_matched_terms)

        proximity = (
            -result.term_span
            if result.term_span is not None
            else 0
        )

        total_term_frequency = sum(
            count
            for _, count in result.query_term_frequency
        )

        return (
            result.query_coverage,
            exact_match_count,
            result.title_query_coverage,
            proximity,
            total_term_frequency,
        )

    results.sort(
        key=ranking_key,
        reverse=True,
    )

    return results
