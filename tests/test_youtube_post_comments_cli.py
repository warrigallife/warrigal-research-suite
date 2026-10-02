import unittest
from unittest.mock import patch

from warrigal.cli import (
    build_parser,
    main,
    run_ingest_youtube_post_comments,
    run_ingest_youtube_post_comments_campaign,
)


class YouTubePostCommentsCLITests(unittest.TestCase):
    def test_parser_accepts_single_post_comment_ingestion_with_unlimited_default(self):
        args = build_parser().parse_args(
            [
                "ingest-youtube-post-comments",
                "https://www.youtube.com/post/Ugkx-1",
                "--checkpoint",
                "workspace/tfj7-post-comments.json",
            ]
        )

        self.assertEqual(args.command, "ingest-youtube-post-comments")
        self.assertEqual(args.post, "https://www.youtube.com/post/Ugkx-1")
        self.assertEqual(args.checkpoint, "workspace/tfj7-post-comments.json")
        self.assertIsNone(args.max_continuation_fetches)

    def test_parser_accepts_explicit_safety_limit(self):
        args = build_parser().parse_args(
            [
                "ingest-youtube-post-comments",
                "Ugkx-1",
                "--checkpoint",
                "workspace/c.json",
                "--max-continuation-fetches",
                "50",
            ]
        )

        self.assertEqual(args.max_continuation_fetches, 50)

    @patch("warrigal.cli.run_ingest_youtube_post_comments", return_value=0)
    def test_main_dispatches_single_post_comment_ingestion(self, run_post_comments):
        with patch(
            "sys.argv",
            [
                "warrigal",
                "ingest-youtube-post-comments",
                "Ugkx-1",
                "--checkpoint",
                "workspace/tfj7-post-comments.json",
            ],
        ):
            result = main()

        self.assertEqual(result, 0)
        run_post_comments.assert_called_once_with(
            "Ugkx-1",
            checkpoint_path="workspace/tfj7-post-comments.json",
            max_continuation_fetches=None,
        )

    def test_parser_accepts_post_comment_campaign_and_skip_completed_flag(self):
        args = build_parser().parse_args(
            [
                "ingest-youtube-post-comments-campaign",
                "https://www.youtube.com/@TFJ7/posts",
                "--posts-checkpoint",
                "workspace/tfj7-posts.json",
                "--comments-checkpoint",
                "workspace/tfj7-post-comments.json",
                "--skip-completed",
            ]
        )

        self.assertEqual(args.command, "ingest-youtube-post-comments-campaign")
        self.assertTrue(args.skip_completed)

    def test_skip_completed_defaults_to_false(self):
        args = build_parser().parse_args(
            [
                "ingest-youtube-post-comments-campaign",
                "https://www.youtube.com/@TFJ7/posts",
                "--posts-checkpoint",
                "workspace/tfj7-posts.json",
                "--comments-checkpoint",
                "workspace/tfj7-post-comments.json",
            ]
        )

        self.assertFalse(args.skip_completed)

    @patch(
        "warrigal.cli.run_ingest_youtube_post_comments_campaign", return_value=0
    )
    def test_main_dispatches_post_comment_campaign(self, run_campaign):
        with patch(
            "sys.argv",
            [
                "warrigal",
                "ingest-youtube-post-comments-campaign",
                "https://www.youtube.com/@TFJ7/posts",
                "--posts-checkpoint",
                "workspace/tfj7-posts.json",
                "--comments-checkpoint",
                "workspace/tfj7-post-comments.json",
                "--max-continuation-fetches",
                "200",
            ],
        ):
            result = main()

        self.assertEqual(result, 0)
        run_campaign.assert_called_once_with(
            "https://www.youtube.com/@TFJ7/posts",
            posts_checkpoint_path="workspace/tfj7-posts.json",
            comments_checkpoint_path="workspace/tfj7-post-comments.json",
            max_continuation_fetches=200,
            skip_completed=False,
        )

    @patch("warrigal.cli.initialize_database")
    def test_single_post_rejects_non_positive_safety_limit_before_database(
        self, database
    ):
        with self.assertRaisesRegex(ValueError, "max-continuation-fetches"):
            run_ingest_youtube_post_comments(
                "Ugkx-1", checkpoint_path="unused.json", max_continuation_fetches=0
            )

        database.assert_not_called()

    @patch("warrigal.cli.initialize_database")
    def test_campaign_rejects_non_positive_safety_limit_before_database(self, database):
        with self.assertRaisesRegex(ValueError, "max-continuation-fetches"):
            run_ingest_youtube_post_comments_campaign(
                "https://www.youtube.com/@TFJ7/posts",
                posts_checkpoint_path="unused-posts.json",
                comments_checkpoint_path="unused-comments.json",
                max_continuation_fetches=0,
            )

        database.assert_not_called()

    @patch("warrigal.cli.acquisition_cdp_runners")
    @patch("warrigal.cli.initialize_database")
    @patch("warrigal.cli.ingest_youtube_post_comments")
    def test_single_post_incomplete_returns_distinct_nonzero_exit_code(
        self, ingest, database, cdp_runners
    ):
        from types import SimpleNamespace

        database.return_value.close = lambda: None
        ingest.return_value = SimpleNamespace(
            post_id="P1",
            post_url="https://www.youtube.com/post/P1",
            object_id="O",
            acquisition_id="A",
            sha256="a" * 64,
            counts=SimpleNamespace(
                visible_comment_count=None,
                visible_count_basis="unavailable",
                top_level_count=0,
                reply_count=0,
                total_count=0,
                count_match="unknown",
            ),
            identity_coverage=SimpleNamespace(
                stable_id_count=0,
                unresolved_provisional_count=0,
                stable_id_coverage_complete=True,
            ),
            new_count=0,
            indexed_count=0,
            target_author_comment_count=0,
            deduplicated=False,
            status="incomplete",
            reasons=("round_limit_reached",),
        )

        result = run_ingest_youtube_post_comments("P1", checkpoint_path="c.json")

        self.assertEqual(result, 2)

    @patch("warrigal.cli.acquisition_cdp_runners")
    @patch("warrigal.cli.initialize_database")
    @patch("warrigal.cli.ingest_youtube_post_comments")
    def test_single_post_failed_returns_one(self, ingest, database, cdp_runners):
        from types import SimpleNamespace

        database.return_value.close = lambda: None
        ingest.return_value = SimpleNamespace(
            post_id="P1",
            post_url="https://www.youtube.com/post/P1",
            object_id="O",
            acquisition_id="A",
            sha256="a" * 64,
            counts=SimpleNamespace(
                visible_comment_count=None,
                visible_count_basis="unavailable",
                top_level_count=0,
                reply_count=0,
                total_count=0,
                count_match="unknown",
            ),
            identity_coverage=SimpleNamespace(
                stable_id_count=0,
                unresolved_provisional_count=0,
                stable_id_coverage_complete=True,
            ),
            new_count=0,
            indexed_count=0,
            target_author_comment_count=0,
            deduplicated=False,
            status="failed",
            reasons=("fetch_failure:RuntimeError: no Brave window",),
        )

        result = run_ingest_youtube_post_comments("P1", checkpoint_path="c.json")

        self.assertEqual(result, 1)

    @patch("warrigal.cli.acquisition_cdp_runners")
    @patch("warrigal.cli.initialize_database")
    @patch("warrigal.cli.run_post_comment_campaign")
    def test_campaign_incomplete_returns_distinct_nonzero_exit_code(
        self, campaign, database, cdp_runners
    ):
        from types import SimpleNamespace

        database.return_value.close = lambda: None
        campaign.return_value = SimpleNamespace(
            known_before_refresh=(),
            newly_discovered=(),
            attempted=("P1",),
            items=(
                SimpleNamespace(
                    post_id="P1",
                    status="incomplete",
                    reasons=("round_limit_reached",),
                    new_count=0,
                    target_author_comment_count=0,
                ),
            ),
            feed_coverage_status="complete",
            feed_coverage_reasons=(),
            completed=(),
            incomplete=("P1",),
            failed=(),
        )

        result = run_ingest_youtube_post_comments_campaign(
            "https://www.youtube.com/@TFJ7/posts",
            posts_checkpoint_path="posts.json",
            comments_checkpoint_path="comments.json",
        )

        self.assertEqual(result, 2)

    @patch("warrigal.cli.acquisition_cdp_runners")
    @patch("warrigal.cli.initialize_database")
    @patch("warrigal.cli.run_post_comment_campaign")
    def test_campaign_with_incomplete_feed_coverage_returns_distinct_nonzero_exit_code(
        self, campaign, database, cdp_runners
    ):
        from types import SimpleNamespace

        database.return_value.close = lambda: None
        campaign.return_value = SimpleNamespace(
            known_before_refresh=(),
            newly_discovered=(),
            attempted=("P1",),
            items=(
                SimpleNamespace(
                    post_id="P1",
                    status="completed",
                    reasons=(),
                    new_count=1,
                    target_author_comment_count=0,
                ),
            ),
            feed_coverage_status="incomplete",
            feed_coverage_reasons=("scroll_limit_reached",),
            completed=("P1",),
            incomplete=(),
            failed=(),
        )

        result = run_ingest_youtube_post_comments_campaign(
            "https://www.youtube.com/@TFJ7/posts",
            posts_checkpoint_path="posts.json",
            comments_checkpoint_path="comments.json",
        )

        self.assertEqual(result, 2)

    @patch("warrigal.cli.acquisition_cdp_runners")
    @patch("warrigal.cli.initialize_database")
    @patch("warrigal.cli.run_post_comment_campaign")
    def test_campaign_with_failure_returns_one_even_if_others_incomplete(
        self, campaign, database, cdp_runners
    ):
        from types import SimpleNamespace

        database.return_value.close = lambda: None
        campaign.return_value = SimpleNamespace(
            known_before_refresh=(),
            newly_discovered=(),
            attempted=("P1", "P2"),
            items=(),
            feed_coverage_status="complete",
            feed_coverage_reasons=(),
            completed=(),
            incomplete=("P1",),
            failed=("P2",),
        )

        result = run_ingest_youtube_post_comments_campaign(
            "https://www.youtube.com/@TFJ7/posts",
            posts_checkpoint_path="posts.json",
            comments_checkpoint_path="comments.json",
        )

        self.assertEqual(result, 1)

    @patch("warrigal.cli.acquisition_cdp_runners")
    @patch("warrigal.cli.initialize_database")
    def test_campaign_with_no_checkpointed_posts_and_no_refresh_still_touches_database(
        self, database, cdp_runners
    ):
        # The campaign now always refreshes first (authenticated feed
        # discovery), so it always initializes the database, unlike the
        # old plan-first short-circuit.
        with patch("warrigal.cli.run_post_comment_campaign") as campaign:
            from types import SimpleNamespace

            campaign.return_value = SimpleNamespace(
                known_before_refresh=(), newly_discovered=(), attempted=(), items=(),
                feed_coverage_status="complete", feed_coverage_reasons=(),
                completed=(), incomplete=(), failed=(),
            )
            result = run_ingest_youtube_post_comments_campaign(
                "https://www.youtube.com/@TFJ7/posts",
                posts_checkpoint_path="unused-posts.json",
                comments_checkpoint_path="unused-comments.json",
            )

        self.assertEqual(result, 0)
        database.assert_called_once()

    @patch("warrigal.cli.acquisition_cdp_runners")
    @patch("warrigal.cli.initialize_database")
    @patch("warrigal.cli.ingest_youtube_post_comments")
    def test_single_post_entry_point_is_wired_to_the_cdp_extractor(
        self, ingest, database, cdp_runners
    ):
        from types import SimpleNamespace

        database.return_value.close = lambda: None
        sentinel_extractor = object()
        cdp_runners.return_value.__enter__.return_value = SimpleNamespace(
            comment_extractor=sentinel_extractor
        )
        ingest.return_value = SimpleNamespace(
            post_id="P1",
            post_url="https://www.youtube.com/post/P1",
            object_id="O",
            acquisition_id="A",
            sha256="a" * 64,
            counts=SimpleNamespace(
                visible_comment_count=None,
                visible_count_basis="unavailable",
                top_level_count=0,
                reply_count=0,
                total_count=0,
                count_match="unknown",
            ),
            identity_coverage=SimpleNamespace(
                stable_id_count=0,
                unresolved_provisional_count=0,
                stable_id_coverage_complete=True,
            ),
            new_count=0,
            indexed_count=0,
            target_author_comment_count=0,
            deduplicated=False,
            status="completed",
            reasons=(),
        )

        run_ingest_youtube_post_comments("P1", checkpoint_path="c.json")

        self.assertIs(ingest.call_args.kwargs["extractor"], sentinel_extractor)
        cdp_runners.return_value.__enter__.assert_called_once()
        cdp_runners.return_value.__exit__.assert_called_once()

    @patch("warrigal.cli.acquisition_cdp_runners")
    @patch("warrigal.cli.initialize_database")
    @patch("warrigal.cli.run_post_comment_campaign")
    def test_campaign_entry_point_is_wired_to_the_cdp_extractor_and_refresher(
        self, campaign, database, cdp_runners
    ):
        from types import SimpleNamespace

        database.return_value.close = lambda: None
        sentinel_extractor = object()
        sentinel_refresher = object()
        cdp_runners.return_value.__enter__.return_value = SimpleNamespace(
            comment_extractor=sentinel_extractor, post_feed_refresher=sentinel_refresher
        )
        campaign.return_value = SimpleNamespace(
            known_before_refresh=(),
            newly_discovered=(),
            attempted=(),
            items=(),
            feed_coverage_status="complete",
            feed_coverage_reasons=(),
            completed=(),
            incomplete=(),
            failed=(),
        )

        run_ingest_youtube_post_comments_campaign(
            "https://www.youtube.com/@TFJ7/posts",
            posts_checkpoint_path="posts.json",
            comments_checkpoint_path="comments.json",
        )

        self.assertIs(campaign.call_args.kwargs["comment_extractor"], sentinel_extractor)
        self.assertIs(campaign.call_args.kwargs["post_feed_refresher"], sentinel_refresher)
        cdp_runners.return_value.__enter__.assert_called_once()
        cdp_runners.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
