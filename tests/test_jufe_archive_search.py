import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from warrigal.retrieval.jufe_archive_search import (
    export_jufe_search,
    load_triggers,
    search_jufe_archive,
)


class JUFEArchiveSearchTests(unittest.TestCase):
    def test_search_is_ranked_bounded_and_source_preserving(self):
        rows = [
            {
                "passage_id": "P1", "text": "A toroidal tensegrity lattice.",
                "source_url": "https://example/1", "source_title": "One",
                "metadata_json": json.dumps({"author_id": "A1", "author": "@one"}),
            },
            {
                "passage_id": "P2", "text": "A lattice alone.",
                "source_url": "https://example/2", "source_title": "Two",
                "metadata_json": "{}",
            },
        ]
        hits = search_jufe_archive(
            rows, ["lattice", "toroidal", "tensegrity"], max_results=1
        )
        self.assertEqual([hit.passage_id for hit in hits], ["P1"])
        self.assertEqual(hits[0].author_id, "A1")
        self.assertEqual(hits[0].review_status, "UNREVIEWED")

    def test_trigger_loader_ignores_comments_and_duplicates(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "triggers.txt"
            path.write_text("# note\nTorus\n\ntorus\nphase lock\n")
            self.assertEqual(load_triggers(path), ("Torus", "phase lock"))

    def test_export_writes_markdown_and_json(self):
        rows = [{
            "passage_id": "P1", "text": "phase lock",
            "source_url": "https://example/1", "source_title": "One",
            "metadata_json": "{}",
        }]
        hits = search_jufe_archive(rows, ["phase lock"], max_results=10)
        with TemporaryDirectory() as tmp:
            md, data, count = export_jufe_search(
                hits, output_path=Path(tmp) / "results.md", triggers=["phase lock"]
            )
            self.assertEqual(count, 1)
            self.assertIn("UNREVIEWED", md.read_text())
            self.assertEqual(json.loads(data.read_text())["result_count"], 1)
