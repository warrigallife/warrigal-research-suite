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


    def test_instagram_post_persistence(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from warrigal.acquisition.instagram import (
            InstagramPost,
            persist_instagram_post,
        )
        from warrigal.database import initialize_database
        from warrigal.models import Batch, Job, Node
        from warrigal.object_store import ObjectStore
        from warrigal.repository import WarrigalRepository

        post = InstagramPost(
            shortcode="TEST123",
            url="https://www.instagram.com/p/TEST123/",
            date_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
            typename="GraphImage",
            caption="Ganoderma australe",
        )

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            connection = initialize_database(root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(root / "objects")

            node = Node(name="Instagram Test")
            repository.save_node(node)

            batch = Batch(
                node_id=node.node_id,
                label="Instagram Test Batch",
            )
            repository.save_batch(batch)

            job = Job(
                name="Instagram Test Job",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            kwargs = {
                "repository": repository,
                "object_store": object_store,
                "job_id": job.job_id,
                "node_id": node.node_id,
                "batch_id": batch.batch_id,
            }

            first = persist_instagram_post(post, **kwargs)
            second = persist_instagram_post(post, **kwargs)

            self.assertFalse(first.deduplicated)
            self.assertTrue(second.deduplicated)
            self.assertEqual(first.object_id, second.object_id)
            self.assertEqual(first.sha256, second.sha256)
            self.assertNotEqual(
                first.acquisition_id,
                second.acquisition_id,
            )

            data = object_store.read_bytes(first.sha256)
            payload = json.loads(data)

            self.assertEqual(
                payload["schema"],
                "warrigal.instagram.post.v1",
            )
            self.assertEqual(
                payload["post"]["caption"],
                "Ganoderma australe",
            )
            self.assertEqual(
                payload["post"]["date_utc"],
                "2026-01-02T00:00:00+00:00",
            )

            source_rows = connection.execute(
                """
                SELECT source_id, metadata_json
                FROM sources
                WHERE locator = ?
                """,
                (post.url,),
            ).fetchall()

            self.assertEqual(len(source_rows), 2)

            for row in source_rows:
                metadata = json.loads(row["metadata_json"])
                self.assertEqual(
                    metadata["evidence_kind"],
                    "normalized_metadata_snapshot",
                )

            acquisition_rows = connection.execute(
                """
                SELECT acquisition_id, object_id, source_id
                FROM acquisitions
                WHERE object_id = ?
                """,
                (first.object_id,),
            ).fetchall()

            self.assertEqual(len(acquisition_rows), 2)
            self.assertEqual(
                {row["acquisition_id"] for row in acquisition_rows},
                {first.acquisition_id, second.acquisition_id},
            )
            self.assertEqual(
                {row["source_id"] for row in acquisition_rows},
                {row["source_id"] for row in source_rows},
            )

            passage_rows = connection.execute(
                """
                SELECT object_id, acquisition_id, text, metadata_json
                FROM passages
                WHERE object_id = ?
                """,
                (first.object_id,),
            ).fetchall()

            self.assertEqual(len(passage_rows), 1)
            passage = passage_rows[0]
            self.assertEqual(passage["text"], post.caption)
            self.assertEqual(
                passage["acquisition_id"],
                first.acquisition_id,
            )

            passage_metadata = json.loads(passage["metadata_json"])
            self.assertEqual(
                passage_metadata["source_start_char"], 0
            )
            self.assertEqual(
                passage_metadata["source_end_char"], len(post.caption)
            )

            connection.close()


    def test_instagram_caption_passages(self):
        from warrigal.acquisition.instagram import (
            InstagramPost,
            instagram_caption_to_passages,
        )

        caption = "  Ganoderma australe\\nNative fungi research.  "
        post = InstagramPost(
            shortcode="CAPTION123",
            url="https://www.instagram.com/p/CAPTION123/",
            date_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
            typename="GraphImage",
            caption=caption,
        )

        passages = instagram_caption_to_passages(
            post,
            object_id="WRG-OBJ-TEST",
            acquisition_id="WRG-ACQ-TEST",
        )

        self.assertEqual(len(passages), 1)
        passage = passages[0]
        self.assertEqual(passage.text, caption)
        self.assertEqual(passage.source_url, post.url)
        self.assertEqual(passage.metadata["source_field"], "post.caption")
        self.assertEqual(passage.metadata["source_start_char"], 0)
        self.assertEqual(passage.metadata["source_end_char"], len(caption))
        self.assertEqual(
            caption[
                passage.metadata["source_start_char"]:
                passage.metadata["source_end_char"]
            ],
            passage.text,
        )

    def test_blank_instagram_caption_produces_no_passages(self):
        from warrigal.acquisition.instagram import (
            InstagramPost,
            instagram_caption_to_passages,
        )

        post = InstagramPost(
            shortcode="BLANK123",
            url="https://www.instagram.com/p/BLANK123/",
            date_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
            typename="GraphImage",
            caption="  \n  ",
        )

        self.assertEqual(
            instagram_caption_to_passages(
                post,
                object_id="WRG-OBJ-TEST",
                acquisition_id="WRG-ACQ-TEST",
            ),
            [],
        )


    def test_instagram_evidence_file_persistence(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from warrigal.acquisition.instagram import (
            persist_instagram_evidence_file,
        )
        from warrigal.database import initialize_database
        from warrigal.models import Batch, Job, Node
        from warrigal.object_store import ObjectStore
        from warrigal.repository import WarrigalRepository

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            connection = initialize_database(root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(root / "objects")

            node = Node(name="Instagram Evidence Test")
            repository.save_node(node)
            batch = Batch(
                node_id=node.node_id,
                label="Instagram Evidence Batch",
            )
            repository.save_batch(batch)
            job = Job(
                name="Instagram Evidence Job",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            evidence = root / "TEST123.json"
            original = b'{"raw":"preserved exactly"}'
            evidence.write_bytes(original)

            kwargs = {
                "source_url": "https://www.instagram.com/p/TEST123/",
                "evidence_kind": "instaloader_metadata",
                "repository": repository,
                "object_store": object_store,
                "job_id": job.job_id,
                "node_id": node.node_id,
                "batch_id": batch.batch_id,
            }

            first = persist_instagram_evidence_file(evidence, **kwargs)
            second = persist_instagram_evidence_file(evidence, **kwargs)

            self.assertEqual(
                object_store.read_bytes(first.sha256),
                original,
            )
            self.assertEqual(first.object_id, second.object_id)
            self.assertFalse(first.deduplicated)
            self.assertTrue(second.deduplicated)
            self.assertNotEqual(
                first.acquisition_id,
                second.acquisition_id,
            )

            media = root / "TEST123.jpg"
            media_bytes = b"synthetic-image-bytes"
            media.write_bytes(media_bytes)

            media_result = persist_instagram_evidence_file(
                media,
                **{**kwargs, "evidence_kind": "instagram_media"},
            )
            self.assertEqual(
                object_store.read_bytes(media_result.sha256),
                media_bytes,
            )

            connection.close()


    def test_instagram_post_workflow(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from warrigal.acquisition.instagram import ingest_instagram_post
        from warrigal.database import initialize_database
        from warrigal.models import Batch, Job, Node
        from warrigal.object_store import ObjectStore
        from warrigal.repository import WarrigalRepository

        class ControlledDownloader:
            dirname_pattern = "{target}"

            def download_post(self, post, target):
                root = Path(self.dirname_pattern.format(target=target))
                root.mkdir(parents=True)
                (root / "post.json").write_bytes(b'{"original":true}')
                (root / "post.jpg").write_bytes(b"synthetic-image-bytes")
                return True

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            connection = initialize_database(root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(root / "objects")

            node = Node(name="Instagram Workflow Test")
            repository.save_node(node)
            batch = Batch(node_id=node.node_id, label="Instagram Workflow Batch")
            repository.save_batch(batch)
            job = Job(
                name="Instagram Workflow Job",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            raw_post = SimpleNamespace(
                shortcode="WORKFLOW123",
                date_utc=datetime(2026, 1, 2, tzinfo=timezone.utc),
                typename="GraphImage",
                caption="Ganoderma australe research",
            )

            result = ingest_instagram_post(
                raw_post,
                downloader=ControlledDownloader(),
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )

            self.assertEqual(len(result["evidence"]), 2)
            self.assertEqual(
                result["post"].caption,
                "Ganoderma australe research",
            )
            self.assertEqual(
                object_store.read_bytes(result["evidence"][0].sha256),
                b"synthetic-image-bytes",
            )
            self.assertEqual(
                object_store.read_bytes(result["evidence"][1].sha256),
                b'{"original":true}',
            )
            self.assertTrue(
                repository.object_has_passages(result["snapshot"].object_id)
            )

            connection.close()



class InstagramProfileIngestionTests(unittest.TestCase):
    def test_zero_limit_does_not_discover_posts(self):
        from unittest.mock import Mock
        from warrigal.acquisition.instagram import ingest_instagram_profile

        profile = Mock()
        result = ingest_instagram_profile(
            profile,
            downloader=None,
            repository=None,
            object_store=None,
            job_id="JOB",
            node_id="NODE",
            batch_id="BATCH",
            max_posts=0,
        )
        self.assertEqual(result, [])
        profile.get_posts.assert_not_called()

    def test_negative_limit_is_rejected(self):
        from unittest.mock import Mock
        from warrigal.acquisition.instagram import ingest_instagram_profile

        with self.assertRaises(ValueError):
            ingest_instagram_profile(
                Mock(),
                downloader=None,
                repository=None,
                object_store=None,
                job_id="JOB",
                node_id="NODE",
                batch_id="BATCH",
                max_posts=-1,
            )

    def test_bounded_profile_ingestion_reuses_post_workflow(self):
        from unittest.mock import Mock, patch
        from warrigal.acquisition.instagram import ingest_instagram_profile

        posts = [object() for _ in range(5)]
        profile = Mock()
        profile.get_posts.return_value = iter(posts)

        with patch(
            "warrigal.acquisition.instagram.ingest_instagram_post",
            side_effect=lambda post, **kwargs: {"raw_post": post},
        ) as ingest:
            results = ingest_instagram_profile(
                profile,
                downloader=None,
                repository=None,
                object_store=None,
                job_id="JOB",
                node_id="NODE",
                batch_id="BATCH",
                max_posts=2,
            )

        self.assertEqual(len(results), 2)
        self.assertEqual([r["raw_post"] for r in results], posts[:2])
        self.assertEqual(ingest.call_count, 2)

if __name__ == "__main__":
    unittest.main()
