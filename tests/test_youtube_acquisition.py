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


    def test_parse_json3_transcript_preserves_caption_events(self):
        import json

        from warrigal.acquisition.youtube import parse_json3_transcript

        payload = {
            "events": [
                {
                    "tStartMs": 1000,
                    "dDurationMs": 2500,
                    "segs": [
                        {"utf8": "First "},
                        {"utf8": "caption"},
                    ],
                },
                {
                    "tStartMs": 3000,
                    "segs": [
                        {"utf8": "Second caption"},
                    ],
                },
                {
                    "tStartMs": 4000,
                    "dDurationMs": 1000,
                    "segs": [],
                },
                {
                    "dDurationMs": 1000,
                    "segs": [
                        {"utf8": "Missing timestamp"},
                    ],
                },
            ]
        }

        segments = parse_json3_transcript(
            json.dumps(payload).encode("utf-8")
        )

        self.assertEqual(len(segments), 2)

        self.assertEqual(segments[0].start_ms, 1000)
        self.assertEqual(segments[0].duration_ms, 2500)
        self.assertEqual(segments[0].text, "First caption")

        self.assertEqual(segments[1].start_ms, 3000)
        self.assertIsNone(segments[1].duration_ms)
        self.assertEqual(segments[1].text, "Second caption")

    def test_build_transcript_unit_preserves_source_range(self):
        from warrigal.acquisition.youtube import (
            YouTubeTranscriptSegment,
            build_transcript_unit,
        )

        segments = [
            YouTubeTranscriptSegment(
                start_ms=1000,
                duration_ms=2500,
                text="First part of",
            ),
            YouTubeTranscriptSegment(
                start_ms=2500,
                duration_ms=3000,
                text="the sentence.",
            ),
            YouTubeTranscriptSegment(
                start_ms=5000,
                duration_ms=2000,
                text="I have uh I have uh",
            ),
            YouTubeTranscriptSegment(
                start_ms=6500,
                duration_ms=1500,
                text="finished.",
            ),
        ]

        original_text = [segment.text for segment in segments]

        unit = build_transcript_unit(
            segments,
            0,
            3,
        )

        self.assertEqual(unit.start_ms, 1000)
        self.assertEqual(unit.end_ms, 8000)
        self.assertEqual(unit.source_segment_start, 0)
        self.assertEqual(unit.source_start_char, 0)
        self.assertEqual(unit.source_segment_end, 3)
        self.assertEqual(unit.source_end_char, len(segments[3].text))
        self.assertEqual(
            unit.text,
            "First part of the sentence. "
            "I have uh I have uh finished.",
        )

        self.assertEqual(
            [segment.text for segment in segments],
            original_text,
        )

    def test_build_transcript_sentences_handles_internal_and_cross_segment_boundaries(self):
        from warrigal.acquisition.youtube import (
            YouTubeTranscriptSegment,
            build_transcript_sentences,
        )

        segments = [
            YouTubeTranscriptSegment(
                start_ms=1000,
                duration_ms=3000,
                text="First sentence. Second",
            ),
            YouTubeTranscriptSegment(
                start_ms=3000,
                duration_ms=3000,
                text="sentence? Third one! Final",
            ),
            YouTubeTranscriptSegment(
                start_ms=5000,
                duration_ms=2500,
                text="unfinished thought",
            ),
        ]

        original_text = [segment.text for segment in segments]

        units = build_transcript_sentences(segments)

        self.assertEqual(
            [unit.text for unit in units],
            [
                "First sentence.",
                "Second sentence?",
                "Third one!",
                "Final unfinished thought",
            ],
        )

        self.assertEqual(
            (
                units[0].source_segment_start,
                units[0].source_start_char,
                units[0].source_segment_end,
                units[0].source_end_char,
            ),
            (0, 0, 0, 15),
        )

        self.assertEqual(
            (
                units[1].source_segment_start,
                units[1].source_start_char,
                units[1].source_segment_end,
                units[1].source_end_char,
            ),
            (0, 16, 1, 9),
        )

        self.assertEqual(
            (
                units[2].source_segment_start,
                units[2].source_start_char,
                units[2].source_segment_end,
                units[2].source_end_char,
            ),
            (1, 10, 1, 20),
        )

        self.assertEqual(
            (
                units[3].source_segment_start,
                units[3].source_start_char,
                units[3].source_segment_end,
                units[3].source_end_char,
            ),
            (1, 21, 2, len(segments[2].text)),
        )

        self.assertEqual(
            [segment.text for segment in segments],
            original_text,
        )

if __name__ == "__main__":
    unittest.main()
