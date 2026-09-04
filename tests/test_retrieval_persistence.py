import tempfile
import unittest
from pathlib import Path

from warrigal.database import initialize_database
from warrigal.models import Acquisition, Job, Node, Object, Passage, Source
from warrigal.repository import WarrigalRepository
from warrigal.retrieval.passages import passages_from_rows
from warrigal.retrieval.search import search_passages


class RetrievalPersistenceTests(unittest.TestCase):
    def test_persistent_passage_preserves_evidence_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "warrigal.db"
            connection = initialize_database(database_path)

            try:
                repository = WarrigalRepository(connection)

                node = Node(name="test-node")
                repository.save_node(node)

                job = Job(
                    name="test-job",
                    node_id=node.node_id,
                )
                repository.save_job(job)

                source = Source(
                    source_type="web",
                    locator="https://example.test/ganoderma",
                    final_locator="https://example.test/ganoderma",
                    title="Ganoderma australe research",
                )
                repository.save_source(source)

                obj = Object(
                    sha256="a" * 64,
                    size_bytes=123,
                    mime_type="text/html",
                    original_filename="ganoderma.html",
                )
                repository.save_object(obj)

                acquisition = Acquisition(
                    source_id=source.source_id,
                    object_id=obj.object_id,
                    job_id=job.job_id,
                    node_id=node.node_id,
                    method="test",
                )
                repository.save_acquisition(acquisition)

                persistent_passage = Passage(
                    object_id=obj.object_id,
                    acquisition_id=acquisition.acquisition_id,
                    passage_index=0,
                    text="Ganoderma australe contains triterpenes.",
                    source_url=source.final_locator,
                    source_title=source.title,
                )
                repository.save_passage(persistent_passage)

                passages = passages_from_rows(
                    repository.list_passages()
                )
                results = search_passages(
                    "Ganoderma australe",
                    passages,
                )

                self.assertEqual(len(results), 1)

                result = results[0]

                self.assertEqual(
                    result.passage.text,
                    "Ganoderma australe contains triterpenes.",
                )
                self.assertEqual(
                    result.passage.source_url,
                    "https://example.test/ganoderma",
                )
                self.assertEqual(
                    result.passage.source_title,
                    "Ganoderma australe research",
                )
                self.assertEqual(
                    result.passage.object_id,
                    obj.object_id,
                )
                self.assertEqual(
                    result.passage.acquisition_id,
                    acquisition.acquisition_id,
                )
            finally:
                connection.close()

    def test_object_has_passages_tracks_persisted_passages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "warrigal.db"
            connection = initialize_database(database_path)

            try:
                repository = WarrigalRepository(connection)

                node = Node(name="test-node")
                repository.save_node(node)

                job = Job(
                    name="test-job",
                    node_id=node.node_id,
                )
                repository.save_job(job)

                source = Source(
                    source_type="file",
                    locator="archive-test.pdf",
                    final_locator="archive-test.pdf",
                    title="Archive Test",
                )
                repository.save_source(source)

                obj = Object(
                    sha256="b" * 64,
                    size_bytes=456,
                    mime_type="application/pdf",
                    original_filename="archive-test.pdf",
                )
                repository.save_object(obj)

                acquisition = Acquisition(
                    source_id=source.source_id,
                    object_id=obj.object_id,
                    job_id=job.job_id,
                    node_id=node.node_id,
                    method="test",
                )
                repository.save_acquisition(acquisition)

                self.assertFalse(
                    repository.object_has_passages(obj.object_id)
                )

                passage = Passage(
                    object_id=obj.object_id,
                    acquisition_id=acquisition.acquisition_id,
                    passage_index=0,
                    text="Persistent archive evidence.",
                    source_url="archive-test.pdf",
                    source_title="Archive Test",
                )
                repository.save_passage(passage)

                self.assertTrue(
                    repository.object_has_passages(obj.object_id)
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
