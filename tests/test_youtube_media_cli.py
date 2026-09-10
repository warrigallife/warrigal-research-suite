from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from warrigal.audio import TranscriptResult, TranscriptSegment
from warrigal.cli import build_parser
from warrigal.database import initialize_database
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.youtube_media_cli import run_ingest_youtube_media


class YouTubeMediaCLITests(unittest.TestCase):
    def test_parser_accepts_media_command(self):
        args = build_parser().parse_args([
            "ingest-youtube-media",
            "https://www.youtube.com/watch?v=test",
            "--model",
            "model.bin",
        ])
        self.assertEqual(args.url, "https://www.youtube.com/watch?v=test")
        self.assertEqual(args.model, "model.bin")

    def test_archives_before_transcription_and_preserves_youtube_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.bin"
            model.write_bytes(b"fake model")
            db = initialize_database(root / "test.db")

            try:
                repository = WarrigalRepository(db)
                store = ObjectStore(root / "objects")
                observed = []

                def fake_downloader(url, destination):
                    path = destination / "test.mp4"
                    path.write_bytes(b"original youtube media")
                    return path, {
                        "id": "test",
                        "title": "Research Lecture",
                        "webpage_url": "https://www.youtube.com/watch?v=test",
                        "channel": "Test Channel",
                    }

                def fake_transcriber(source_path, *, model_path):
                    archived = Path(source_path)
                    observed.append(archived)
                    self.assertEqual(
                        archived.read_bytes(), b"original youtube media"
                    )
                    self.assertNotIn("warrigal-youtube-", str(archived))
                    return TranscriptResult(
                        source_path=archived,
                        segments=(
                            TranscriptSegment(0, 0, 1000, "Research lecture"),
                        ),
                        raw_json=b'{"transcription":[]}',
                        model_path=Path(model_path),
                    )

                result = run_ingest_youtube_media(
                    "https://www.youtube.com/watch?v=test",
                    model_path=str(model),
                    repository=repository,
                    object_store=store,
                    downloader=fake_downloader,
                    transcriber=fake_transcriber,
                )

                self.assertEqual(result, 0)
                self.assertEqual(len(observed), 1)
                passages = repository.list_passages()
                self.assertEqual(len(passages), 1)
                self.assertEqual(
                    passages[0]["source_url"],
                    "https://www.youtube.com/watch?v=test",
                )
                self.assertEqual(passages[0]["text"], "Research lecture")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
