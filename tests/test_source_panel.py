import unittest
from pathlib import Path
from unittest.mock import patch

from warrigal.source_panel import (
    build_instagram_commands,
    build_website_commands,
    instagram_paths,
    safe_name,
)


class SourcePanelTests(unittest.TestCase):
    def test_safe_name_accepts_instagram_username_and_url(self):
        self.assertEqual(safe_name("@ScienceWithJahir"), "sciencewithjahir")
        self.assertEqual(
            safe_name("https://www.instagram.com/ScienceWithJahir/"),
            "sciencewithjahir",
        )

    def test_instagram_paths_are_external_and_deterministic(self):
        profile, inventory, checkpoint = instagram_paths("sciencewithjahir")
        self.assertEqual(profile, "sciencewithjahir")
        self.assertEqual(inventory.name, "sciencewithjahir-instagram-inventory.json")
        self.assertEqual(checkpoint.name, "sciencewithjahir-instagram.checkpoint.json")
        self.assertIn("INFORMATION_ARCHIVE", str(inventory))

    def test_complete_instagram_workflow_has_four_steps(self):
        commands = build_instagram_commands("sciencewithjahir", "Complete workflow")
        self.assertEqual(len(commands), 4)
        self.assertIn("warrigal.instagram_profile_inventory", commands[0][1])
        self.assertIn("warrigal.instagram_browser_campaign", commands[1][1])
        self.assertIn("warrigal.instagram_browser_campaign", commands[2][1])
        self.assertIn("warrigal.publish_instagram_collection", commands[3][1])

    def test_website_without_scheme_gets_https(self):
        command = build_website_commands("example.com", "Crawl website")[0][1]
        self.assertEqual(command[-1], "https://example.com")


if __name__ == "__main__":
    unittest.main()
