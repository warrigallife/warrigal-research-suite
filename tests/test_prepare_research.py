import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from warrigal import cli
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


class RunSearchAutomaticPacketTests(unittest.TestCase):
    """`warrigal.cli search` is the existing WRS research entry point -- the
    same backend the Archive Search source-panel action already shells out
    to. These tests confirm that entry point now also prepares a local
    evidence packet automatically, with no separate manual
    `warrigal.prepare_research` invocation required."""

    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.connection = initialize_database(root / "warrigal.db")
        self.output_dir = root / "research-briefs"
        repository = WarrigalRepository(self.connection)

        node = Node(name="Run Search Packet Test")
        repository.save_node(node)
        batch = Batch(node_id=node.node_id)
        repository.save_batch(batch)
        job = Job(name="Run Search Packet Test", node_id=node.node_id, batch_id=batch.batch_id)
        repository.save_job(job)

        source = Source(
            source_type="web",
            locator="https://example.com/jennings-claim",
            final_locator="https://example.com/jennings-claim",
            title="Jennings claim source",
        )
        repository.save_source(source)

        obj = Object(
            sha256="1" * 64,
            size_bytes=42,
            mime_type="text/plain",
            original_filename="jennings-claim.txt",
        )
        repository.save_object(obj)

        acquisition = Acquisition(
            source_id=source.source_id,
            object_id=obj.object_id,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            method="web_fetch",
            status="success",
        )
        repository.save_acquisition(acquisition)

        passage = Passage(
            object_id=obj.object_id,
            acquisition_id=acquisition.acquisition_id,
            passage_index=0,
            text="Jennings claimed the device could run without external power.",
            source_url=source.final_locator,
            source_title=source.title,
        )
        repository.save_passage(passage)
        self.source_url = source.final_locator

    def tearDown(self):
        self.connection.close()
        self.temporary.cleanup()

    def _run_search_capturing_stdout(self, query: str) -> str:
        buffer = io.StringIO()
        with mock.patch("warrigal.cli.initialize_database", return_value=self.connection), \
            mock.patch(
                "warrigal.cli.RESEARCH_BRIEF_OUTPUT_DIR", self.output_dir
            ), redirect_stdout(buffer):
            exit_code = cli.run_search(query)
        self.assertEqual(exit_code, 0)
        return buffer.getvalue()

    def test_eligible_search_automatically_prepares_packet_with_sources(self):
        with mock.patch("urllib.request.urlopen") as urlopen, mock.patch(
            "http.client.HTTPConnection.request"
        ) as http_request:
            output = self._run_search_capturing_stdout("Jennings device power claim")

            # No extra Claude/Ollama/network call was made to prepare the packet.
            urlopen.assert_not_called()
            http_request.assert_not_called()

        self.assertIn("EVIDENCE PACKET:", output)

        packet_line = next(
            line for line in output.splitlines() if line.startswith("EVIDENCE PACKET:")
        )
        packet_path = Path(packet_line.split("EVIDENCE PACKET:", 1)[1].strip())

        self.assertTrue(packet_path.exists())
        packet_text = packet_path.read_text(encoding="utf-8")
        self.assertIn(self.source_url, packet_text)
        self.assertIn("Jennings claimed the device could run", packet_text)

    def test_search_with_no_matches_still_prepares_packet_transparently(self):
        output = self._run_search_capturing_stdout(
            "completely unrelated query about spacecraft propulsion"
        )

        self.assertIn("EVIDENCE PACKET:", output)
        packet_line = next(
            line for line in output.splitlines() if line.startswith("EVIDENCE PACKET:")
        )
        packet_path = Path(packet_line.split("EVIDENCE PACKET:", 1)[1].strip())
        packet_text = packet_path.read_text(encoding="utf-8")
        self.assertIn("No archived passages matched this query", packet_text)


if __name__ == "__main__":
    unittest.main()
