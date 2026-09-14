import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from warrigal.acquisition.youtube_comments import (
    extract_youtube_comments,
    ingest_youtube_comments,
    parse_youtube_comments,
    select_target_thread_context,
)
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


def comment_info():
    return {
        "id": "video-test",
        "title": "JUFE discussion",
        "webpage_url": "https://www.youtube.com/watch?v=video-test",
        "channel": "Randall",
        "channel_id": "UC-RANDALL",
        "comments": [
            {
                "id": "comment-tom",
                "text": "Tom's exact statement.",
                "author": "@TFJ7",
                "author_id": "UC-TOM",
                "author_url": "https://www.youtube.com/@TFJ7",
                "timestamp": 1700000000,
                "parent": "root",
                "like_count": 7,
                "author_is_verified": False,
                "is_pinned": True,
            },
            {
                "id": "comment-other",
                "text": "Another author's statement.",
                "author": "@someoneelse",
                "author_id": "UC-OTHER",
                "parent": "root",
            },
        ],
    }


def thread_info():
    info = comment_info()
    info["comments"] = [
        {
            "id": "parent",
            "text": "Question for Tom",
            "author": "@reader",
            "author_id": "UC-READER",
            "parent": "root",
        },
        {
            "id": "tom-reply",
            "text": "Tom answers",
            "author": "@TFJ7",
            "author_id": "UC-TOM",
            "parent": "parent",
        },
        {
            "id": "reply-to-tom",
            "text": "Follow-up to Tom",
            "author": "@reader2",
            "author_id": "UC-READER2",
            "parent": "tom-reply",
        },
        {
            "id": "unrelated",
            "text": "Unrelated",
            "author": "@other",
            "author_id": "UC-OTHER",
            "parent": "root",
        },
    ]
    return info


class YouTubeCommentTests(unittest.TestCase):
    def test_selects_target_parent_and_direct_reply_context(self):
        info = thread_info()
        comments = parse_youtube_comments(info)
        selected = select_target_thread_context(
            comments,
            [(comments[1], "author_id")],
        )

        self.assertEqual(
            [(comment.comment_id, role) for comment, role, _ in selected],
            [
                ("parent", "parent_context"),
                ("tom-reply", "target_author"),
                ("reply-to-tom", "reply_context"),
            ],
        )

    def test_rerun_restores_missing_context_without_duplicate_targets(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            connection = initialize_database(root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(root / "objects")
            node = Node(name="Context Upgrade")
            repository.save_node(node)
            batch = Batch(node_id=node.node_id)
            repository.save_batch(batch)
            job = Job(
                name="Context Upgrade",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)
            collection = Collection(name="Context Upgrade")
            repository.save_collection(collection)
            kwargs = {
                "target_author_id": "UC-TOM",
                "repository": repository,
                "object_store": object_store,
                "job_id": job.job_id,
                "node_id": node.node_id,
                "batch_id": batch.batch_id,
                "collection_id": collection.collection_id,
                "extractor": lambda url, limit: thread_info(),
            }

            first = ingest_youtube_comments(
                "https://www.youtube.com/watch?v=video-test",
                **kwargs,
            )
            rows = repository.get_passages_for_object(first.object_id)
            target_id = next(
                row["passage_id"]
                for row in rows
                if json.loads(row["metadata_json"])["context_role"]
                == "target_author"
            )
            connection.execute(
                "DELETE FROM passages WHERE object_id = ? AND passage_id != ?",
                (first.object_id, target_id),
            )
            connection.commit()

            second = ingest_youtube_comments(
                "https://www.youtube.com/watch?v=video-test",
                **kwargs,
            )

            self.assertTrue(second.deduplicated)
            self.assertEqual(second.indexed_count, 2)
            restored = repository.get_passages_for_object(first.object_id)
            self.assertEqual(len(restored), 3)
            roles = {
                json.loads(row["metadata_json"])["context_role"]
                for row in restored
            }
            self.assertEqual(
                roles,
                {"target_author", "parent_context", "reply_context"},
            )
            connection.close()

    def test_parse_comments_preserves_identity_and_thread_provenance(self):
        comments = parse_youtube_comments(comment_info())

        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0].comment_id, "comment-tom")
        self.assertEqual(comments[0].author_id, "UC-TOM")
        self.assertEqual(comments[0].parent_id, "root")
        self.assertEqual(comments[0].timestamp, 1700000000)
        self.assertTrue(comments[0].is_pinned)

    @patch("warrigal.acquisition.youtube_comments.yt_dlp.YoutubeDL")
    def test_extraction_is_bounded(self, youtube_dl):
        ydl = MagicMock()
        youtube_dl.return_value.__enter__.return_value = ydl
        ydl.extract_info.return_value = comment_info()

        result = extract_youtube_comments(
            "https://www.youtube.com/watch?v=video-test",
            250,
        )

        self.assertEqual(result["id"], "video-test")
        options = youtube_dl.call_args.args[0]
        self.assertTrue(options["getcomments"])
        self.assertTrue(options["skip_download"])
        self.assertEqual(
            options["extractor_args"]["youtube"]["max_comments"],
            ["250"],
        )

    def test_ingestion_preserves_snapshot_and_indexes_only_stable_match(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            connection = initialize_database(root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(root / "objects")

            node = Node(name="Comment Test")
            repository.save_node(node)
            batch = Batch(node_id=node.node_id, label="Comment Test")
            repository.save_batch(batch)
            job = Job(
                name="Comment Test",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)
            collection = Collection(name="Comment Test")
            repository.save_collection(collection)

            result = ingest_youtube_comments(
                "https://www.youtube.com/watch?v=video-test",
                target_author_id="UC-TOM",
                target_author_handle="@TFJ7",
                max_comments=100,
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                collection_id=collection.collection_id,
                extractor=lambda url, limit: comment_info(),
            )

            self.assertEqual(result.collected_count, 2)
            self.assertEqual(result.matched_count, 1)
            self.assertEqual(result.match_basis, "author_id")
            self.assertEqual(result.matched_author_ids, ("UC-TOM",))

            rows = repository.list_passages()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["text"], "Tom's exact statement.")
            passage_metadata = json.loads(rows[0]["metadata_json"])
            self.assertEqual(passage_metadata["author_id"], "UC-TOM")
            self.assertEqual(passage_metadata["match_basis"], "author_id")
            self.assertEqual(
                passage_metadata["evidence_status"],
                "explicit_identity",
            )

            snapshot = json.loads(object_store.read_bytes(result.sha256))
            self.assertEqual(len(snapshot["comments"]), 2)
            self.assertEqual(
                snapshot["schema"],
                "warrigal.youtube-comments.v1",
            )
            connection.close()

    def test_handle_only_match_is_marked_provisional(self):
        info = comment_info()
        info["comments"][0]["author_id"] = None

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            connection = initialize_database(root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(root / "objects")
            node = Node(name="Comment Test")
            repository.save_node(node)
            batch = Batch(node_id=node.node_id)
            repository.save_batch(batch)
            job = Job(
                name="Comment Test",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)
            collection = Collection(name="Comment Test")
            repository.save_collection(collection)

            result = ingest_youtube_comments(
                "https://www.youtube.com/watch?v=video-test",
                target_author_handle="@tfj7",
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                collection_id=collection.collection_id,
                extractor=lambda url, limit: info,
            )

            self.assertEqual(result.match_basis, "author_handle_provisional")
            metadata = json.loads(
                repository.list_passages()[0]["metadata_json"]
            )
            self.assertEqual(metadata["evidence_status"], "provisional_identity")
            connection.close()

    def test_target_and_limit_are_required(self):
        with self.assertRaisesRegex(ValueError, "target author"):
            ingest_youtube_comments(
                "https://www.youtube.com/watch?v=test",
                repository=MagicMock(),
                object_store=MagicMock(),
                job_id="job",
                node_id="node",
                batch_id="batch",
                collection_id="collection",
            )

        with self.assertRaisesRegex(ValueError, "at least 1"):
            extract_youtube_comments("https://youtube.test/video", 0)


if __name__ == "__main__":
    unittest.main()
