import json
import tempfile
import unittest
from pathlib import Path

from warrigal.name_calculator import (
    calculate_fingerprint,
    digital_root_9,
    node18_root,
    save_fingerprint,
)


class NameCalculatorTests(unittest.TestCase):
    def test_double9_preserves_eighteen(self):
        self.assertEqual(node18_root(18), 18)
        self.assertEqual(node18_root(36), 18)
        self.assertEqual(node18_root(19), 1)

    def test_liam_custom_mapping(self):
        result = calculate_fingerprint("LIAM", created_at="2026-01-01T00:00:00+00:00")
        self.assertEqual(result.mapped_sequence, [30, 9, 1, 40])
        self.assertEqual(result.total, 80)
        self.assertEqual(result.total_root_18, 8)
        self.assertEqual(result.total_root_9, 8)

    def test_phrase_preserves_word_boundaries(self):
        result = calculate_fingerprint("Liam James McIlmurray")
        self.assertEqual([word.word for word in result.words], ["LIAM", "JAMES", "MCILMURRAY"])
        self.assertEqual(result.word_roots_18, [8, 12, 7])
        self.assertEqual(result.total, 1539)
        self.assertEqual(result.total_root_18, 9)

    def test_save_is_deterministic_and_valid_json(self):
        result = calculate_fingerprint("LIAM", source_reference="Example 1")
        with tempfile.TemporaryDirectory() as directory:
            first = save_fingerprint(result, Path(directory))
            second = save_fingerprint(result, Path(directory))
            self.assertEqual(first, second)
            payload = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(payload["fingerprint_id"], result.fingerprint_id)
            self.assertEqual(len(list(Path(directory).glob("*.json"))), 1)

    def test_source_attachment_provenance_is_recorded(self):
        result = calculate_fingerprint(
            "Fallen Name",
            source_attachment_path="sources/abc.jpg",
            source_attachment_sha256="abc",
        )
        self.assertEqual(result.source_attachment_sha256, "abc")


if __name__ == "__main__":
    unittest.main()
