import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from warrigal.acquisition.youtube_posts import (
    YouTubePostCheckpointStore,
    _balanced_json_after,
    ingest_youtube_posts,
    parse_youtube_posts,
)


def post_payload():
    return {
        "contents": [{
            "backstagePostThreadRenderer": {
                "post": {
                    "backstagePostRenderer": {
                        "postId": "Ugkx-POST-1",
                        "contentText": {"runs": [{"text": "Grand Unified "}, {"text": "Architecture of Witness"}]},
                        "authorText": {"simpleText": "Jimmy Da Science Preacher"},
                        "authorEndpoint": {"browseEndpoint": {"browseId": "UC-JIMMY", "canonicalBaseUrl": "/@JimmyDaSciencePreacher"}},
                        "publishedTimeText": {"simpleText": "2 days ago"},
                        "voteCount": {"simpleText": "7"},
                        "replyCount": {"simpleText": "3"},
                        "backstageAttachment": {"videoRenderer": {"videoId": "VIDEO-1", "title": "Linked evidence"}},
                    }
                }
            }
        }]
    }


class YouTubePostTests(unittest.TestCase):
    def test_json_locator_skips_javascript_function_definition(self):
        html = (
            "ytcfg.set=function(k,v){if(k){return v;}};"
            'ytcfg.set({"INNERTUBE_API_KEY":"test-key"});'
        )

        self.assertEqual(
            _balanced_json_after(html, "ytcfg.set"),
            {"INNERTUBE_API_KEY": "test-key"},
        )

    def test_renderer_parser_preserves_post_identity_and_text(self):
        posts = parse_youtube_posts(post_payload())

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].post_id, "Ugkx-POST-1")
        self.assertEqual(posts[0].text, "Grand Unified Architecture of Witness")
        self.assertEqual(posts[0].author_id, "UC-JIMMY")
        self.assertEqual(posts[0].author_url, "https://www.youtube.com/@JimmyDaSciencePreacher")
        self.assertEqual(posts[0].published_text, "2 days ago")
        self.assertEqual(posts[0].attachments[0]["videoId"], "VIDEO-1")

    def test_checkpoint_rejects_another_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "posts.json"
            store = YouTubePostCheckpointStore(path)
            store.save("https://youtube.test/@one/posts", {"post-1"})

            with self.assertRaisesRegex(ValueError, "different channel"):
                store.load("https://youtube.test/@two/posts")

    @patch("warrigal.acquisition.youtube_posts.AcquisitionService")
    def test_ingestion_archives_and_indexes_only_uncheckpointed_posts(self, service):
        acquisition = SimpleNamespace(
            object_id="WRG-OBJ-POSTS",
            acquisition_id="WRG-ACQ-POSTS",
            sha256="a" * 64,
            deduplicated=False,
        )
        service.return_value.acquire_bytes.return_value = acquisition
        repository = Mock()
        repository.get_passages_for_object.return_value = []
        info = {
            "channel_url": "https://www.youtube.com/@JimmyDaSciencePreacher/posts",
            "channel_id": "UC-JIMMY",
            "channel_title": "Jimmy Da Science Preacher",
            "pages_fetched": 1,
            "posts": [{
                "post_id": "Ugkx-POST-1",
                "text": "GUA-W manuscript section",
                "author": "Jimmy",
                "author_id": "UC-JIMMY",
                "author_url": "https://www.youtube.com/@JimmyDaSciencePreacher",
                "published_text": "2 days ago",
                "like_count": "7",
                "reply_count": "3",
                "attachments": [],
            }],
        }
        extractor = Mock(return_value=info)

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "posts.json"
            result = ingest_youtube_posts(
                "https://www.youtube.com/@JimmyDaSciencePreacher/posts",
                checkpoint_path=checkpoint,
                max_posts=100,
                max_pages=20,
                repository=repository,
                object_store=Mock(),
                job_id="WRG-JOB", node_id="WRG-NODE",
                batch_id="WRG-BATCH", collection_id="WRG-COL",
                extractor=extractor,
            )

            self.assertEqual(result.new_count, 1)
            self.assertEqual(result.indexed_count, 1)
            passage = repository.save_passage.call_args.args[0]
            self.assertEqual(passage.text, "GUA-W manuscript section")
            self.assertEqual(passage.metadata["post_id"], "Ugkx-POST-1")
            self.assertEqual(passage.metadata["author_id"], "UC-JIMMY")
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(saved["post_ids"], ["Ugkx-POST-1"])


if __name__ == "__main__":
    unittest.main()
