from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class Passage:
    """A searchable passage extracted from readable content."""

    index: int
    text: str
    source_url: str | None = None
    source_title: str | None = None
    object_id: str | None = None
    acquisition_id: str | None = None

def split_into_passages(
    text: str,
    max_words: int = 120,
    source_url: str | None = None,
    source_title: str | None = None,
    object_id: str | None = None,
    acquisition_id: str | None = None,
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
                source_url=source_url,
                source_title=source_title,
                object_id=object_id,
                acquisition_id=acquisition_id,
            )
        )

    return passages


def passages_from_rows(
    rows: list[sqlite3.Row],
) -> list[Passage]:
    """Convert persistent passage rows into searchable passages."""

    return [
        Passage(
            index=row["passage_index"],
            text=row["text"],
            source_url=row["source_url"],
            source_title=row["source_title"],
            object_id=row["object_id"],
            acquisition_id=row["acquisition_id"],
        )
        for row in rows
    ]