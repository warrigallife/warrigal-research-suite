import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock

from warrigal.acquisition.youtube import YouTubeVideo
from warrigal.acquisition.youtube_comment_campaign import (
    YouTubeCommentCheckpointStore,
    run_youtube_comment_campaign,
)


def videos():
    return [
        YouTubeVideo("one", "One", "https://youtube.test/watch?v=one"),
        YouTubeVideo("two", "Two", "https://youtube.test/watch?v=two"),
        YouTubeVideo("three", "Three", "https://youtube.test/watch?v=three"),
    ]


def result_for(video_url):
    video_id = video_url.rsplit("=", 1)[1]
    return SimpleNamespace(
        video_id=video_id,
        object_id=f"object-{video_id}",
        acquisition_id=f"acquisition-{video_id}",
        collected_count=20,
        matched_count=2,
        context_count=3,
    )


class YouTubeCommentCampaignTests(unittest.TestCase):
    def test_campaign_is_bounded_and_resumes_after_checkpoint(self):
        with TemporaryDirectory() as temporary_directory:
            checkpoint = Path(temporary_directory) / "comments.json"
            calls = []

            def ingest(video_url, **kwargs):
                calls.append(video_url)
                return result_for(video_url)

            common = {
                "target_author_id": "UC-TOM",
                "target_author_handle": "@TFJ7",
                "checkpoint_path": checkpoint,
                "scan_videos": 3,
                "max_videos": 1,
                "max_comments": 500,
                "repository": MagicMock(),
                "object_store": MagicMock(),
                "job_id": "job",
                "node_id": "node",
                "batch_id": "batch",
                "collection_id": "collection",
                "discoverer": lambda url, max_videos: videos(),
                "ingestor": ingest,
            }

            first = run_youtube_comment_campaign(
                "https://youtube.test/@randall/videos",
                **common,
            )
            second = run_youtube_comment_campaign(
                "https://youtube.test/@randall/videos",
                **common,
            )

            self.assertEqual(
                calls,
                [
                    "https://youtube.test/watch?v=one",
                    "https://youtube.test/watch?v=two",
                ],
            )
            self.assertEqual(first.selected_count, 1)
            self.assertEqual(first.matched_count, 2)
            self.assertEqual(first.context_count, 3)
            self.assertEqual(second.selected_count, 1)
            self.assertEqual(second.items[0].status, "skipped_checkpoint")

    def test_failure_is_checkpointed_and_does_not_stop_later_video(self):
        with TemporaryDirectory() as temporary_directory:
            checkpoint = Path(temporary_directory) / "comments.json"
            calls = []

            def ingest(video_url, **kwargs):
                calls.append(video_url)
                if video_url.endswith("=one"):
                    raise TimeoutError("comment request timed out")
                return result_for(video_url)

            result = run_youtube_comment_campaign(
                "https://youtube.test/@randall/videos",
                target_author_id="UC-TOM",
                checkpoint_path=checkpoint,
                scan_videos=3,
                max_videos=2,
                repository=MagicMock(),
                object_store=MagicMock(),
                job_id="job",
                node_id="node",
                batch_id="batch",
                collection_id="collection",
                discoverer=lambda url, max_videos: videos(),
                ingestor=ingest,
            )

            self.assertEqual(len(calls), 2)
            self.assertEqual(result.failed_count, 1)
            self.assertEqual(result.completed_count, 1)
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(payload["videos"]["one"]["status"], "failed")
            self.assertEqual(payload["videos"]["two"]["status"], "completed")

    def test_failed_video_is_retried_on_next_run(self):
        with TemporaryDirectory() as temporary_directory:
            checkpoint = Path(temporary_directory) / "comments.json"
            store = YouTubeCommentCheckpointStore(checkpoint)
            store.save(
                "https://youtube.test/@randall/videos",
                "UC-TOM",
                {
                    "one": {
                        "status": "failed",
                        "attempts": 1,
                        "url": "https://youtube.test/watch?v=one",
                    }
                },
            )
            calls = []

            result = run_youtube_comment_campaign(
                "https://youtube.test/@randall/videos",
                target_author_id="UC-TOM",
                checkpoint_path=checkpoint,
                scan_videos=1,
                max_videos=1,
                repository=MagicMock(),
                object_store=MagicMock(),
                job_id="job",
                node_id="node",
                batch_id="batch",
                collection_id="collection",
                discoverer=lambda url, max_videos: videos()[:1],
                ingestor=lambda url, **kwargs: (
                    calls.append(url) or result_for(url)
                ),
            )

            self.assertEqual(calls, ["https://youtube.test/watch?v=one"])
            self.assertEqual(result.completed_count, 1)
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(payload["videos"]["one"]["attempts"], 2)

    def test_new_video_advances_before_retrying_failure(self):
        with TemporaryDirectory() as temporary_directory:
            checkpoint = Path(temporary_directory) / "comments.json"
            YouTubeCommentCheckpointStore(checkpoint).save(
                "https://youtube.test/@randall/videos",
                "UC-TOM",
                {"one": {"status": "failed", "attempts": 1}},
            )
            calls = []

            run_youtube_comment_campaign(
                "https://youtube.test/@randall/videos",
                target_author_id="UC-TOM",
                checkpoint_path=checkpoint,
                scan_videos=3,
                max_videos=1,
                repository=MagicMock(),
                object_store=MagicMock(),
                job_id="job",
                node_id="node",
                batch_id="batch",
                collection_id="collection",
                discoverer=lambda url, max_videos: videos(),
                ingestor=lambda url, **kwargs: (
                    calls.append(url) or result_for(url)
                ),
            )

            self.assertEqual(calls, ["https://youtube.test/watch?v=two"])

    def test_checkpoint_rejects_different_identity(self):
        with TemporaryDirectory() as temporary_directory:
            checkpoint = Path(temporary_directory) / "comments.json"
            store = YouTubeCommentCheckpointStore(checkpoint)
            store.save("channel-one", "UC-TOM", {})

            with self.assertRaisesRegex(ValueError, "different channel"):
                store.load("channel-two", "UC-TOM")
            with self.assertRaisesRegex(ValueError, "different target"):
                store.load("channel-one", "UC-OTHER")


if __name__ == "__main__":
    unittest.main()
