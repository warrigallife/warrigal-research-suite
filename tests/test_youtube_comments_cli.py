import unittest
from unittest.mock import patch

from warrigal.cli import (
    build_parser,
    main,
    run_ingest_youtube_comments,
)


class YouTubeCommentsCLITests(unittest.TestCase):
    def test_parser_accepts_youtube_post_ingestion(self):
        args = build_parser().parse_args([
            "ingest-youtube-posts",
            "https://www.youtube.com/@JimmyDaSciencePreacher/posts",
            "--checkpoint", "workspace/jimmy-posts.json",
            "--max-posts", "80",
            "--max-pages", "12",
        ])

        self.assertEqual(args.command, "ingest-youtube-posts")
        self.assertEqual(args.max_posts, 80)
        self.assertEqual(args.max_pages, 12)

    @patch("warrigal.cli.run_ingest_youtube_posts", return_value=0)
    def test_main_dispatches_youtube_post_ingestion(self, run_posts):
        with patch("sys.argv", [
            "warrigal", "ingest-youtube-posts",
            "https://www.youtube.com/@JimmyDaSciencePreacher/posts",
            "--checkpoint", "workspace/jimmy-posts.json",
        ]):
            result = main()

        self.assertEqual(result, 0)
        run_posts.assert_called_once_with(
            "https://www.youtube.com/@JimmyDaSciencePreacher/posts",
            checkpoint_path="workspace/jimmy-posts.json",
            max_posts=100,
            max_pages=20,
        )

    def test_parser_accepts_local_comment_research_commands(self):
        parser = build_parser()

        index_args = parser.parse_args(["index-youtube-comments"])
        find_args = parser.parse_args(
            ["find-youtube-comment-authors", "scrolls"]
        )
        show_args = parser.parse_args(
            ["show-youtube-comments-by-author", "UC-TOM"]
        )

        self.assertEqual(index_args.command, "index-youtube-comments")
        self.assertEqual(find_args.query, "scrolls")
        self.assertEqual(show_args.identity, "UC-TOM")

    @patch("warrigal.cli.run_index_youtube_comments", return_value=0)
    def test_main_dispatches_local_comment_index(self, run_index):
        with patch("sys.argv", ["warrigal", "index-youtube-comments"]):
            result = main()

        self.assertEqual(result, 0)
        run_index.assert_called_once_with()

    @patch("warrigal.cli.run_find_youtube_comment_authors", return_value=0)
    def test_main_dispatches_author_search(self, run_find):
        with patch(
            "sys.argv",
            ["warrigal", "find-youtube-comment-authors", "scrolls"],
        ):
            result = main()

        self.assertEqual(result, 0)
        run_find.assert_called_once_with("scrolls")

    @patch("warrigal.cli.run_show_youtube_comments_by_author", return_value=0)
    def test_main_dispatches_author_comment_listing(self, run_show):
        with patch(
            "sys.argv",
            ["warrigal", "show-youtube-comments-by-author", "UC-TOM"],
        ):
            result = main()

        self.assertEqual(result, 0)
        run_show.assert_called_once_with("UC-TOM")

    def test_parser_accepts_checkpointed_channel_campaign(self):
        args = build_parser().parse_args(
            [
                "ingest-youtube-channel-comments",
                "https://www.youtube.com/@randall/videos",
                "--target-author-id",
                "UC-TOM",
                "--target-author-handle",
                "@TFJ7",
                "--checkpoint",
                "workspace/tom-comments.json",
                "--scan-videos",
                "80",
                "--max-videos",
                "4",
                "--max-comments",
                "600",
            ]
        )

        self.assertEqual(args.command, "ingest-youtube-channel-comments")
        self.assertEqual(args.target_author_id, "UC-TOM")
        self.assertEqual(args.scan_videos, 80)
        self.assertEqual(args.max_videos, 4)
        self.assertEqual(args.max_comments, 600)

    @patch("warrigal.cli.run_ingest_youtube_channel_comments", return_value=0)
    def test_main_dispatches_channel_campaign(self, run_campaign):
        with patch(
            "sys.argv",
            [
                "warrigal",
                "ingest-youtube-channel-comments",
                "https://www.youtube.com/@randall/videos",
                "--target-author-id",
                "UC-TOM",
                "--checkpoint",
                "workspace/tom-comments.json",
            ],
        ):
            result = main()

        self.assertEqual(result, 0)
        run_campaign.assert_called_once_with(
            "https://www.youtube.com/@randall/videos",
            target_author_id="UC-TOM",
            target_author_handle=None,
            checkpoint_path="workspace/tom-comments.json",
            scan_videos=100,
            max_videos=5,
            max_comments=1000,
        )

    def test_parser_accepts_bounded_target_author_collection(self):
        args = build_parser().parse_args(
            [
                "ingest-youtube-comments",
                "https://www.youtube.com/watch?v=test",
                "--target-author-handle",
                "@TFJ7",
                "--max-comments",
                "500",
            ]
        )

        self.assertEqual(args.command, "ingest-youtube-comments")
        self.assertEqual(args.target_author_handle, "@TFJ7")
        self.assertEqual(args.max_comments, 500)

    @patch("warrigal.cli.run_ingest_youtube_comments", return_value=0)
    def test_main_dispatches_comment_ingestion(self, run_comments):
        with patch(
            "sys.argv",
            [
                "warrigal",
                "ingest-youtube-comments",
                "https://www.youtube.com/watch?v=test",
                "--target-author-id",
                "UC-TOM",
                "--target-author-handle",
                "@TFJ7",
                "--max-comments",
                "750",
            ],
        ):
            result = main()

        self.assertEqual(result, 0)
        run_comments.assert_called_once_with(
            "https://www.youtube.com/watch?v=test",
            target_author_id="UC-TOM",
            target_author_handle="@TFJ7",
            max_comments=750,
        )

    @patch("warrigal.cli.initialize_database")
    def test_validation_happens_before_database_creation(self, database):
        with self.assertRaisesRegex(ValueError, "target-author"):
            run_ingest_youtube_comments(
                "https://www.youtube.com/watch?v=test"
            )

        database.assert_not_called()


if __name__ == "__main__":
    unittest.main()
