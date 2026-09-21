import json
import tempfile
import unittest
from pathlib import Path

from warrigal.scripture_import import align_units, load_text_units, parse_labelled_text, preserve_source_file, save_text_batch


class ScriptureImportTests(unittest.TestCase):
    def test_full_references_are_split(self):
        units = parse_labelled_text("John 1:1 In the beginning\nJohn 1:2 He was in the beginning")
        self.assertEqual([(u.book, u.chapter, u.verse) for u in units], [("John", "1", "1"), ("John", "1", "2")])

    def test_default_book_and_chapter(self):
        units = parse_labelled_text("1 In the beginning\n2 He was in the beginning", default_book="John", default_chapter="1")
        self.assertEqual([u.reference for u in units], ["John 1:1", "John 1:2"])

    def test_json_corpus_and_batch_are_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "john.json"
            source.write_text(json.dumps({"verses": [{"book": "John", "chapter": 1, "verse": 1, "text": "In the beginning"}]}), encoding="utf-8")
            units = load_text_units(source)
            first = save_text_batch(units, mapping_profile="English — Warrigal custom scale", root=root / "records")
            second = save_text_batch(units, mapping_profile="English — Warrigal custom scale", root=root / "records")
            self.assertEqual(first, second)
            payload = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(payload["saved_count"], 1)
            self.assertEqual(len(list((root / "records").glob("*.json"))), 1)

    def test_original_and_translation_align_by_reference(self):
        original = parse_labelled_text("John 1:1 Ἐν ἀρχῇ", original_language=True)
        translation = parse_labelled_text("John 1:1 In the beginning")
        aligned = align_units(original, translation)
        self.assertEqual(aligned[0].original_text, "Ἐν ἀρχῇ")
        self.assertEqual(aligned[0].translation_text, "In the beginning")

    def test_source_file_is_deduplicated_by_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photo.txt"
            source.write_text("inscription", encoding="utf-8")
            first, digest1 = preserve_source_file(source, root / "sources")
            second, digest2 = preserve_source_file(source, root / "sources")
            self.assertEqual(first, second)
            self.assertEqual(digest1, digest2)
            self.assertEqual(len(list((root / "sources").glob("*.txt"))), 1)


if __name__ == "__main__":
    unittest.main()
