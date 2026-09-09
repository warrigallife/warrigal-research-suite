from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from warrigal.audio import TranscriptResult, TranscriptSegment
from warrigal.audio_cli import run_ingest_audio
from warrigal.cli import build_parser
from warrigal.database import initialize_database
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


class AudioCLITests(unittest.TestCase):
    def test_parser_accepts_audio_command(self):
        args = build_parser().parse_args([
            "ingest-audio", "song.flac", "--model", "model.bin"
        ])
        self.assertEqual(args.path, "song.flac")
        self.assertEqual(args.model, "model.bin")

    def test_archives_before_transcription(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "song.flac"
            source.write_bytes(b"original audio bytes")
            model = root / "model.bin"
            model.write_bytes(b"fake model")

            db = initialize_database(root / "test.db")
            try:
                repository = WarrigalRepository(db)
                store = ObjectStore(root / "objects")
                observed = []

                def fake_transcriber(source_path, *, model_path):
                    archived = Path(source_path)
                    observed.append(archived)
                    self.assertNotEqual(archived, source)
                    self.assertEqual(
                        archived.read_bytes(), b"original audio bytes"
                    )
                    return TranscriptResult(
                        source_path=archived,
                        segments=(
                            TranscriptSegment(0, 0, 1000, "Hello world"),
                        ),
                        raw_json=b'{"transcription":[]}',
                        model_path=Path(model_path),
                    )

                result = run_ingest_audio(
                    str(source),
                    model_path=str(model),
                    repository=repository,
                    object_store=store,
                    transcriber=fake_transcriber,
                )

                self.assertEqual(result, 0)
                self.assertEqual(len(observed), 1)
                self.assertEqual(source.read_bytes(), b"original audio bytes")
                self.assertEqual(len(repository.list_passages()), 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
