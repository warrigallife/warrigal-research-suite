import json
import unittest
from unittest.mock import MagicMock, patch
from unittest.mock import MagicMock, patch

from warrigal.acquisition.youtube import discover_channel_videos
from warrigal.acquisition.youtube import extract_description_references
from warrigal.acquisition.youtube import extract_description_urls


class YouTubeAcquisitionTests(unittest.TestCase):

    def test_extract_description_references_preserve_positions(self):
        description = (
            "Project: https://example.com/model\n"
            "Paper: https://example.org/paper.pdf"
        )

        references = extract_description_references(description)

        self.assertEqual(len(references), 2)

        self.assertEqual(references[0].url, "https://example.com/model")
        self.assertEqual(references[0].index, 0)
        self.assertEqual(
            description[
                references[0].start_char:references[0].end_char
            ],
            references[0].url,
        )

        self.assertEqual(references[1].url, "https://example.org/paper.pdf")
        self.assertEqual(references[1].index, 1)
        self.assertEqual(
            description[
                references[1].start_char:references[1].end_char
            ],
            references[1].url,
        )

        self.assertEqual(extract_description_references(None), [])

    def test_extract_description_urls_preserves_source_order(self):
        description = """Project notes:
https://example.com/paper.pdf
More information: https://example.org/research?id=42
Support: https://www.patreon.com/example
"""

        urls = extract_description_urls(description)

        self.assertEqual(
            urls,
            [
                "https://example.com/paper.pdf",
                "https://example.org/research?id=42",
                "https://www.patreon.com/example",
            ],
        )

        self.assertEqual(extract_description_urls(None), [])
        self.assertEqual(extract_description_urls("No links here."), [])

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


    def test_transcript_units_convert_to_passages(self):
        from warrigal.acquisition.youtube import (
            YouTubeTranscriptUnit,
            transcript_units_to_passages,
        )

        units = [
            YouTubeTranscriptUnit(
                start_ms=1000,
                end_ms=2500,
                text="First useful sentence.",
                source_segment_start=0,
                source_start_char=0,
                source_segment_end=1,
                source_end_char=8,
            ),
            YouTubeTranscriptUnit(
                start_ms=2500,
                end_ms=4000,
                text="Second useful sentence.",
                source_segment_start=1,
                source_start_char=9,
                source_segment_end=2,
                source_end_char=12,
            ),
        ]

        passages = transcript_units_to_passages(
            units=units,
            object_id="WRG-OBJ-TEST",
            acquisition_id="WRG-ACQ-TEST",
            source_url="https://www.youtube.com/watch?v=test",
            source_title="Test Video",
        )

        self.assertEqual(len(passages), 2)

        self.assertEqual(passages[0].object_id, "WRG-OBJ-TEST")
        self.assertEqual(passages[0].acquisition_id, "WRG-ACQ-TEST")
        self.assertEqual(passages[0].passage_index, 0)
        self.assertEqual(passages[0].text, "First useful sentence.")
        self.assertEqual(
            passages[0].source_url,
            "https://www.youtube.com/watch?v=test",
        )
        self.assertEqual(passages[0].source_title, "Test Video")
        self.assertEqual(
            passages[0].metadata,
            {
                "start_ms": 1000,
                "end_ms": 2500,
                "source_segment_start": 0,
                "source_start_char": 0,
                "source_segment_end": 1,
                "source_end_char": 8,
            },
        )

        self.assertEqual(passages[1].passage_index, 1)
        self.assertEqual(passages[1].text, "Second useful sentence.")


    def test_acquire_json3_transcript_returns_caption_bytes(self):
        from warrigal.acquisition.youtube import acquire_json3_transcript

        caption_bytes = b'{"events": []}'

        first_ydl = MagicMock()
        first_ydl.extract_info.return_value = {
            "automatic_captions": {
                "en-orig": [
                    {
                        "ext": "vtt",
                        "url": "https://example.test/caption.vtt",
                    },
                    {
                        "ext": "json3",
                        "url": "https://example.test/caption.json3",
                    },
                ]
            }
        }

        response = MagicMock()
        response.read.return_value = caption_bytes

        second_ydl = MagicMock()
        second_ydl.urlopen.return_value = response

        first_context = MagicMock()
        first_context.__enter__.return_value = first_ydl

        second_context = MagicMock()
        second_context.__enter__.return_value = second_ydl

        with patch(
            "warrigal.acquisition.youtube.yt_dlp.YoutubeDL",
            side_effect=[first_context, second_context],
        ):
            data = acquire_json3_transcript(
                "https://www.youtube.com/watch?v=test"
            )

        self.assertEqual(data, caption_bytes)
        first_ydl.extract_info.assert_called_once_with(
            "https://www.youtube.com/watch?v=test",
            download=False,
        )
        second_ydl.urlopen.assert_called_once()



    def test_build_video_transcript_passages_connects_transcript_pipeline(self):
        from warrigal.acquisition.youtube import build_video_transcript_passages

        caption_data = (
            b'{"events":['
            b'{"tStartMs":1000,"dDurationMs":1000,'
            b'"segs":[{"utf8":"First sentence. Second"}]},'
            b'{"tStartMs":2000,"dDurationMs":1000,'
            b'"segs":[{"utf8":" sentence?"}]}'
            b']}'
        )

        with patch(
            "warrigal.acquisition.youtube.acquire_json3_transcript",
            return_value=caption_data,
        ) as acquire:
            passages = build_video_transcript_passages(
                video_url="https://www.youtube.com/watch?v=test",
                object_id="WRG-OBJ-PIPELINE",
                acquisition_id="WRG-ACQ-PIPELINE",
                source_title="Pipeline Test",
            )

        acquire.assert_called_once_with(
            "https://www.youtube.com/watch?v=test",
            language="en-orig",
        )

        self.assertEqual(len(passages), 2)
        self.assertEqual(passages[0].text, "First sentence.")
        self.assertEqual(passages[1].text, "Second sentence?")

        self.assertEqual(passages[0].object_id, "WRG-OBJ-PIPELINE")
        self.assertEqual(passages[0].acquisition_id, "WRG-ACQ-PIPELINE")
        self.assertEqual(passages[0].passage_index, 0)
        self.assertEqual(passages[1].passage_index, 1)

        self.assertEqual(
            passages[0].metadata,
            {
                "start_ms": 1000,
                "end_ms": 2000,
                "source_segment_start": 0,
                "source_start_char": 0,
                "source_segment_end": 0,
                "source_end_char": 15,
            },
        )

        self.assertEqual(
            passages[1].metadata,
            {
                "start_ms": 1000,
                "end_ms": 3000,
                "source_segment_start": 0,
                "source_start_char": 16,
                "source_segment_end": 1,
                "source_end_char": 9,
            },
        )


    def test_ingest_video_transcript_persists_raw_evidence_and_passages(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from warrigal.acquisition.youtube import (
            YouTubeVideoMetadata,
            ingest_video_transcript,
        )
        from warrigal.database import initialize_database
        from warrigal.models import Batch, Job, Node
        from warrigal.object_store import ObjectStore
        from warrigal.repository import WarrigalRepository

        caption_data = (
            b'{"events":['
            b'{"tStartMs":1000,"dDurationMs":1000,'
            b'"segs":[{"utf8":"First sentence. Second"}]},'
            b'{"tStartMs":2000,"dDurationMs":1000,'
            b'"segs":[{"utf8":" sentence?"}]}'
            b']}'
        )

        metadata = YouTubeVideoMetadata(
            video_id="test-video",
            title="Persistent YouTube Test",
            channel="Test Channel",
            channel_id="test-channel",
            upload_date="20260906",
            duration=3,
            url="https://www.youtube.com/watch?v=test-video",
            description=(
                "Test description\n"
                "Paper: https://example.com/paper.pdf\n"
                "Support: https://www.patreon.com/example"
            ),
        )

        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)

            connection = initialize_database(
                temporary_root / "warrigal.db"
            )
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(temporary_root / "objects")

            node = Node(name="YouTube Test")
            repository.save_node(node)

            batch = Batch(
                node_id=node.node_id,
                label="YouTube Test Batch",
            )
            repository.save_batch(batch)

            job = Job(
                name="YouTube Test Job",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            with patch(
                "warrigal.acquisition.youtube.extract_video_metadata",
                return_value=metadata,
            ), patch(
                "warrigal.acquisition.youtube.acquire_json3_transcript",
                return_value=caption_data,
            ):
                first = ingest_video_transcript(
                    metadata.url,
                    repository=repository,
                    object_store=object_store,
                    job_id=job.job_id,
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                )

                second = ingest_video_transcript(
                    metadata.url,
                    repository=repository,
                    object_store=object_store,
                    job_id=job.job_id,
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                )

            self.assertEqual(first.video_id, "test-video")
            self.assertEqual(first.passage_count, 2)
            self.assertFalse(first.deduplicated)

            self.assertEqual(second.object_id, first.object_id)
            self.assertEqual(second.passage_count, 0)
            self.assertTrue(second.deduplicated)

            self.assertNotEqual(
                first.acquisition_id,
                second.acquisition_id,
            )

            self.assertEqual(
                object_store.read_bytes(first.sha256),
                caption_data,
            )

            source_row = connection.execute(
                """
                SELECT metadata_json
                FROM sources
                WHERE locator = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (metadata.url,),
            ).fetchone()

            self.assertIsNotNone(source_row)

            source_metadata = json.loads(source_row["metadata_json"])

            self.assertEqual(
                source_metadata["description"],
                metadata.description,
            )
            self.assertEqual(
                source_metadata["description_urls"],
                [
                    "https://example.com/paper.pdf",
                    "https://www.patreon.com/example",
                ],
            )

            description = metadata.description
            self.assertIsNotNone(description)

            expected_urls = [
                "https://example.com/paper.pdf",
                "https://www.patreon.com/example",
            ]

            references = source_metadata["description_references"]

            self.assertEqual(len(references), 2)

            for index, reference in enumerate(references):
                self.assertEqual(reference["index"], index)
                self.assertEqual(reference["url"], expected_urls[index])
                self.assertEqual(
                    description[
                        reference["start_char"]:reference["end_char"]
                    ],
                    reference["url"],
                )

            passages = [
                passage
                for passage in repository.list_passages()
                if passage["object_id"] == first.object_id
            ]

            self.assertEqual(len(passages), 2)
            self.assertEqual(passages[0]["text"], "First sentence.")
            self.assertEqual(passages[1]["text"], "Second sentence?")

            self.assertEqual(
                json.loads(passages[1]["metadata_json"]),
                {
                    "start_ms": 1000,
                    "end_ms": 3000,
                    "source_segment_start": 0,
                    "source_start_char": 16,
                    "source_segment_end": 1,
                    "source_end_char": 9,
                },
            )

            acquisition_count = connection.execute(
                "SELECT COUNT(*) FROM acquisitions"
            ).fetchone()[0]

            object_count = connection.execute(
                "SELECT COUNT(*) FROM objects"
            ).fetchone()[0]

            passage_count = connection.execute(
                "SELECT COUNT(*) FROM passages"
            ).fetchone()[0]

            self.assertEqual(acquisition_count, 2)
            self.assertEqual(object_count, 1)
            self.assertEqual(passage_count, 2)


if __name__ == "__main__":
    unittest.main()
