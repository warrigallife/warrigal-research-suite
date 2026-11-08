import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from warrigal.database import initialize_database
from warrigal.models import (
    Acquisition,
    Batch,
    Collection,
    Job,
    Node,
    Object,
    Passage,
    Source,
)
from warrigal.object_store import ObjectStore
from warrigal.publish_youtube_collection import (
    format_timestamp,
    load_acquisition_status_summary,
    load_video_collection_names,
    migrate_legacy_video_folder,
    publish_youtube_collection,
    render_comments_markdown,
    render_transcript_markdown,
    video_folder_name,
    video_markdown_link,
)
from warrigal.repository import WarrigalRepository


class FormattingHelperTests(unittest.TestCase):
    def test_format_timestamp_renders_minutes_and_seconds(self):
        self.assertEqual(format_timestamp(65000), "01:05")

    def test_format_timestamp_renders_hours_when_present(self):
        self.assertEqual(format_timestamp(3665000), "01:01:05")

    def test_format_timestamp_returns_none_for_non_numeric(self):
        self.assertIsNone(format_timestamp(None))
        self.assertIsNone(format_timestamp("not-a-number"))

    def test_render_transcript_markdown_without_passages(self):
        self.assertEqual(
            render_transcript_markdown([]),
            "_No transcript was recorded for this video._",
        )

    def test_render_transcript_markdown_includes_timestamp(self):
        passages = [
            {
                "text": "Hello there.",
                "metadata_json": json.dumps({"start_ms": 1000}),
            }
        ]
        rendered = render_transcript_markdown(passages)
        self.assertIn("**[00:01]**", rendered)
        self.assertIn("Hello there.", rendered)

    def test_render_comments_markdown_without_comments(self):
        self.assertEqual(
            render_comments_markdown([]),
            "_No comments were captured for this video._",
        )

    def test_render_comments_markdown_renders_author_and_text(self):
        rendered = render_comments_markdown(
            [{"author": "Ada", "text": "Great video!", "like_count": 3}]
        )
        self.assertIn("**Ada**", rendered)
        self.assertIn("Great video!", rendered)
        self.assertIn("3 likes", rendered)


class VideoFolderNameTests(unittest.TestCase):
    def test_uses_title_and_video_id(self):
        self.assertEqual(
            video_folder_name(
                "Pi Coding Agent Setup After 2 Months", "DWWrLlM3gwQ"
            ),
            "Pi Coding Agent Setup After 2 Months [DWWrLlM3gwQ]",
        )

    def test_sanitises_unsafe_filesystem_characters(self):
        folder = video_folder_name(
            'Weird: Title/With\\Slashes "and" <brackets>|pipe', "abc123"
        )
        self.assertNotIn("/", folder.replace("[abc123]", ""))
        self.assertNotIn("\\", folder)
        self.assertNotIn(":", folder)
        self.assertNotIn('"', folder)
        self.assertNotIn("<", folder)
        self.assertNotIn(">", folder)
        self.assertNotIn("|", folder)
        self.assertTrue(folder.endswith("[abc123]"))

    def test_duplicate_titles_still_produce_distinct_folders(self):
        first = video_folder_name("Same Title", "videoOne1")
        second = video_folder_name("Same Title", "videoTwo2")
        self.assertNotEqual(first, second)
        self.assertIn("[videoOne1]", first)
        self.assertIn("[videoTwo2]", second)

    def test_blank_title_falls_back_to_bracketed_id(self):
        self.assertEqual(video_folder_name("", "onlyID12345"), "[onlyID12345]")
        self.assertEqual(video_folder_name(None, "onlyID12345"), "[onlyID12345]")
        self.assertEqual(
            video_folder_name("   ", "onlyID12345"), "[onlyID12345]"
        )
        self.assertEqual(
            video_folder_name(" . . . ", "onlyID12345"), "[onlyID12345]"
        )

    def test_unsafe_only_title_still_produces_a_valid_distinct_folder(self):
        # "///" isn't blank -- it's unsafe characters, each replaced with
        # "-", leaving a non-empty (if unusual) folder name. Never raises,
        # never collides with a different video's unsafe-only title,
        # because the video_id suffix is always distinct.
        folder = video_folder_name("///", "onlyID12345")
        self.assertTrue(folder.endswith("[onlyID12345]"))
        self.assertNotIn("/", folder.replace("[onlyID12345]", ""))

    def test_collapses_internal_whitespace_and_trims_edges(self):
        self.assertEqual(
            video_folder_name("  Too    many   spaces  ", "id0000001"),
            "Too many spaces [id0000001]",
        )

    def test_long_title_is_truncated_at_a_safe_utf8_boundary(self):
        long_title = "é" * 300  # multi-byte character throughout
        folder = video_folder_name(long_title, "id0000002")
        # Must still decode cleanly and stay well under typical filesystem
        # name-length limits once the " [id0000002]" suffix is included.
        folder.encode("utf-8")
        self.assertLessEqual(len(folder.encode("utf-8")), 255)
        self.assertTrue(folder.endswith("[id0000002]"))


class VideoMarkdownLinkTests(unittest.TestCase):
    def test_encodes_spaces_and_brackets(self):
        link = video_markdown_link(
            video_folder_name(
                "Pi Coding Agent Setup After 2 Months", "DWWrLlM3gwQ"
            )
        )
        self.assertEqual(
            link,
            "Pi%20Coding%20Agent%20Setup%20After%202%20Months%20"
            "%5BDWWrLlM3gwQ%5D/VIDEO.md",
        )
        # No literal space -- a CommonMark link destination without
        # angle brackets must not contain one, or it fails to parse as a
        # link at all.
        self.assertNotIn(" ", link)

    def test_preserves_the_path_separator(self):
        link = video_markdown_link(video_folder_name("Plain Title", "id1"))
        self.assertTrue(link.endswith("/VIDEO.md"))
        self.assertEqual(link.count("/"), 1)


class PublishYouTubeCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.connection = initialize_database(root / "warrigal.db")
        self.repository = WarrigalRepository(self.connection)
        self.object_store = ObjectStore(root / "objects")
        self.output_root = root / "COLLECTIONS" / "YOUTUBE"

        node = Node(name="Publish Test")
        self.repository.save_node(node)
        batch = Batch(node_id=node.node_id)
        self.repository.save_batch(batch)
        job = Job(name="Publish Test", node_id=node.node_id, batch_id=batch.batch_id)
        self.repository.save_job(job)
        self.node_id = node.node_id
        self.batch_id = batch.batch_id
        self.job_id = job.job_id

    def tearDown(self):
        self.connection.close()
        self.temporary.cleanup()

    def _store_transcript_video(
        self,
        *,
        video_id: str,
        title: str,
        acquired_at: datetime,
        transcript_text: str = "First passage of the transcript.",
        channel: str = "Test Channel",
    ) -> None:
        source = Source(
            source_type="youtube",
            locator=f"https://www.youtube.com/watch?v={video_id}",
            final_locator=f"https://www.youtube.com/watch?v={video_id}",
            title=title,
            metadata={
                "video_id": video_id,
                "channel": channel,
                "upload_date": "20261101",
            },
        )
        self.repository.save_source(source)

        stored = self.object_store.store_bytes(
            json.dumps({"video_id": video_id}).encode("utf-8")
        )
        obj = Object(
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type="application/json",
            original_filename=f"{video_id}.en-orig.json3",
        )
        self.repository.save_object(obj)

        acquisition = Acquisition(
            source_id=source.source_id,
            object_id=obj.object_id,
            job_id=self.job_id,
            node_id=self.node_id,
            batch_id=self.batch_id,
            method="youtube_caption_json3",
            status="success",
            acquired_at=acquired_at,
            metadata={"video_id": video_id},
        )
        self.repository.save_acquisition(acquisition)

        passage = Passage(
            object_id=obj.object_id,
            acquisition_id=acquisition.acquisition_id,
            passage_index=0,
            text=transcript_text,
            source_url=source.final_locator,
            source_title=title,
            metadata={"start_ms": 0},
        )
        self.repository.save_passage(passage)

    def _store_comments(self, *, video_id: str, comments: list[dict]) -> None:
        source = Source(
            source_type="youtube_comments",
            locator=f"https://www.youtube.com/watch?v={video_id}",
            final_locator=f"https://www.youtube.com/watch?v={video_id}",
            title=f"Comments: {video_id}",
            metadata={"video_id": video_id},
        )
        self.repository.save_source(source)

        payload = {
            "schema": "warrigal.youtube-comments.v1",
            "video": {"id": video_id},
            "comments": comments,
        }
        stored = self.object_store.store_bytes(
            json.dumps(payload).encode("utf-8")
        )
        obj = Object(
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type="application/json",
            original_filename=f"{video_id}.comments.json",
        )
        self.repository.save_object(obj)

        acquisition = Acquisition(
            source_id=source.source_id,
            object_id=obj.object_id,
            job_id=self.job_id,
            node_id=self.node_id,
            batch_id=self.batch_id,
            method="youtube_comments_ytdlp",
            status="success",
            metadata={"video_id": video_id},
        )
        self.repository.save_acquisition(acquisition)

    def _store_duplicate_acquisition_video(
        self,
        *,
        video_id: str,
        title: str,
        older_acquired_at: datetime,
        newer_acquired_at: datetime,
        transcript_text: str = "Passage from the older acquisition.",
        channel: str = "Test Channel",
    ) -> tuple[str, str]:
        """Two successful acquisitions for the same video, sharing one
        archived object -- mirroring the real duplicate found for
        GhramXiUrY4 (WRS_MASTER_STATE.md §21/§22): the OLDER acquisition's
        passages are the only ones linked; the NEWER (dedup-selected,
        published) acquisition has none of its own. Returns
        ``(older_acquisition_id, newer_acquisition_id)``.
        """
        stored = self.object_store.store_bytes(
            json.dumps({"video_id": video_id}).encode("utf-8")
        )
        obj = Object(
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type="application/json",
            original_filename=f"{video_id}.en-orig.json3",
        )
        self.repository.save_object(obj)

        def _make_acquisition(acquired_at: datetime) -> Acquisition:
            source = Source(
                source_type="youtube",
                locator=f"https://www.youtube.com/watch?v={video_id}",
                final_locator=f"https://www.youtube.com/watch?v={video_id}",
                title=title,
                metadata={
                    "video_id": video_id,
                    "channel": channel,
                    "upload_date": "20261101",
                },
            )
            self.repository.save_source(source)

            acquisition = Acquisition(
                source_id=source.source_id,
                object_id=obj.object_id,
                job_id=self.job_id,
                node_id=self.node_id,
                batch_id=self.batch_id,
                method="youtube_caption_json3",
                status="success",
                acquired_at=acquired_at,
                metadata={"video_id": video_id},
            )
            self.repository.save_acquisition(acquisition)
            return acquisition

        older_acquisition = _make_acquisition(older_acquired_at)
        passage = Passage(
            object_id=obj.object_id,
            acquisition_id=older_acquisition.acquisition_id,
            passage_index=0,
            text=transcript_text,
            source_url=f"https://www.youtube.com/watch?v={video_id}",
            source_title=title,
            metadata={"start_ms": 0},
        )
        self.repository.save_passage(passage)

        newer_acquisition = _make_acquisition(newer_acquired_at)

        return older_acquisition.acquisition_id, newer_acquisition.acquisition_id

    def test_publishes_video_with_transcript_and_comments(self):
        self._store_transcript_video(
            video_id="video001",
            title="First Video",
            acquired_at=datetime(2026, 11, 7, 23, 33, tzinfo=timezone.utc),
        )
        self._store_comments(
            video_id="video001",
            comments=[{"id": "c1", "text": "Nice work!", "author": "Viewer"}],
        )

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        self.assertEqual(result["published_videos"], 1)
        self.assertEqual(result["videos_with_transcript"], 1)
        self.assertEqual(result["videos_with_comments"], 1)
        self.assertEqual(result["missing_objects"], [])

        video_root = self.output_root / video_folder_name(
            "First Video", "video001"
        )
        video_markdown = (video_root / "VIDEO.md").read_text(encoding="utf-8")
        self.assertIn("First Video", video_markdown)
        self.assertIn(
            "https://www.youtube.com/watch?v=video001", video_markdown
        )
        self.assertIn("First passage of the transcript.", video_markdown)
        self.assertIn("Nice work!", video_markdown)

        manifest = json.loads(
            (video_root / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["video_id"], "video001")
        self.assertEqual(manifest["comment_count"], 1)
        self.assertEqual(manifest["transcript_passage_count"], 1)

        index = (self.output_root / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("First Video", index)

    def test_video_without_comments_is_published_with_absence_note(self):
        self._store_transcript_video(
            video_id="video002",
            title="Second Video",
            acquired_at=datetime(2026, 11, 7, 23, 34, tzinfo=timezone.utc),
        )

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        self.assertEqual(result["videos_with_comments"], 0)
        video_root = self.output_root / video_folder_name(
            "Second Video", "video002"
        )
        video_markdown = (video_root / "VIDEO.md").read_text(encoding="utf-8")
        self.assertIn(
            "_No comments were captured for this video._", video_markdown
        )

    def test_duplicate_acquisition_falls_back_to_sibling_with_passages(self):
        older_id, newer_id = self._store_duplicate_acquisition_video(
            video_id="video003",
            title="Duplicate Acquisition Video",
            older_acquired_at=datetime(2026, 9, 7, 8, 58, tzinfo=timezone.utc),
            newer_acquired_at=datetime(2026, 9, 7, 9, 29, tzinfo=timezone.utc),
        )

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        # One video published, not two -- the newer duplicate is still the
        # one selected to represent the video (unchanged dedup behaviour).
        self.assertEqual(result["published_videos"], 1)
        self.assertEqual(result["distinct_successful_video_count"], 1)
        self.assertEqual(result["videos_with_transcript"], 1)
        self.assertEqual(result["videos_without_transcript"], 0)
        self.assertEqual(result["missing_objects"], [])

        video_root = self.output_root / video_folder_name(
            "Duplicate Acquisition Video", "video003"
        )
        video_markdown = (video_root / "VIDEO.md").read_text(encoding="utf-8")
        self.assertIn(
            "Passage from the older acquisition.", video_markdown
        )
        self.assertIn(f"Transcript acquisition:** `{newer_id}`", video_markdown)
        self.assertIn(
            "Transcript passages retrieved from duplicate acquisition:** "
            f"`{older_id}`",
            video_markdown,
        )

        manifest = json.loads(
            (video_root / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["transcript_acquisition_id"], newer_id)
        self.assertEqual(
            manifest["transcript_passages_acquisition_id"], older_id
        )
        self.assertEqual(manifest["transcript_passage_count"], 1)

        index_entry = next(
            v for v in result["videos"] if v["video_id"] == "video003"
        )
        self.assertTrue(index_entry["has_transcript"])
        self.assertEqual(index_entry["passage_count"], 1)

    def test_non_duplicate_video_is_unaffected_by_fallback_logic(self):
        self._store_transcript_video(
            video_id="video004",
            title="Ordinary Video",
            acquired_at=datetime(2026, 11, 7, 23, 35, tzinfo=timezone.utc),
        )

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        self.assertEqual(result["videos_with_transcript"], 1)
        video_root = self.output_root / video_folder_name(
            "Ordinary Video", "video004"
        )
        video_markdown = (video_root / "VIDEO.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "Transcript passages retrieved from duplicate acquisition",
            video_markdown,
        )

    def test_limit_restricts_to_most_recently_acquired_videos(self):
        self._store_transcript_video(
            video_id="older",
            title="Older Video",
            acquired_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
        self._store_transcript_video(
            video_id="newer",
            title="Newer Video",
            acquired_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
            limit=1,
        )

        self.assertEqual(result["published_videos"], 1)
        self.assertEqual(result["videos"][0]["video_id"], "newer")

    def test_republishing_is_idempotent_and_does_not_duplicate_evidence(self):
        self._store_transcript_video(
            video_id="video003",
            title="Third Video",
            acquired_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )

        first = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )
        second = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        self.assertEqual(first["published_videos"], second["published_videos"])
        video_root = self.output_root / video_folder_name(
            "Third Video", "video003"
        )
        evidence_files = list((video_root / "evidence").iterdir())
        self.assertEqual(len(evidence_files), 1)

        # No stray old-style, bare-video_id folder left behind either.
        self.assertFalse((self.output_root / "video003").exists())

    def test_no_limit_publishes_every_successful_video_across_channels(self):
        self._store_transcript_video(
            video_id="chanA-video",
            title="Channel A Video",
            acquired_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
            channel="Channel A",
        )
        self._store_transcript_video(
            video_id="chanB-video",
            title="Channel B Video",
            acquired_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
            channel="Channel B",
        )

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        self.assertEqual(result["published_videos"], 2)
        self.assertEqual(result["distinct_successful_video_count"], 2)
        self.assertEqual(result["unpublished_successful_video_ids"], [])
        self.assertEqual(result["distinct_channel_count"], 2)
        self.assertCountEqual(
            result["distinct_channels"], ["Channel A", "Channel B"]
        )

        index = (self.output_root / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("Channel A Video", index)
        self.assertIn("Channel B Video", index)
        self.assertIn(
            "https://www.youtube.com/watch?v=chanA-video", index
        )
        self.assertIn(
            "https://www.youtube.com/watch?v=chanB-video", index
        )

    def test_limit_reports_successful_but_unpublished_video_ids(self):
        self._store_transcript_video(
            video_id="older-vid",
            title="Older Video",
            acquired_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        self._store_transcript_video(
            video_id="newer-vid",
            title="Newer Video",
            acquired_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
            limit=1,
        )

        self.assertEqual(result["published_videos"], 1)
        self.assertEqual(result["distinct_successful_video_count"], 2)
        self.assertEqual(
            result["unpublished_successful_video_ids"], ["older-vid"]
        )
        index = (self.output_root / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("older-vid", index)

    def test_load_acquisition_status_summary_distinguishes_never_acquired(
        self,
    ):
        # A successful acquisition, plus a `youtube` source whose only
        # acquisition attempt failed, must be reported separately: the
        # failed one was never successfully acquired at all and can never
        # be published, which is a different situation from a successful
        # acquisition this run's --limit simply didn't reach yet.
        self._store_transcript_video(
            video_id="success-vid",
            title="Successful Video",
            acquired_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )

        failed_source = Source(
            source_type="youtube",
            locator="https://www.youtube.com/watch?v=failed-vid",
            final_locator="https://www.youtube.com/watch?v=failed-vid",
            title="Failed Video",
            metadata={"video_id": "failed-vid"},
        )
        self.repository.save_source(failed_source)
        stored = self.object_store.store_bytes(b"{}")
        failed_object = Object(
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            mime_type="application/json",
            original_filename="failed-vid.empty.json",
        )
        self.repository.save_object(failed_object)
        failed_acquisition = Acquisition(
            source_id=failed_source.source_id,
            object_id=failed_object.object_id,
            job_id=self.job_id,
            node_id=self.node_id,
            batch_id=self.batch_id,
            method="youtube_caption_json3",
            status="failed",
            metadata={"video_id": "failed-vid"},
        )
        self.repository.save_acquisition(failed_acquisition)

        summary = load_acquisition_status_summary(self.connection)

        self.assertEqual(summary["total_youtube_sources"], 2)
        self.assertEqual(summary["youtube_sources_by_status"]["success"], 1)
        self.assertEqual(summary["youtube_sources_by_status"]["failed"], 1)

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        # The failed acquisition is never a candidate for publication at
        # all (no object to publish), so it must not appear as
        # "unpublished" alongside genuinely unpublished successes.
        self.assertEqual(result["published_videos"], 1)
        self.assertEqual(result["unpublished_successful_video_ids"], [])
        self.assertEqual(result["youtube_sources_by_status"]["failed"], 1)

    def test_missing_archived_object_is_reported_not_raised(self):
        self._store_transcript_video(
            video_id="video004",
            title="Fourth Video",
            acquired_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )

        # Point the publisher at an empty object store so the archived
        # transcript object cannot be found, simulating the object having
        # gone missing while the database record remains intact. This test
        # never mutates the real archive; it only ever reads a
        # temporary, test-local database and points to a separate,
        # deliberately-empty temporary object store.
        result = publish_youtube_collection(
            database=self.connection,
            object_store=ObjectStore(
                Path(self.temporary.name) / "nonexistent-objects"
            ),
            output_root=self.output_root,
        )

        self.assertEqual(result["published_videos"], 1)
        self.assertEqual(len(result["missing_objects"]), 1)
        self.assertEqual(
            result["missing_objects"][0]["kind"], "transcript_capture"
        )

    def test_legacy_bare_id_folder_is_migrated_not_duplicated(self):
        self._store_transcript_video(
            video_id="video005",
            title="Legacy Folder Video",
            acquired_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        )

        # Simulate a folder published by the pre-rename version of this
        # module: a bare-video_id folder containing a stray marker file
        # that must survive the migration (it stands in for a real,
        # already-published VIDEO.md/manifest.json/evidence/ tree).
        legacy_root = self.output_root / "video005"
        legacy_root.mkdir(parents=True)
        (legacy_root / "PRE_EXISTING_MARKER.txt").write_text(
            "must survive migration", encoding="utf-8"
        )

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        self.assertEqual(result["published_videos"], 1)
        new_root = self.output_root / video_folder_name(
            "Legacy Folder Video", "video005"
        )
        self.assertTrue(new_root.is_dir())
        self.assertTrue((new_root / "PRE_EXISTING_MARKER.txt").is_file())
        self.assertTrue((new_root / "VIDEO.md").is_file())
        # The old bare-ID folder must be gone, not left as a duplicate.
        self.assertFalse(legacy_root.exists())

        # Re-running again must stay stable: no legacy folder reappears,
        # no second copy of the new folder is created, content unchanged.
        second = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )
        self.assertEqual(second["published_videos"], 1)
        self.assertFalse(legacy_root.exists())
        self.assertTrue((new_root / "PRE_EXISTING_MARKER.txt").is_file())
        folders = [p for p in self.output_root.iterdir() if p.is_dir()]
        self.assertEqual(len(folders), 1)

    def test_migrate_legacy_video_folder_leaves_existing_new_folder_alone(
        self,
    ):
        # If the new-style folder already exists (e.g. the title changed
        # between two runs under the new naming scheme), the legacy
        # folder must be left in place rather than overwritten or deleted.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "vid123"
            legacy.mkdir()
            (legacy / "old.txt").write_text("old", encoding="utf-8")
            new_root = root / "New Title [vid123]"
            new_root.mkdir()
            (new_root / "new.txt").write_text("new", encoding="utf-8")

            migrate_legacy_video_folder(root, "vid123", new_root)

            self.assertTrue(legacy.is_dir())
            self.assertTrue((legacy / "old.txt").is_file())
            self.assertTrue((new_root / "new.txt").is_file())

    def test_index_includes_channel_collection_and_by_channel_section(self):
        self._store_transcript_video(
            video_id="indexed-video",
            title="Indexed Video",
            acquired_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
            channel="Reference Channel",
        )

        result = publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        index_entry = result["videos"][0]
        self.assertEqual(index_entry["channel"], "Reference Channel")
        self.assertIn("folder_name", index_entry)

        index = (self.output_root / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("| Acquired | Title | YouTube URL | Channel", index)
        self.assertIn("Reference Channel", index)
        self.assertIn("## By channel", index)
        self.assertIn("### Reference Channel (1)", index)
        relative = video_markdown_link(
            video_folder_name("Indexed Video", "indexed-video")
        )
        self.assertIn(f"[Indexed Video]({relative})", index)
        # The link destination itself must contain no literal space --
        # otherwise it fails to parse as a link at all in a strict
        # CommonMark renderer.
        self.assertNotIn(" ", relative)

    def test_collection_names_are_deduplicated_when_recorded_twice(self):
        # Reproduces the real shape found on GhramXiUrY4
        # (WRS_MASTER_STATE.md): two separate `collections` rows that
        # happen to share the same name, both linked to the same object
        # -- not the same (collection_id, object_id) pair repeated, which
        # is already INSERT OR IGNORE-guarded at the repository level.
        obj = Object(
            sha256="a" * 64,
            size_bytes=10,
            mime_type="application/json",
            original_filename="dup.json",
        )
        self.repository.save_object(obj)

        first_collection = Collection(name="Duplicate-Named Collection")
        second_collection = Collection(name="Duplicate-Named Collection")
        self.repository.save_collection(first_collection)
        self.repository.save_collection(second_collection)
        self.repository.add_object_to_collection(
            first_collection.collection_id, obj.object_id
        )
        self.repository.add_object_to_collection(
            second_collection.collection_id, obj.object_id
        )

        names = load_video_collection_names(self.connection)
        self.assertEqual(
            names[obj.object_id], ["Duplicate-Named Collection"]
        )

    def test_index_collection_column_deduplicates_repeated_name(self):
        older_id, newer_id = self._store_duplicate_acquisition_video(
            video_id="video006",
            title="Collection Dedup Video",
            older_acquired_at=datetime(2026, 9, 7, 8, 58, tzinfo=timezone.utc),
            newer_acquired_at=datetime(2026, 9, 7, 9, 29, tzinfo=timezone.utc),
        )
        # The object both acquisitions share needs its object_id to link
        # a (duplicated-name) collection to -- read it back from the
        # newer acquisition, the one actually published.
        row = self.connection.execute(
            "SELECT object_id FROM acquisitions WHERE acquisition_id = ?",
            (newer_id,),
        ).fetchone()
        object_id = row["object_id"]

        for _ in range(2):
            collection = Collection(name="Repeated Collection")
            self.repository.save_collection(collection)
            self.repository.add_object_to_collection(
                collection.collection_id, object_id
            )

        publish_youtube_collection(
            database=self.connection,
            object_store=self.object_store,
            output_root=self.output_root,
        )

        index = (self.output_root / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("Repeated Collection", index)
        self.assertNotIn(
            "Repeated Collection, Repeated Collection", index
        )


if __name__ == "__main__":
    unittest.main()
