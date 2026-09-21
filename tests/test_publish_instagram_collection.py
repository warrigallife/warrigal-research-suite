import os
import tempfile
import unittest
from pathlib import Path

from warrigal.publish_instagram_collection import (
    materialize_object,
    nested_username,
    profile_from_url,
    safe_name,
    shortcode_from_url,
    unique_destination,
)


class InstagramPublicationTests(unittest.TestCase):
    def test_profile_and_shortcode_from_qualified_reel_url(self):
        url = (
            "https://www.instagram.com/eeanimation/"
            "reel/DdAhgqYR_g8/"
        )
        self.assertEqual(profile_from_url(url), "eeanimation")
        self.assertEqual(shortcode_from_url(url), "DdAhgqYR_g8")

    def test_canonical_post_url_has_no_profile(self):
        url = "https://www.instagram.com/p/Dc2wI1Cvwwj/"
        self.assertIsNone(profile_from_url(url))
        self.assertEqual(shortcode_from_url(url), "Dc2wI1Cvwwj")

    def test_nested_username_prefers_archived_username(self):
        payload = {
            "post": {
                "owner": {
                    "owner_username": "example_profile"
                }
            }
        }
        self.assertEqual(
            nested_username(payload),
            "example_profile",
        )

    def test_safe_name_removes_path_characters(self):
        self.assertEqual(
            safe_name("../../bad profile/name"),
            "bad-profile-name",
        )

    def test_safe_name_preserves_instagram_shortcode_endings(self):
        self.assertEqual(
            safe_name("DcWB1uXEo1-"),
            "DcWB1uXEo1-",
        )
        self.assertEqual(
            safe_name("DcWVWHYn4T_"),
            "DcWVWHYn4T_",
        )

    def test_unique_destination_preserves_both_collisions(self):
        used = set()
        root = Path("/tmp/output")

        first = unique_destination(root, "post.json", used)
        second = unique_destination(root, "post.json", used)

        self.assertEqual(first.name, "post.json")
        self.assertEqual(second.name, "post-2.json")

    def test_materialize_object_is_readable_and_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "archive-object"
            destination = root / "published" / "image.jpg"
            source.write_bytes(b"immutable evidence")

            first = materialize_object(source, destination)
            second = materialize_object(source, destination)

            self.assertIn(first, {"hardlink", "copy"})
            self.assertEqual(second, "existing")
            self.assertEqual(
                destination.read_bytes(),
                b"immutable evidence",
            )

            if first == "hardlink":
                self.assertTrue(os.path.samefile(source, destination))


if __name__ == "__main__":
    unittest.main()
