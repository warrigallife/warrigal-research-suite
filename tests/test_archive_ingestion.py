from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from warrigal.acquisition.archive import discover_pdf_files


class ArchiveIngestionTests(unittest.TestCase):
    def test_discover_pdf_files_recursively_finds_only_pdfs(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            nested = root / "COLLECTIONS" / "TEST" / "ORIGINALS"
            nested.mkdir(parents=True)

            (root / "root.pdf").write_bytes(b"root")
            (nested / "nested.PDF").write_bytes(b"nested")
            (nested / "notes.txt").write_text("ignore me", encoding="utf-8")
            (nested / "image.jpg").write_bytes(b"ignore me")

            discovered = discover_pdf_files(root)

            self.assertEqual(
                discovered,
                sorted(
                    [
                        (root / "root.pdf").resolve(),
                        (nested / "nested.PDF").resolve(),
                    ],
                    key=lambda path: str(path).casefold(),
                ),
            )

    def test_discover_pdf_files_rejects_missing_directory(self):
        with TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "missing"

            with self.assertRaises(NotADirectoryError):
                discover_pdf_files(missing)


if __name__ == "__main__":
    unittest.main()
