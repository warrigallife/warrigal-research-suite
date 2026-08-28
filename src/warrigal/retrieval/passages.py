from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Passage:
    """A searchable passage extracted from readable content."""

    index: int
    text: str

def split_into_passages(
    text: str,
    max_words: int = 120,
) -> list[Passage]:
    """Split readable text into searchable passages."""

    words = text.split()

    passages: list[Passage] = []

    for start in range(0, len(words), max_words):
        passage_words = words[start : start + max_words]
        passage_text = " ".join(passage_words)

        passages.append(
            Passage(
                index=len(passages),
                text=passage_text,
            )
        )

    return passages