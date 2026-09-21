import json
import tempfile
import unittest
from pathlib import Path

from warrigal.instagram_profile_inventory import (
    discover_profile_inventory,
    normalize_post_url,
    normalize_profile_url,
    parse_browser_snapshots,
)


class InstagramProfileInventoryTests(unittest.TestCase):
    def test_normalizes_profile(self):
        url, username = normalize_profile_url(
            "https://www.instagram.com/chemist_ryislove/"
        )
        self.assertEqual(username, "chemist_ryislove")
        self.assertEqual(
            url,
            "https://www.instagram.com/chemist_ryislove/",
        )

    def test_rejects_post_as_profile(self):
        with self.assertRaises(ValueError):
            normalize_profile_url(
                "https://www.instagram.com/p/ABC123/"
            )

    def test_normalizes_discovered_post_to_profile_url(self):
        result = normalize_post_url(
            "https://www.instagram.com/p/ABC_123/?utm_source=x",
            profile_username="chemist_ryislove",
        )
        self.assertEqual(
            result,
            (
                "https://www.instagram.com/"
                "chemist_ryislove/p/ABC_123/"
            ),
        )

    def test_merges_scroll_snapshots_without_duplicates(self):
        output = "\n".join(
            [
                json.dumps([
                    "https://www.instagram.com/p/ONE/",
                    "https://www.instagram.com/reel/TWO/",
                ]),
                json.dumps([
                    "https://www.instagram.com/p/ONE/",
                    "https://www.instagram.com/p/THREE/",
                ]),
            ]
        )

        result = parse_browser_snapshots(
            output,
            profile_username="chemist_ryislove",
        )

        self.assertEqual(
            result,
            [
                (
                    "https://www.instagram.com/"
                    "chemist_ryislove/p/ONE/"
                ),
                (
                    "https://www.instagram.com/"
                    "chemist_ryislove/reel/TWO/"
                ),
                (
                    "https://www.instagram.com/"
                    "chemist_ryislove/p/THREE/"
                ),
            ],
        )

    def test_existing_inventory_is_merged(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inventory.json"
            output.write_text(
                json.dumps({
                    "post_urls": [
                        (
                            "https://www.instagram.com/"
                            "chemist_ryislove/p/OLD/"
                        )
                    ]
                }),
                encoding="utf-8",
            )

            def runner(
                profile_url,
                *,
                max_scrolls,
                delay,
                stable_rounds,
            ):
                return json.dumps([
                    "https://www.instagram.com/p/NEW/"
                ])

            result = discover_profile_inventory(
                "chemist_ryislove",
                output=output,
                runner=runner,
            )

            self.assertEqual(result["post_count"], 2)
            self.assertEqual(
                json.loads(
                    output.read_text(encoding="utf-8")
                )["post_count"],
                2,
            )


if __name__ == "__main__":
    unittest.main()
