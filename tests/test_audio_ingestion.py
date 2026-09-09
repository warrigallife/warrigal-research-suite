from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from warrigal.acquisition.service import AcquisitionService
from warrigal.audio import TranscriptResult, TranscriptSegment
from warrigal.audio_ingestion import ingest_audio_object
from warrigal.database import initialize_database
from warrigal.models import Batch, Job, Node, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


class AudioIngestionTests(unittest.TestCase):
    def test_preserves_transcript_and_timestamped_passages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = WarrigalRepository(
                initialize_database(root / "test.db")
            )
            object_store = ObjectStore(root / "objects")

            node = Node(name="Audio test")
            repository.save_node(node)
            batch = Batch(node_id=node.node_id, label="Audio test")
            repository.save_batch(batch)
            job = Job(
                name="Audio test",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            source = Source(
                source_type="audio",
                locator="file:///test-song.flac",
                title="Test song",
            )
            repository.save_source(source)

            service = AcquisitionService(repository, object_store)
            original = b"original audio bytes"
            audio = service.acquire_bytes(
                data=original,
                source_id=source.source_id,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                method="test_audio_acquisition",
                mime_type="audio/flac",
                original_filename="test-song.flac",
            )

            raw_json = json.dumps({
                "transcription": [
                    {"offsets": {"from": 0, "to": 1000}, "text": "Hello"},
                    {"offsets": {"from": 1000, "to": 2000}, "text": "world"},
                ]
            }).encode("utf-8")

            def fake_transcriber(source_path, *, model_path):
                return TranscriptResult(
                    source_path=Path(source_path),
                    segments=(
                        TranscriptSegment(0, 0, 1000, "Hello"),
                        TranscriptSegment(1, 1000, 2000, "world"),
                    ),
                    raw_json=raw_json,
                    model_path=Path(model_path),
                )

            arguments = dict(
                source_object_id=audio.object_id,
                source_acquisition_id=audio.acquisition_id,
                source_path=audio.archive_path,
                source_url="file:///test-song.flac",
                source_title="Test song",
                model_path=root / "fake-model.bin",
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                transcriber=fake_transcriber,
            )

            first = ingest_audio_object(**arguments)
            second = ingest_audio_object(**arguments)

            self.assertEqual(first.passage_count, 2)
            self.assertEqual(second.passage_count, 0)
            self.assertEqual(
                first.transcript_object_id,
                second.transcript_object_id,
            )

            transcript_object = repository.get_object(
                first.transcript_object_id
            )
            self.assertEqual(
                object_store.read_bytes(transcript_object["sha256"]),
                raw_json,
            )

            passages = [
                row for row in repository.list_passages()
                if row["object_id"] == first.transcript_object_id
            ]
            self.assertEqual(len(passages), 2)
            self.assertEqual([row["text"] for row in passages], [
                "Hello", "world"
            ])

            metadata = json.loads(passages[0]["metadata_json"])
            self.assertEqual(metadata["start_ms"], 0)
            self.assertEqual(metadata["end_ms"], 1000)
            self.assertEqual(
                metadata["derived_from_object_id"],
                audio.object_id,
            )

            self.assertEqual(
                Path(audio.archive_path).read_bytes(),
                original,
            )


if __name__ == "__main__":
    unittest.main()
