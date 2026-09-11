from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from warrigal.acquisition.service import AcquisitionService
from warrigal.database import initialize_database
from warrigal.models import Batch, Job, Node, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.video_frames import VideoFrame
from warrigal.video_frames_cli import (
    run_extract_video_frames,
    select_acquisition,
)


class VideoFramesCLITests(unittest.TestCase):
    def test_rejects_ambiguous_acquisition(self):
        acquisitions = [
            {"acquisition_id": "WRG-ACQ-ONE"},
            {"acquisition_id": "WRG-ACQ-TWO"},
        ]

        with self.assertRaisesRegex(ValueError, "multiple acquisitions"):
            select_acquisition(acquisitions, None)

        selected = select_acquisition(
            acquisitions,
            "WRG-ACQ-TWO",
        )
        self.assertEqual(
            selected["acquisition_id"],
            "WRG-ACQ-TWO",
        )

    def test_extracts_frames_from_archived_object(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = initialize_database(root / "test.db")

            try:
                repository = WarrigalRepository(db)
                store = ObjectStore(root / "objects")

                node = Node(name="Archived Frame CLI Test")
                repository.save_node(node)

                batch = Batch(
                    node_id=node.node_id,
                    label="Archived Frame CLI Test",
                )
                repository.save_batch(batch)

                job = Job(
                    name="Archived Frame CLI Test",
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                )
                repository.save_job(job)

                source = Source(
                    source_type="youtube_media",
                    locator="https://example.test/watch?v=visual",
                    final_locator="https://example.test/watch?v=visual",
                    title="Visual Test",
                )
                repository.save_source(source)

                service = AcquisitionService(repository, store)
                original = service.acquire_bytes(
                    data=b"archived video bytes",
                    source_id=source.source_id,
                    job_id=job.job_id,
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                    method="test_video",
                    mime_type="video/mp4",
                    original_filename="visual.mp4",
                )

                seen = {}

                def fake_extractor(source_path, *, interval_seconds):
                    path = Path(source_path)
                    seen["bytes"] = path.read_bytes()
                    seen["interval"] = interval_seconds

                    return (
                        VideoFrame(
                            index=0,
                            timestamp_ms=0,
                            image_bytes=b"frame zero",
                        ),
                        VideoFrame(
                            index=1,
                            timestamp_ms=5000,
                            image_bytes=b"frame five",
                        ),
                    )

                result = run_extract_video_frames(
                    original.object_id,
                    interval_seconds=5.0,
                    repository=repository,
                    object_store=store,
                    extractor=fake_extractor,
                )

                self.assertEqual(result, 0)
                self.assertEqual(
                    seen["bytes"],
                    b"archived video bytes",
                )
                self.assertEqual(seen["interval"], 5.0)

                acquisitions = repository.get_acquisitions_for_object(
                    original.object_id
                )
                self.assertEqual(len(acquisitions), 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
