"""Focused tests for the ingest-youtube-channel CLI orchestration."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from warrigal.cli import run_ingest_youtube_channel


def _workflow_result(**extra):
    values = {
        "channel_url": "https://youtube.com/@example",
        "inventory_object_id": "",
        "discovered_count": 0,
        "selected_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "unavailable_transcript_count": 0,
        "acquired_transcript_count": 0,
        "comments_collected": 0,
        "community_posts_status": "completed",
        "community_posts_collected": 0,
        "community_posts_new": 0,
        "community_posts_deduplicated": None,
        "indexed_comment_count": 0,
        "comment_index_scope": "not_run",
    }
    values.update(extra)
    return MagicMock(**values)


class YouTubeChannelCLITests(unittest.TestCase):
    def _run(self, stages):
        with patch("warrigal.cli.resolve_youtube_channel") as resolve, \
             patch("warrigal.cli.initialize_database") as init_db, \
             patch("warrigal.cli.WarrigalRepository") as repository_cls, \
             patch("warrigal.cli.ObjectStore"), \
             patch("warrigal.cli.run_youtube_channel_workflow") as run_workflow:
            resolve.return_value = MagicMock(
                channel_id="UC123",
                title="Example",
                canonical_url="https://www.youtube.com/channel/UC123/videos",
            )
            init_db.return_value = MagicMock()
            repository_cls.return_value = MagicMock()
            run_workflow.return_value = _workflow_result()

            result = run_ingest_youtube_channel(
                "https://youtube.com/@example",
                checkpoint_path="c.json",
                posts_checkpoint_path="p.json",
                stages=stages,
            )
        return result, resolve, run_workflow

    def test_posts_only_run_does_not_resolve_channel_identity(self):
        result, resolve, run_workflow = self._run(["posts"])

        resolve.assert_not_called()
        self.assertEqual(result, 0)
        run_workflow.assert_called_once()
        self.assertEqual(
            run_workflow.call_args.args[0], "https://youtube.com/@example"
        )

    def test_transcripts_stage_still_resolves_channel_identity(self):
        result, resolve, run_workflow = self._run(["transcripts"])

        resolve.assert_called_once_with("https://youtube.com/@example")
        self.assertEqual(result, 0)
        self.assertEqual(
            run_workflow.call_args.args[0],
            "https://www.youtube.com/channel/UC123/videos",
        )

    def test_combined_stages_including_posts_still_resolve_channel_identity(self):
        result, resolve, run_workflow = self._run(["transcripts", "posts"])

        resolve.assert_called_once_with("https://youtube.com/@example")
        self.assertEqual(result, 0)
        self.assertEqual(
            run_workflow.call_args.args[0],
            "https://www.youtube.com/channel/UC123/videos",
        )


if __name__ == "__main__":
    unittest.main()
