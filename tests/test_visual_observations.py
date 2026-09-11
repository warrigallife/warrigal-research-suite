from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from warrigal.acquisition.service import AcquisitionService
from warrigal.database import initialize_database
from warrigal.models import (
    Batch,
    Job,
    Node,
    Source,
    VisualObservation,
)
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


class VisualObservationPersistenceTests(unittest.TestCase):
    def test_visual_observation_preserves_frame_and_analyser_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = initialize_database(root / "test.db")

            try:
                repository = WarrigalRepository(db)
                store = ObjectStore(root / "objects")

                node = Node(name="Visual Observation Test")
                repository.save_node(node)

                batch = Batch(
                    node_id=node.node_id,
                    label="Visual Observation Test",
                )
                repository.save_batch(batch)

                job = Job(
                    name="Visual Observation Test",
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                )
                repository.save_job(job)

                source = Source(
                    source_type="video_frame",
                    locator="https://example.test/video",
                    title="Test Video @ 10000 ms",
                )
                repository.save_source(source)

                service = AcquisitionService(repository, store)
                frame = service.acquire_bytes(
                    data=b"real archived frame evidence",
                    source_id=source.source_id,
                    job_id=job.job_id,
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                    method="video_frame_extraction",
                    mime_type="image/jpeg",
                    original_filename="frame-000001.jpg",
                    metadata={
                        "timestamp_ms": 10000,
                        "derived_from_object_id": "parent-video",
                    },
                )

                observation = VisualObservation(
                    frame_object_id=frame.object_id,
                    frame_acquisition_id=frame.acquisition_id,
                    timestamp_ms=10000,
                    text="A hand appears to hold a rectangular material.",
                    analyser="test-vision-model",
                    analyser_version="1.0",
                    confidence=0.75,
                    metadata={
                        "prompt_contract": "visual-observation-v1",
                    },
                )
                repository.save_visual_observation(observation)

                rows = repository.get_visual_observations_for_frame(
                    frame.object_id
                )

                self.assertEqual(len(rows), 1)

                row = rows[0]
                self.assertEqual(
                    row["observation_id"],
                    observation.observation_id,
                )
                self.assertEqual(
                    row["frame_object_id"],
                    frame.object_id,
                )
                self.assertEqual(
                    row["frame_acquisition_id"],
                    frame.acquisition_id,
                )
                self.assertEqual(row["timestamp_ms"], 10000)
                self.assertEqual(
                    row["text"],
                    "A hand appears to hold a rectangular material.",
                )
                self.assertEqual(
                    row["analyser"],
                    "test-vision-model",
                )
                self.assertEqual(row["analyser_version"], "1.0")
                self.assertEqual(row["status"], "derived")
                self.assertEqual(row["confidence"], 0.75)

                # The underlying frame remains independently archived evidence.
                archived = repository.get_object(frame.object_id)
                self.assertIsNotNone(archived)
                self.assertEqual(
                    store.read_bytes(archived["sha256"]),
                    b"real archived frame evidence",
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
