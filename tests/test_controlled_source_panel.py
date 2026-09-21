from __future__ import annotations

import unittest

from warrigal.source_panel import build_website_commands, build_youtube_commands


class ControlledSourcePanelTests(unittest.TestCase):
    def test_youtube_layers_are_independent_commands(self):
        url = "https://www.youtube.com/@DutchUncleJohn"
        cases = {
            "Discover channel inventory": "inventory",
            "Acquire / resume transcripts": "transcripts",
            "Acquire / resume comments": "comments",
            "Acquire / resume Community posts": "posts",
            "Index archived comments": "index",
        }
        for action, stage in cases.items():
            with self.subTest(action=action):
                command = build_youtube_commands(url, action)[0][1]
                self.assertEqual(command[command.index("--stage") + 1], stage)

    def test_all_layers_is_explicit_and_has_no_stage_filter(self):
        command = build_youtube_commands(
            "https://www.youtube.com/@DutchUncleJohn",
            "All research layers",
        )[0][1]
        self.assertNotIn("--stage", command)

    def test_youtube_limits_are_forwarded_to_channel_workflow(self):
        command = build_youtube_commands(
            "https://www.youtube.com/@DutchUncleJohn",
            "Acquire / resume comments",
            max_videos=4,
            max_comments=250,
            max_posts=25,
        )[0][1]

        self.assertEqual(command[command.index("--max-videos") + 1], "4")
        self.assertEqual(command[command.index("--max-comments") + 1], "250")
        self.assertEqual(command[command.index("--max-posts") + 1], "25")

    def test_single_video_media_action_uses_whisper_media_pipeline(self):
        command = build_youtube_commands(
            "https://www.youtube.com/watch?v=example",
            "Single-video media + Whisper transcript",
        )[0][1]

        self.assertIn("ingest-youtube-media", command)
        self.assertNotIn("ingest-youtube-channel", command)

    def test_single_video_caption_action_does_not_download_media(self):
        command = build_youtube_commands(
            "https://www.youtube.com/watch?v=example",
            "Single-video available caption",
        )[0][1]

        self.assertIn("ingest-youtube", command)
        self.assertNotIn("ingest-youtube-media", command)

    def test_website_document_workflow_reuses_paths(self):
        url = "https://example.test/library"
        inventory = build_website_commands(
            url, "Inventory documents and preserve website sections"
        )[0][1]
        acquire = build_website_commands(
            url, "Acquire / resume smaller documents (up to 25 MB)"
        )[0][1]
        verify = build_website_commands(
            url, "Verify all inventoried documents"
        )[0][1]
        manifest = inventory[inventory.index("--output") + 1]
        self.assertIn(manifest, acquire)
        self.assertIn(manifest, verify)

    def test_website_selected_workflow_uses_derived_manifest(self):
        url = "https://example.test/library"
        review = build_website_commands(
            url, "Review / select inventoried documents"
        )[0][1]
        acquire = build_website_commands(
            url, "Acquire / resume selected smaller documents (up to 25 MB)"
        )[0][1]
        verify = build_website_commands(
            url, "Verify selected documents"
        )[0][1]
        selected = review[review.index("--output") + 1]
        self.assertTrue(selected.endswith("-selected.json"))
        self.assertIn(selected, acquire)
        self.assertIn(selected, verify)

    def test_website_publication_uses_selected_manifest_and_readable_collection(self):
        url = "https://www.radionictech.com/free-ebooks.html"
        review = build_website_commands(
            url, "Review / select inventoried documents"
        )[0][1]
        publish = build_website_commands(
            url, "Publish selected documents"
        )[0][1]
        selected = review[review.index("--output") + 1]
        self.assertIn(selected, publish)
        output = publish[publish.index("--output-root") + 1]
        self.assertTrue(output.endswith("COLLECTIONS/WEBSITES/radionictech.com"))
        self.assertIn("warrigal.publish_manifest_collection", publish)


if __name__ == "__main__":
    unittest.main()
