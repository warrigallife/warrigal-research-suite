import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from warrigal.database import initialize_database
from warrigal.models import Acquisition, Batch, Job, Node, Object, Passage, Source
from warrigal.prepare_research import prepare_research_packet
from warrigal.repository import WarrigalRepository


class PrepareResearchPacketTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.connection = initialize_database(root / "warrigal.db")
        self.repository = WarrigalRepository(self.connection)
        self.output_dir = root / "research-briefs"

        node = Node(name="Prepare Research Test")
        self.repository.save_node(node)
        batch = Batch(node_id=node.node_id)
        self.repository.save_batch(batch)
        job = Job(name="Prepare Research Test", node_id=node.node_id, batch_id=batch.batch_id)
        self.repository.save_job(job)

        source = Source(
            source_type="web",
            locator="https://example.com/jennings-claim",
            final_locator="https://example.com/jennings-claim",
            title="Jennings claim source",
        )
        self.repository.save_source(source)

        obj = Object(
            sha256="0" * 64,
            size_bytes=42,
            mime_type="text/plain",
            original_filename="jennings-claim.txt",
        )
        self.repository.save_object(obj)

        acquisition = Acquisition(
            source_id=source.source_id,
            object_id=obj.object_id,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            method="web_fetch",
            status="success",
        )
        self.repository.save_acquisition(acquisition)

        passage = Passage(
            object_id=obj.object_id,
            acquisition_id=acquisition.acquisition_id,
            passage_index=0,
            text="Jennings claimed the device could run without external power.",
            source_url=source.final_locator,
            source_title=source.title,
        )
        self.repository.save_passage(passage)
        self.acquisition_id = acquisition.acquisition_id
        self.object_id = obj.object_id
        self.source_url = source.final_locator

    def tearDown(self):
        self.connection.close()
        self.temporary.cleanup()

    def test_packet_contains_matching_passage_with_provenance(self):
        path = prepare_research_packet(
            "Jennings device power claim",
            database=self.connection,
            output_dir=self.output_dir,
        )

        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")

        self.assertIn("Jennings claimed the device could run", text)
        self.assertIn(self.source_url, text)
        self.assertIn(self.object_id, text)
        self.assertIn(self.acquisition_id, text)
        self.assertIn("web_fetch", text)
        self.assertIn("No Claude or Ollama inference", text)

    def test_no_matching_passage_reports_empty_result(self):
        path = prepare_research_packet(
            "completely unrelated query about spacecraft propulsion",
            database=self.connection,
            output_dir=self.output_dir,
        )

        text = path.read_text(encoding="utf-8")
        self.assertIn("No archived passages matched this query", text)

    def test_retrieval_makes_no_network_or_model_call(self):
        with mock.patch("urllib.request.urlopen") as urlopen, mock.patch(
            "http.client.HTTPConnection.request"
        ) as http_request:
            prepare_research_packet(
                "Jennings device power claim",
                database=self.connection,
                output_dir=self.output_dir,
            )

            urlopen.assert_not_called()
            http_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
