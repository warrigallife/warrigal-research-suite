from __future__ import annotations

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


class WebDocumentTests(unittest.TestCase):
    def test_web_pdf_preserves_remote_and_discovery_provenance(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            pdf_path = root / "test.pdf"

            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.add_metadata({"/Title": "Remote Test PDF"})

            with pdf_path.open("wb") as handle:
                writer.write(handle)

            data = pdf_path.read_bytes()

            connection = initialize_database(root / "warrigal.db")
            repository = WarrigalRepository(connection)
            object_store = ObjectStore(root / "objects")

            node = Node(name="Web Document Test")
            repository.save_node(node)

            batch = Batch(
                node_id=node.node_id,
                label="Web document test batch",
            )
            repository.save_batch(batch)

            job = Job(
                name="Web document test job",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            collection = Collection(
                name="Bunker Web Document Test",
            )
            repository.save_collection(collection)

            url = (
                "https://bunkerofdoom.com/lit/semico/"
                "125-Transistor-Projects-Rufus-Turner.pdf"
            )

            discovery = {
                "discovery_page":
                    "https://bunkerofdoom.com/lit/semico/index.html",
                "discovered_via": "John Kleinbauer YouTube",
                "youtube_video": "Bunker of Doom Booklets",
                "youtube_video_id": "9P9KqyALVus",
                "youtube_comment_id":
                    "UgwQ78IYFPj5m-6rAOV4AaABAg",
                "youtube_comment_author":
                    "@johnkleinbauer4424",
                "youtube_comment_author_is_uploader": True,
            }

            result = ingest_web_pdf(
                url,
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                collection_id=collection.collection_id,
                discovery_metadata=discovery,
                fetcher=FakeFetcher(data),
            )

            self.assertEqual(result.status, "no_text")
            self.assertIsNotNone(result.object_id)
            self.assertIsNotNone(result.acquisition_id)
            self.assertIsNotNone(result.sha256)
            self.assertEqual(result.size_bytes, len(data))

            object_row = connection.execute(
                """
                SELECT sha256, size_bytes, original_filename
                FROM objects
                WHERE object_id = ?
                """,
                (result.object_id,),
            ).fetchone()

            self.assertIsNotNone(object_row)
            self.assertEqual(object_row[0], result.sha256)
            self.assertEqual(object_row[1], len(data))
            self.assertEqual(
                object_row[2],
                "125-Transistor-Projects-Rufus-Turner.pdf",
            )

            source_row = connection.execute(
                """
                SELECT source_type, locator, final_locator, metadata_json
                FROM sources
                WHERE source_id = (
                    SELECT source_id
                    FROM acquisitions
                    WHERE acquisition_id = ?
                )
                """,
                (result.acquisition_id,),
            ).fetchone()

            self.assertIsNotNone(source_row)
            self.assertEqual(source_row[0], "web_document")
            self.assertEqual(source_row[1], url)
            self.assertEqual(source_row[2], url)

            metadata_json = source_row[3]

            self.assertIn(
                "https://bunkerofdoom.com/lit/semico/index.html",
                metadata_json,
            )
            self.assertIn("John Kleinbauer YouTube", metadata_json)
            self.assertIn("9P9KqyALVus", metadata_json)
            self.assertIn(
                "UgwQ78IYFPj5m-6rAOV4AaABAg",
                metadata_json,
            )
            self.assertIn("@johnkleinbauer4424", metadata_json)

            acquisition_row = connection.execute(
                """
                SELECT method, http_status
                FROM acquisitions
                WHERE acquisition_id = ?
                """,
                (result.acquisition_id,),
            ).fetchone()

            self.assertEqual(acquisition_row[0], "web_document")
            self.assertEqual(acquisition_row[1], 200)

            storage_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM storage_locations
                WHERE object_id = ?
                """,
                (result.object_id,),
            ).fetchone()[0]

            self.assertEqual(storage_count, 1)

            connection.close()


if __name__ == "__main__":
    unittest.main()
