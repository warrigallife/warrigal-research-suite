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


    @patch("warrigal.acquisition.youtube.yt_dlp.YoutubeDL")
    def test_extract_video_metadata_returns_structured_metadata(self, youtube_dl):
        ydl = MagicMock()
        youtube_dl.return_value.__enter__.return_value = ydl
        ydl.extract_info.return_value = {
            "id": "video001",
            "title": "Test Video",
            "channel": "Test Channel",
            "channel_id": "channel001",
            "upload_date": "20250904",
            "duration": 467,
            "webpage_url": "https://www.youtube.com/watch?v=video001",
            "description": "Test description.",
        }

        from warrigal.acquisition.youtube import extract_video_metadata

        metadata = extract_video_metadata(
            "https://www.youtube.com/watch?v=video001"
        )

        self.assertEqual(metadata.video_id, "video001")
        self.assertEqual(metadata.title, "Test Video")
        self.assertEqual(metadata.channel, "Test Channel")
        self.assertEqual(metadata.channel_id, "channel001")
        self.assertEqual(metadata.upload_date, "20250904")
        self.assertEqual(metadata.duration, 467)
        self.assertEqual(
            metadata.url,
            "https://www.youtube.com/watch?v=video001",
        )
        self.assertEqual(metadata.description, "Test description.")

        ydl.extract_info.assert_called_once_with(
            "https://www.youtube.com/watch?v=video001",
            download=False,
        )


if __name__ == "__main__":
    unittest.main()
