from __future__ import annotations

from pathlib import Path


def discover_pdf_files(root: Path) -> list[Path]:
    """Return PDFs beneath root in deterministic path order."""

    root = root.expanduser().resolve()

    if not root.is_dir():
        raise NotADirectoryError(f"Archive directory not found: {root}")

    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda path: str(path).casefold(),
    )
