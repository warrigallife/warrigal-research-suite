import io
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from warrigal import cli
from warrigal.acquisition.youtube import YouTubeVideoMetadata
from warrigal.database import initialize_database
from warrigal.object_store import ObjectStore

CAPTION_DATA = (
    b'{"events":['
    b'{"tStartMs":1000,"dDurationMs":1000,'
    b'"segs":[{"utf8":"First sentence. Second"}]},'
    b'{"tStartMs":2000,"dDurationMs":1000,'
    b'"segs":[{"utf8":" sentence?"}]}'
    b']}'
)

METADATA = YouTubeVideoMetadata(
    video_id="fixture-video",
    title="Fixture Save-And-Find Video",
    channel="Fixture Channel",
    channel_id="fixture-channel",
    upload_date="20261108",
    duration=3,
    url="https://www.youtube.com/watch?v=fixture-video",
    description="Fixture description",
)


class RunIngestYoutubeTests(unittest.TestCase):
    """Covers the paste-URL -> acquire -> confirm -> find -> open workflow
    for a single video, using a controlled local fixture (no network
    calls) -- `extract_video_metadata`/`acquire_json3_transcript` are the
    only two network-touching calls `ingest_video_transcript` makes, and
    both are mocked; everything else (database, object store, the
    publisher) runs for real against a temporary directory."""

    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.db_path = root / "warrigal.db"
        self.object_store = ObjectStore(root / "objects")
        self.output_root = root / "COLLECTIONS" / "YOUTUBE"

    def tearDown(self):
        self.temporary.cleanup()

    def _ingestion_patches(self):
        return (
            mock.patch(
                "warrigal.cli.initialize_database",
                side_effect=lambda: initialize_database(self.db_path),
            ),
            mock.patch("warrigal.cli.ObjectStore", return_value=self.object_store),
            mock.patch("warrigal.cli.YOUTUBE_COLLECTION_OUTPUT_ROOT", self.output_root),
            mock.patch(
                "warrigal.acquisition.youtube.extract_video_metadata",
                return_value=METADATA,
            ),
            mock.patch(
                "warrigal.acquisition.youtube.acquire_json3_transcript",
                return_value=CAPTION_DATA,
            ),
        )

    def _run(self, url: str) -> tuple[int, str]:
        with ExitStack() as stack:
            for patcher in self._ingestion_patches():
                stack.enter_context(patcher)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cli.run_ingest_youtube(url)
        return exit_code, buffer.getvalue()

    def test_successful_ingest_is_published_and_reported(self):
        exit_code, output = self._run(METADATA.url)

        self.assertEqual(exit_code, 0)
        self.assertIn("RESULT:", output)
        self.assertIn("NEWLY ACQUIRED", output)
        self.assertIn("COLLECTION:", output)

        collection_line = next(
            line for line in output.splitlines() if line.startswith("COLLECTION:")
        )
        folder = Path(collection_line.split("COLLECTION:", 1)[1].strip())

        self.assertTrue(folder.exists())
        video_markdown = (folder / "VIDEO.md").read_text(encoding="utf-8")
        self.assertIn("Fixture Save-And-Find Video", video_markdown)
        self.assertIn("First sentence", video_markdown)

    def test_rerun_reports_already_archived_and_still_locates_it(self):
        self._run(METADATA.url)
        exit_code, output = self._run(METADATA.url)

        self.assertEqual(exit_code, 0)
        self.assertIn("ALREADY ARCHIVED", output)
        self.assertIn("COLLECTION:", output)

    def test_ingestion_failure_is_reported_clearly_and_nothing_is_published(self):
        with mock.patch(
            "warrigal.cli.initialize_database",
            side_effect=lambda: initialize_database(self.db_path),
        ), mock.patch(
            "warrigal.cli.ObjectStore", return_value=self.object_store
        ), mock.patch(
            "warrigal.cli.YOUTUBE_COLLECTION_OUTPUT_ROOT", self.output_root
        ), mock.patch(
            "warrigal.acquisition.youtube.extract_video_metadata",
            side_effect=ValueError(
                "YouTube returned no channel information for this URL"
            ),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cli.run_ingest_youtube(
                    "https://www.youtube.com/watch?v=missing-video"
                )

        self.assertEqual(exit_code, 1)
        output = buffer.getvalue()
        self.assertIn("INGESTION FAILED", output)
        self.assertIn("ERROR:", output)
        self.assertFalse(self.output_root.exists())


if __name__ == "__main__":
    unittest.main()
