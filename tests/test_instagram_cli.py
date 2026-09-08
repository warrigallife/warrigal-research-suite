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


if __name__ == "__main__":
    unittest.main()
