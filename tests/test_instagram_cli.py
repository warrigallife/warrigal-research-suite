import sys
import unittest
from unittest.mock import patch

from warrigal.cli import build_parser, main
from warrigal.instagram_cli import instagram_shortcode


class InstagramCLITests(unittest.TestCase):
    def test_shortcode_and_post_urls(self):
        self.assertEqual(instagram_shortcode("ABC_123-"), "ABC_123-")
        self.assertEqual(
            instagram_shortcode("https://www.instagram.com/p/ABC_123-/"),
            "ABC_123-",
        )
        self.assertEqual(
            instagram_shortcode("https://www.instagram.com/reel/XYZ987/?utm_source=test"),
            "XYZ987",
        )

    def test_invalid_urls_are_rejected(self):
        for value in (
            "https://example.com/p/ABC123/",
            "https://www.instagram.com/australian_native_mushrooms/",
            "ftp://www.instagram.com/p/ABC123/",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    instagram_shortcode(value)

    def test_parser_accepts_instagram_command(self):
        args = build_parser().parse_args([
            "ingest-instagram",
            "ABC123",
            "--username",
            "australian_native_mushrooms",
        ])
        self.assertEqual(args.command, "ingest-instagram")
        self.assertEqual(args.post, "ABC123")
        self.assertEqual(args.username, "australian_native_mushrooms")

    def test_dispatch_calls_instagram_runner(self):
        with patch.object(sys, "argv", [
            "warrigal",
            "ingest-instagram",
            "ABC123",
            "--username",
            "australian_native_mushrooms",
        ]):
            with patch("warrigal.cli.run_ingest_instagram", return_value=0) as runner:
                self.assertEqual(main(), 0)
                runner.assert_called_once_with(
                    "ABC123",
                    username="australian_native_mushrooms",
                )


    def test_profile_parser_accepts_limit(self):
        from warrigal.cli import build_parser

        args = build_parser().parse_args([
            "ingest-instagram-profile",
            "australian_native_mushrooms",
            "--username", "australian_native_mushrooms",
            "--max-posts", "2",
        ])
        self.assertEqual(args.command, "ingest-instagram-profile")
        self.assertEqual(args.profile, "australian_native_mushrooms")
        self.assertEqual(args.max_posts, 2)

    def test_profile_dispatch_calls_runner(self):
        import sys
        from unittest.mock import patch
        from warrigal.cli import main

        with patch.object(sys, "argv", [
            "warrigal", "ingest-instagram-profile",
            "australian_native_mushrooms",
            "--username", "australian_native_mushrooms",
            "--max-posts", "2",
        ]):
            with patch(
                "warrigal.cli.run_ingest_instagram_profile", return_value=0
            ) as runner:
                self.assertEqual(main(), 0)
                runner.assert_called_once_with(
                    "australian_native_mushrooms",
                    username="australian_native_mushrooms",
                    max_posts=2,
            resume=False,
                )

    def test_own_profile_uses_authenticated_route(self):
        from unittest.mock import Mock, patch
        from warrigal.instagram_cli import run_ingest_instagram_profile

        loader = Mock()
        loader.test_login.return_value = "australian_native_mushrooms"
        profile = Mock()
        profile.username = "australian_native_mushrooms"

        with (
            patch("instaloader.Instaloader", return_value=loader),
            patch("instaloader.Profile.own_profile", return_value=profile) as own,
            patch("instaloader.Profile.from_username") as resolve,
            patch("warrigal.instagram_cli.initialize_database") as database,
            patch("warrigal.instagram_cli.WarrigalRepository"),
            patch("warrigal.instagram_cli.ObjectStore"),
            patch("warrigal.instagram_cli.Node"),
            patch("warrigal.instagram_cli.Batch"),
            patch("warrigal.instagram_cli.Job"),
            patch("warrigal.instagram_cli.Collection"),
            patch("warrigal.instagram_cli.ingest_instagram_profile", return_value=[]),
        ):
            result = run_ingest_instagram_profile(
                "australian_native_mushrooms",
                username="australian_native_mushrooms",
                max_posts=1,
            )

        self.assertEqual(result, 0)
        own.assert_called_once_with(loader.context)
        resolve.assert_not_called()
        database.return_value.close.assert_called_once()

    def test_profile_reports_acquisition_provenance(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from warrigal.instagram_cli import run_ingest_instagram_profile

        loader = Mock()
        loader.test_login.return_value = "australian_native_mushrooms"
        profile = Mock()
        profile.username = "australian_native_mushrooms"

        snapshot = SimpleNamespace(
            object_id="WRG-OBJ-SNAPSHOT",
            acquisition_id="WRG-ACQ-SNAPSHOT",
            deduplicated=True,
        )
        evidence = SimpleNamespace(
            object_id="WRG-OBJ-EVIDENCE",
            acquisition_id="WRG-ACQ-EVIDENCE",
            deduplicated=False,
        )
        results = [{
            "post": SimpleNamespace(url="https://www.instagram.com/p/TEST123/"),
            "snapshot": snapshot,
            "evidence": [evidence],
        }]

        output = StringIO()
        with (
            patch("instaloader.Instaloader", return_value=loader),
            patch("instaloader.Profile.own_profile", return_value=profile),
            patch("warrigal.instagram_cli.initialize_database") as database,
            patch("warrigal.instagram_cli.WarrigalRepository"),
            patch("warrigal.instagram_cli.ObjectStore"),
            patch("warrigal.instagram_cli.Node"),
            patch("warrigal.instagram_cli.Batch"),
            patch("warrigal.instagram_cli.Job"),
            patch("warrigal.instagram_cli.Collection"),
            patch("warrigal.instagram_cli.ingest_instagram_profile", return_value=results),
            redirect_stdout(output),
        ):
            result = run_ingest_instagram_profile(
                "australian_native_mushrooms",
                username="australian_native_mushrooms",
                max_posts=1,
            )

        text = output.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("WRG-OBJ-SNAPSHOT", text)
        self.assertIn("WRG-ACQ-SNAPSHOT", text)
        self.assertIn("WRG-OBJ-EVIDENCE", text)
        self.assertIn("WRG-ACQ-EVIDENCE", text)
        self.assertIn("SNAPSHOT DEDUP:       True", text)
        self.assertIn("EVIDENCE DEDUP:       False", text)
        database.return_value.close.assert_called_once()

    def test_profile_reports_partial_failures(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import Mock, patch
        from warrigal.acquisition.instagram import InstagramProfileIngestionResult
        from warrigal.instagram_cli import run_ingest_instagram_profile

        loader = Mock()
        loader.test_login.return_value = "australian_native_mushrooms"
        profile = Mock()
        profile.username = "australian_native_mushrooms"

        results = InstagramProfileIngestionResult()
        results.attempted = 1
        results.failures.append({
            "shortcode": "FAILED123",
            "source_url": "https://www.instagram.com/p/FAILED123/",
            "error_type": "RuntimeError",
            "message": "Controlled export failure",
        })

        output = StringIO()
        with (
            patch("instaloader.Instaloader", return_value=loader),
            patch("instaloader.Profile.own_profile", return_value=profile),
            patch("warrigal.instagram_cli.initialize_database") as database,
            patch("warrigal.instagram_cli.WarrigalRepository"),
            patch("warrigal.instagram_cli.ObjectStore"),
            patch("warrigal.instagram_cli.Node"),
            patch("warrigal.instagram_cli.Batch"),
            patch("warrigal.instagram_cli.Job"),
            patch("warrigal.instagram_cli.Collection"),
            patch("warrigal.instagram_cli.ingest_instagram_profile", return_value=results),
            redirect_stdout(output),
        ):
            result = run_ingest_instagram_profile(
                "australian_native_mushrooms",
                username="australian_native_mushrooms",
                max_posts=1,
            )

        text = output.getvalue()
        self.assertEqual(result, 1)
        self.assertIn("POSTS ATTEMPTED: 1", text)
        self.assertIn("POSTS SUCCEEDED: 0", text)
        self.assertIn("POSTS FAILED:    1", text)
        self.assertIn("https://www.instagram.com/p/FAILED123/", text)
        self.assertIn("RuntimeError: Controlled export failure", text)
        database.return_value.close.assert_called_once()

if __name__ == "__main__":
    unittest.main()
