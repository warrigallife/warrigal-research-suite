import unittest
from unittest.mock import MagicMock, patch

from warrigal.acquisition.youtube import discover_channel_videos


class YouTubeAcquisitionTests(unittest.TestCase):
    @patch("warrigal.acquisition.youtube.yt_dlp.YoutubeDL")
    def test_discover_channel_videos_returns_structured_videos(self, youtube_dl):
        ydl = MagicMock()
        youtube_dl.return_value.__enter__.return_value = ydl
        ydl.extract_info.return_value = {
            "entries": [
                {
                    "id": "video001",
                    "title": "First Test Video",
                },
                {
                    "id": "video002",
                    "title": "Second Test Video",
                },
            ]
        }

        videos = discover_channel_videos(
            "https://www.youtube.com/@example/videos",
            max_videos=2,
        )

        self.assertEqual(len(videos), 2)

        self.assertEqual(videos[0].video_id, "video001")
        self.assertEqual(videos[0].title, "First Test Video")
        self.assertEqual(
            videos[0].url,
            "https://www.youtube.com/watch?v=video001",
        )

        self.assertEqual(videos[1].video_id, "video002")
        self.assertEqual(videos[1].title, "Second Test Video")
        self.assertEqual(
            videos[1].url,
            "https://www.youtube.com/watch?v=video002",
        )

        ydl.extract_info.assert_called_once_with(
            "https://www.youtube.com/@example/videos",
            download=False,
        )


if __name__ == "__main__":
    unittest.main()
