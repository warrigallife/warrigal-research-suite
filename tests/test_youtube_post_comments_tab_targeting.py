"""Execute the collector's dedicated-tab identity logic via real osascript.

These exercise the pure, Brave-independent AppleScript handlers that decide
whether the collection tab is still on the expected post -- the actual
decision logic behind "stop with an explicit error if it navigates
elsewhere" -- without touching a running browser.
"""
import shutil
import subprocess
import unittest

from warrigal.acquisition.youtube_post_comments import _EXTRACT_POST_ID_APPLESCRIPT

_RUN_WRAPPER = _EXTRACT_POST_ID_APPLESCRIPT + r'''
on run argv
    set mode to item 1 of argv
    if mode is "extract" then
        return my extractPostId(item 2 of argv)
    else
        return (my urlMatchesExpectedPost(item 2 of argv, item 3 of argv)) as string
    end if
end run
'''


@unittest.skipUnless(shutil.which("osascript"), "osascript is required (macOS only)")
class DedicatedTabTargetingTests(unittest.TestCase):
    def _extract(self, url: str) -> str:
        result = subprocess.run(
            ["osascript", "-", "extract", url],
            input=_RUN_WRAPPER,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()

    def _matches(self, url: str, expected_post_id: str) -> bool:
        result = subprocess.run(
            ["osascript", "-", "match", url, expected_post_id],
            input=_RUN_WRAPPER,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip() == "true"

    def test_extracts_post_id_with_trailing_slash(self):
        self.assertEqual(
            self._extract("https://www.youtube.com/post/Ugkx3yv-ABC/"),
            "Ugkx3yv-ABC",
        )

    def test_extracts_post_id_with_query_string(self):
        self.assertEqual(
            self._extract("https://www.youtube.com/post/Ugkx-W8-XYZ?foo=bar"),
            "Ugkx-W8-XYZ",
        )

    def test_extracts_post_id_with_fragment(self):
        self.assertEqual(
            self._extract("https://www.youtube.com/post/Ugkx-W8-XYZ#reply"),
            "Ugkx-W8-XYZ",
        )

    def test_matches_same_post(self):
        self.assertTrue(
            self._matches("https://www.youtube.com/post/ABC", "ABC")
        )

    def test_rejects_different_post(self):
        self.assertFalse(
            self._matches("https://www.youtube.com/post/XYZ", "ABC")
        )

    def test_rejects_channel_feed_url(self):
        # The channel's own /posts feed is a real tab the collector's own
        # feed-refresh step may leave behind -- it must never be mistaken
        # for a dedicated single-post collection tab.
        self.assertFalse(
            self._matches("https://www.youtube.com/@TFJ7/posts", "ABC")
        )

    def test_rejects_unrelated_watch_url(self):
        # A personal video the user is watching also "contains youtube.com"
        # and must never be treated as the target post.
        self.assertFalse(
            self._matches("https://www.youtube.com/watch?v=someVideoId", "ABC")
        )


if __name__ == "__main__":
    unittest.main()
