from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from warrigal.acquisition.youtube import YouTubeVideo
from warrigal.acquisition.youtube_channel_workflow import run_youtube_channel_workflow


def acquisition(**values):
    defaults = {
        "object_id": "object", "acquisition_id": "acquisition", "sha256": "hash",
        "collected_count": 3, "passage_count": 0, "new_count": 0,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


class YouTubeStageSelectionTests(unittest.TestCase):
    def run_stage(self, stage, calls):
        video = YouTubeVideo("video-1", "Video", "https://youtu.be/video-1")
        with TemporaryDirectory() as directory:
            return run_youtube_channel_workflow(
                "https://youtube.com/@example",
                checkpoint_path=Path(directory) / "channel.json",
                posts_checkpoint_path=Path(directory) / "posts.json",
                stages=(stage,),
                repository=MagicMock(), object_store=MagicMock(),
                job_id="j", node_id="n", batch_id="b", collection_id="c",
                discoverer=lambda *_a, **_k: [video],
                inventory_preserver=lambda *_a, **_k: acquisition(),
                transcript_ingestor=lambda *_a, **_k: calls.append("transcript"),
                comment_preserver=lambda *_a, **_k: calls.append("comments") or acquisition(),
                posts_ingestor=lambda *_a, **_k: calls.append("posts"),
                comment_indexer=lambda **_k: calls.append("index"),
            )

    def test_comments_stage_only_runs_comments(self):
        calls = []
        result = self.run_stage("comments", calls)
        self.assertEqual(calls, ["comments"])
        self.assertEqual(result.completed_count, 1)

    def test_inventory_stage_runs_no_acquisition_layers(self):
        calls = []
        result = self.run_stage("inventory", calls)
        self.assertEqual(calls, [])
        self.assertEqual(result.selected_count, 0)


if __name__ == "__main__":
    unittest.main()
