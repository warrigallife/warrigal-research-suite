from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfWriter

from warrigal.acquisition.web import WebResponse
from warrigal.acquisition.web_documents import ingest_web_pdf
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


class FakeFetcher:
    def __init__(self, data: bytes):
        self.data = data

    def fetch(self, url: str) -> WebResponse:
        return WebResponse(
            requested_url=url,
            final_url=url,
            status=200,
            content_type="application/pdf",
            data=self.data,
        )


def valid_blank_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return output.getvalue()


class WebPdfRepairTests(unittest.TestCase):
    def test_damaged_original_and_repaired_derivative_are_both_preserved(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = initialize_database(root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(root / "objects")

            node = Node(name="PDF Repair Test")
            repository.save_node(node)

            batch = Batch(
                node_id=node.node_id,
                label="PDF repair test",
            )
            repository.save_batch(batch)

            job = Job(
                name="PDF repair test",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            collection = Collection(name="PDF Repair Test")
            repository.save_collection(collection)

            original = b"%PDF-1.4\nbroken-pages-tree\n%%EOF\n"
            repaired = valid_blank_pdf()

            result = ingest_web_pdf(
                "https://example.test/damaged.pdf",
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                collection_id=collection.collection_id,
                fetcher=FakeFetcher(original),
                repairer=lambda _: repaired,
            )

            self.assertEqual(result.status, "repaired")
            self.assertEqual(result.repair_tool, "qpdf")
            self.assertIsNotNone(result.original_object_id)
            self.assertIsNotNone(result.original_acquisition_id)
            self.assertIsNotNone(result.original_sha256)
            self.assertIsNotNone(result.object_id)
            self.assertIsNotNone(result.acquisition_id)
            self.assertIsNotNone(result.sha256)

            self.assertNotEqual(
                result.original_object_id,
                result.object_id,
            )
            self.assertNotEqual(
                result.original_sha256,
                result.sha256,
            )

            object_count = connection.execute(
                "SELECT COUNT(*) FROM objects"
            ).fetchone()[0]
            acquisition_count = connection.execute(
                "SELECT COUNT(*) FROM acquisitions"
            ).fetchone()[0]

            self.assertEqual(object_count, 2)
            self.assertEqual(acquisition_count, 2)

            repaired_source = connection.execute(
                """
                SELECT source_type, metadata_json
                FROM sources
                WHERE source_id = (
                    SELECT source_id
                    FROM acquisitions
                    WHERE acquisition_id = ?
                )
                """,
                (result.acquisition_id,),
            ).fetchone()

            self.assertEqual(repaired_source[0], "derived_pdf")
            self.assertIn(
                result.original_object_id,
                repaired_source[1],
            )
            self.assertIn("qpdf", repaired_source[1])

            connection.close()

    def test_unrepaired_damage_still_returns_original_identity(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = initialize_database(root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(root / "objects")

            node = Node(name="PDF Damage Test")
            repository.save_node(node)

            batch = Batch(
                node_id=node.node_id,
                label="PDF damage test",
            )
            repository.save_batch(batch)

            job = Job(
                name="PDF damage test",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            collection = Collection(name="PDF Damage Test")
            repository.save_collection(collection)

            result = ingest_web_pdf(
                "https://example.test/damaged.pdf",
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                collection_id=collection.collection_id,
                fetcher=FakeFetcher(b"%PDF-1.4\nbroken\n%%EOF\n"),
                repairer=None,
            )

            self.assertEqual(result.status, "preserved_damaged")
            self.assertIsNotNone(result.object_id)
            self.assertIsNotNone(result.acquisition_id)
            self.assertIsNotNone(result.sha256)
            self.assertEqual(result.object_id, result.original_object_id)
            self.assertEqual(
                result.acquisition_id,
                result.original_acquisition_id,
            )

            connection.close()


if __name__ == "__main__":
    unittest.main()
