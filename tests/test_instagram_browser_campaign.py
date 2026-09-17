from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import warrigal.instagram_browser_campaign as campaign


class InstagramBrowserCampaignTests(unittest.TestCase):
    def test_clean_caption_removes_browser_wrapper(self):
        wrapped = (
            '1,234 likes, 56 comments - EEAnimation: '
            '"A useful engineering caption.".'
        )

        self.assertEqual(
            campaign.clean_caption(wrapped),
            "A useful engineering caption.",
        )
        self.assertEqual(
            campaign.clean_caption("Already clean"),
            "Already clean",
        )

    def test_remove_byte_range_preserves_other_query_values(self):
        source = (
            "https://cdn.example/media.mp4?"
            "token=abc&bytestart=0&byteend=999&quality=hd"
        )

        cleaned = campaign.remove_byte_range(source)

        self.assertIn("token=abc", cleaned)
        self.assertIn("quality=hd", cleaned)
        self.assertNotIn("bytestart", cleaned)
        self.assertNotIn("byteend", cleaned)

    def test_checkpoint_round_trip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            initial = campaign.load_checkpoint(path)

            self.assertEqual(initial["version"], 1)
            self.assertEqual(initial["completed"], {})
            self.assertEqual(initial["failed"], {})

            initial["completed"]["post"] = {
                "evidence_files": 2,
            }
            campaign.save_checkpoint(path, initial)

            self.assertEqual(
                campaign.load_checkpoint(path),
                initial,
            )
            self.assertFalse(
                path.with_suffix(".json.tmp").exists()
            )

    def test_extract_post_normalizes_browser_payload(self):
        payload = {
            "shortcode": "ABC123",
            "source_url":
                "https://www.instagram.com/p/ABC123/",
            "date_utc": "2026-09-01T00:00:00Z",
            "caption": (
                '20 likes, 3 comments - EEAnimation: '
                '"Caption text".'
            ),
            "media": [
                {
                    "type": "image",
                    "url": "https://cdn.example/image.jpg",
                }
            ],
        }

        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

        with patch.object(
            campaign.subprocess,
            "run",
            return_value=completed,
        ):
            result = campaign.extract_post(
                "https://www.instagram.com/p/ABC123/"
            )

        self.assertEqual(result["caption"], "Caption text")
        self.assertEqual(result["shortcode"], "ABC123")

    def test_downloader_writes_metadata_and_ordered_media(self):
        payload = {
            "shortcode": "ABC123",
            "source_url":
                "https://www.instagram.com/p/ABC123/",
            "date_utc": "2026-09-01T00:00:00Z",
            "caption": "Caption",
            "media": [
                {
                    "type": "image",
                    "url":
                        "https://cdn.example/first.jpg?token=1",
                },
                {
                    "type": "video",
                    "url":
                        "https://cdn.example/second?token=2",
                },
            ],
        }

        post = SimpleNamespace(shortcode="ABC123")

        with TemporaryDirectory() as directory:
            downloader = campaign.BrowserEvidenceDownloader(
                payload
            )
            downloader.dirname_pattern = str(
                Path(directory) / "{target}"
            )

            destinations = []

            def fake_download(source_url, destination):
                destinations.append(
                    (source_url, destination.name)
                )
                destination.write_bytes(b"evidence")

            downloader.download = fake_download
            downloader.download_post(post, "post")

            metadata = (
                Path(directory)
                / "post"
                / "ABC123.browser.json"
            )

            self.assertTrue(metadata.is_file())
            self.assertEqual(
                [name for _, name in destinations],
                [
                    "ABC123_01.jpg",
                    "ABC123_02.mp4",
                ],
            )

    def test_archive_post_restores_normalizer(self):
        payload = {
            "shortcode": "ABC123",
            "source_url":
                "https://www.instagram.com/p/ABC123/",
            "date_utc": "2026-09-01T00:00:00Z",
            "caption": "Caption",
            "media": [
                {
                    "type": "image",
                    "url": "https://cdn.example/image.jpg",
                }
            ],
        }

        original = (
            campaign.instagram_acquisition
            .post_from_instaloader
        )
        captured = {}

        def fake_ingest(raw_post, **kwargs):
            captured["post"] = (
                campaign.instagram_acquisition
                .post_from_instaloader(raw_post)
            )
            return {"snapshot": "saved", "evidence": []}

        identity = SimpleNamespace(
            job_id="JOB",
            node_id="NODE",
            batch_id="BATCH",
            collection_id="COLLECTION",
        )

        with (
            patch.object(
                campaign,
                "extract_post",
                return_value=payload,
            ),
            patch.object(
                campaign.instagram_acquisition,
                "ingest_instagram_post",
                side_effect=fake_ingest,
            ),
        ):
            result = campaign.archive_post(
                payload["source_url"],
                repository=object(),
                object_store=object(),
                job=identity,
                node=identity,
                batch=identity,
                collection=identity,
            )

        self.assertEqual(result["snapshot"], "saved")
        self.assertEqual(
            captured["post"].shortcode,
            "ABC123",
        )
        self.assertEqual(
            captured["post"].typename,
            "GraphImage",
        )
        self.assertIs(
            campaign.instagram_acquisition
            .post_from_instaloader,
            original,
        )


if __name__ == "__main__":
    unittest.main()
