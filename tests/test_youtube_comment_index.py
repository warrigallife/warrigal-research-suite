import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from warrigal.acquisition.youtube_comment_index import (
    build_youtube_comment_author_directory,
    comments_by_author,
    find_youtube_comment_authors,
    index_archived_youtube_comments,
)
from warrigal.acquisition.youtube_comments import ingest_youtube_comments
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


def archived_comments():
    return {
        "id": "video-index",
        "title": "Indexed discussion",
        "webpage_url": "https://www.youtube.com/watch?v=video-index",
        "channel": "Randall",
        "channel_id": "UC-RANDALL",
        "comments": [
            {
                "id": "comment-tom",
                "text": "Tom's indexed statement.",
                "author": "@TFJ7",
                "author_id": "UC-TOM",
                "author_url": "https://www.youtube.com/@TFJ7",
                "parent": "root",
            },
            {
                "id": "comment-scrolls",
                "text": "A second archived statement.",
                "author": "@GodsScrollsArchive",
                "author_id": "UC-SCROLLS",
                "author_url": "https://www.youtube.com/@GodsScrollsArchive",
                "parent": "root",
            },
        ],
    }


class YouTubeCommentIndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.connection = initialize_database(root / "warrigal.db")
        self.repository = WarrigalRepository(self.connection)
        self.object_store = ObjectStore(root / "objects")

        node = Node(name="Comment Index Test")
        self.repository.save_node(node)
        batch = Batch(node_id=node.node_id)
        self.repository.save_batch(batch)
        job = Job(
            name="Comment Index Test",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        self.repository.save_job(job)
        collection = Collection(name="Comment Index Test")
        self.repository.save_collection(collection)

        ingest_youtube_comments(
            "https://www.youtube.com/watch?v=video-index",
            target_author_id="UC-TOM",
            repository=self.repository,
            object_store=self.object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
            extractor=lambda url, limit: archived_comments(),
        )

    def tearDown(self):
        self.connection.close()
        self.temporary.cleanup()

    def test_indexer_adds_unindexed_comments_without_network_access(self):
        first = index_archived_youtube_comments(
            repository=self.repository,
            object_store=self.object_store,
        )
        second = index_archived_youtube_comments(
            repository=self.repository,
            object_store=self.object_store,
        )

        self.assertEqual(first.objects_scanned, 1)
        self.assertEqual(first.snapshots_indexed, 1)
        self.assertEqual(first.comments_seen, 2)
        self.assertEqual(first.already_indexed, 1)
        self.assertEqual(first.passages_created, 1)
        self.assertEqual(second.passages_created, 0)
        self.assertEqual(len(self.repository.list_passages()), 2)

    def test_indexer_can_limit_work_to_channel_inventory_urls(self):
        result = index_archived_youtube_comments(
            repository=self.repository,
            object_store=self.object_store,
            source_urls={"https://www.youtube.com/watch?v=another-video"},
        )

        self.assertEqual(result.snapshots_indexed, 0)
        self.assertEqual(result.comments_seen, 0)
        self.assertEqual(result.passages_created, 0)

    def test_author_directory_uses_stable_ids_and_known_handles(self):
        index_archived_youtube_comments(
            repository=self.repository,
            object_store=self.object_store,
        )
        authors = build_youtube_comment_author_directory(
            self.repository.list_passages()
        )

        self.assertEqual(len(authors), 2)
        by_id = {author.author_id: author for author in authors}
        self.assertEqual(by_id["UC-TOM"].handles, ("@TFJ7",))
        self.assertEqual(
            by_id["UC-TOM"].profile_urls,
            ("https://www.youtube.com/@TFJ7",),
        )
        self.assertEqual(by_id["UC-SCROLLS"].comment_count, 1)
        self.assertEqual(by_id["UC-SCROLLS"].video_count, 1)

    def test_find_authors_and_retrieve_comments(self):
        index_archived_youtube_comments(
            repository=self.repository,
            object_store=self.object_store,
        )
        passages = self.repository.list_passages()

        found = find_youtube_comment_authors(passages, "scrolls")
        comments = comments_by_author(passages, "UC-SCROLLS")

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].author_id, "UC-SCROLLS")
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["text"], "A second archived statement.")
        by_url = find_youtube_comment_authors(
            passages,
            "youtube.com/@GodsScrollsArchive",
        )
        self.assertEqual(by_url[0].author_id, "UC-SCROLLS")

    def test_empty_author_queries_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            find_youtube_comment_authors([], "  ")
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            comments_by_author([], "")


if __name__ == "__main__":
    unittest.main()
