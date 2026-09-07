import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from warrigal.acquisition.instagram import (
    profile_from_instaloader,
    post_from_instaloader,
)


class InstagramAcquisitionTests(unittest.TestCase):
    def test_profile_metadata_normalization(self):
        raw = SimpleNamespace(
            username="australian_native_mushrooms",
            userid=12345,
            full_name="Australian Native Mushrooms",
            biography="Native fungi research",
            is_private=False,
            mediacount=42,
        )

        result = profile_from_instaloader(raw)

        self.assertEqual(result.username, raw.username)
        self.assertEqual(result.user_id, 12345)
        self.assertEqual(result.post_count, 42)
        self.assertFalse(result.is_private)

    def test_post_metadata_normalization(self):
        date = datetime(2026, 1, 2, tzinfo=timezone.utc)
        raw = SimpleNamespace(
            shortcode="ABC123",
            date_utc=date,
            typename="GraphImage",
            caption="Ganoderma australe",
        )

        result = post_from_instaloader(raw)

        self.assertEqual(result.shortcode, "ABC123")
        self.assertEqual(result.url, "https://www.instagram.com/p/ABC123/")
        self.assertEqual(result.date_utc, date)
        self.assertEqual(result.caption, "Ganoderma australe")

    def test_missing_caption_becomes_empty_string(self):
        raw = SimpleNamespace(
            shortcode="XYZ789",
            date_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
            typename="GraphVideo",
            caption=None,
        )

        self.assertEqual(post_from_instaloader(raw).caption, "")


    def test_bounded_post_discovery(self):
        from warrigal.acquisition.instagram import discover_profile_posts

        date = datetime(2026, 1, 2, tzinfo=timezone.utc)
        raw_posts = [
            SimpleNamespace(
                shortcode=f"POST{i}",
                date_utc=date,
                typename="GraphImage",
                caption=f"Caption {i}",
            )
            for i in range(5)
        ]

        profile = SimpleNamespace(get_posts=lambda: iter(raw_posts))
        results = discover_profile_posts(profile, max_posts=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(
            [post.shortcode for post in results],
            ["POST0", "POST1"],
        )

    def test_zero_post_limit_does_not_request_posts(self):
        from warrigal.acquisition.instagram import discover_profile_posts

        def forbidden():
            raise AssertionError("get_posts should not be called")

        profile = SimpleNamespace(get_posts=forbidden)
        self.assertEqual(discover_profile_posts(profile, max_posts=0), [])

    def test_negative_post_limit_is_rejected(self):
        from warrigal.acquisition.instagram import discover_profile_posts

        with self.assertRaises(ValueError):
            discover_profile_posts(object(), max_posts=-1)


if __name__ == "__main__":
    unittest.main()
