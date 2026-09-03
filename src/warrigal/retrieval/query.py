from __future__ import annotations

from dataclasses import dataclass


LOW_INFORMATION_TERMS = frozenset(
    {
        "a",
        "an",
        "are",
        "can",
        "did",
        "do",
        "does",
        "for",
        "is",
        "of",
        "the",
        "to",
        "what",
        "which",
        "who",
    }
)


WORD_FAMILIES = {
    "contain": frozenset(
        {
            "contain",
            "contains",
            "contained",
            "containing",
        }
    ),
    "study": frozenset(
        {
            "study",
            "studies",
            "studied",
            "studying",
        }
    ),
    "produce": frozenset(
        {
            "produce",
            "produces",
            "produced",
            "producing",
        }
    ),
}


FORM_TO_CANONICAL = {
    form: canonical
    for canonical, forms in WORD_FAMILIES.items()
    for form in forms
}


@dataclass(frozen=True)
class QueryAnalysis:
    """A deconstructed research query."""

    original_query: str
    all_terms: tuple[str, ...]
    retrieval_terms: tuple[str, ...]
    filtered_terms: tuple[str, ...]


def _normalize_term(word: str) -> str:
    """Normalize one query word without changing query meaning."""

    return word.strip(".,!?;:()[]{}\"'").lower()


def canonical_word(term: str) -> str:
    """Return the canonical form of a known word, otherwise preserve it."""

    return FORM_TO_CANONICAL.get(term, term)


def word_family(term: str) -> frozenset[str]:
    """Return a known word family, otherwise preserve the term."""

    canonical = canonical_word(term)
    return WORD_FAMILIES.get(canonical, frozenset({term}))


def analyze_query(query: str) -> QueryAnalysis:
    """Separate retrieval terms from low-information query terms."""

    all_terms = tuple(
        term
        for word in query.split()
        if (term := _normalize_term(word))
    )

    retrieval_terms = tuple(
        term
        for term in all_terms
        if term not in LOW_INFORMATION_TERMS
    )

    filtered_terms = tuple(
        term
        for term in all_terms
        if term in LOW_INFORMATION_TERMS
    )

    return QueryAnalysis(
        original_query=query,
        all_terms=all_terms,
        retrieval_terms=retrieval_terms,
        filtered_terms=filtered_terms,
    )
