from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from warrigal.acquisition.manifest import ManifestResource
from warrigal.acquisition.manifest_adapters import (
    make_generic_document_manifest_handler,
)
from warrigal.acquisition.web import WebResponse
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


class FakeFetcher:
    def __init__(
        self,
        data: bytes,
        *,
        content_type: str,
    ):
        self.data = data
        self.content_type = content_type

    def fetch(self, url: str) -> WebResponse:
        return WebResponse(
            requested_url=url,
            final_url=url,
            status=200,
            content_type=self.content_type,
            data=self.data,
        )


class GenericDocumentManifestTests(unittest.TestCase):
    def make_context(self, root: Path):
        connection = initialize_database(root / "warrigal.db")
        repository = WarrigalRepository(connection)
        object_store = ObjectStore(root / "objects")

        node = Node(name="Generic Document Test")
        repository.save_node(node)

        batch = Batch(
            node_id=node.node_id,
            label="Generic document test",
        )
        repository.save_batch(batch)

        job = Job(
            name="Generic document test",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)

        collection = Collection(name="Generic Document Test")
        repository.save_collection(collection)

        return (
            connection,
            repository,
            object_store,
            node,
            batch,
            job,
            collection,
        )

    def test_text_document_is_preserved_and_indexed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                connection,
                repository,
                object_store,
                node,
                batch,
                job,
                collection,
            ) = self.make_context(root)

            resource = ManifestResource(
                url="https://example.test/notes.txt",
                media_type="text/plain",
                status="inventoried",
                expected_size_bytes=44,
                metadata={"branch": "test/text"},
            )

            handler = make_generic_document_manifest_handler(
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                collection_id=collection.collection_id,
                fetcher=FakeFetcher(
                    b"Warrigal generic document extraction works.",
                    content_type="text/plain",
                ),
            )

            result = handler(resource)

            self.assertIsNotNone(result["object_id"])
            self.assertIsNotNone(result["acquisition_id"])
            self.assertIsNotNone(result["sha256"])
            self.assertGreater(result["passage_count"], 0)
            self.assertTrue(
                result["text_extraction_status"].startswith(
                    "decoded:"
                )
            )

            object_count = connection.execute(
                "SELECT COUNT(*) FROM objects"
            ).fetchone()[0]
            passage_count = connection.execute(
                "SELECT COUNT(*) FROM passages"
            ).fetchone()[0]

            self.assertEqual(object_count, 1)
            self.assertGreater(passage_count, 0)

            connection.close()

    def test_extraction_failure_keeps_original_object(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                connection,
                repository,
                object_store,
                node,
                batch,
                job,
                collection,
            ) = self.make_context(root)

            resource = ManifestResource(
                url="https://example.test/legacy.doc",
                media_type="application/msword",
                status="inventoried",
                expected_size_bytes=10,
                metadata={"branch": "test/doc"},
            )

            def fail_extraction(*args, **kwargs):
                raise RuntimeError("test extraction failure")

            handler = make_generic_document_manifest_handler(
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                collection_id=collection.collection_id,
                fetcher=FakeFetcher(
                    b"legacy-doc",
                    content_type="application/msword",
                ),
                extractor=fail_extraction,
            )

            result = handler(resource)

            self.assertIsNotNone(result["object_id"])
            self.assertEqual(
                result["text_extraction_status"],
                "preserved:extraction_failed",
            )
            self.assertIn(
                "test extraction failure",
                result["text_extraction_error"],
            )

            object_count = connection.execute(
                "SELECT COUNT(*) FROM objects"
            ).fetchone()[0]
            self.assertEqual(object_count, 1)

            connection.close()


if __name__ == "__main__":
    unittest.main()
