from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from warrigal.acquisition.service import AcquisitionService
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.video_frame_ingestion import ingest_video_frames
from warrigal.video_frames import VideoFrame


class VideoFrameIngestionTests(unittest.TestCase):
    def test_archives_timestamped_frames_with_video_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = initialize_database(root / "test.db")

            try:
                repository = WarrigalRepository(db)
                store = ObjectStore(root / "objects")

                node = Node(name="Frame Test")
                repository.save_node(node)

                batch = Batch(node_id=node.node_id, label="Frame Test")
                repository.save_batch(batch)

                job = Job(
                    name="Frame Test",
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                )
                repository.save_job(job)

                collection = Collection(
                    name="Frame Test",
                    description="Frame extraction test",
                )
                repository.save_collection(collection)

                source = Source(
                    source_type="local_video",
                    locator="file:///test/video.mp4",
                    title="Test Video",
                )
                repository.save_source(source)

                service = AcquisitionService(repository, store)
                original = service.acquire_bytes(
                    data=b"fake video evidence",
                    source_id=source.source_id,
                    job_id=job.job_id,
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                    method="test_video",
                    mime_type="video/mp4",
                    original_filename="video.mp4",
                    collection_id=collection.collection_id,
                )

                def fake_extractor(source_path, *, interval_seconds):
                    self.assertEqual(
                        Path(source_path).read_bytes(),
                        b"fake video evidence",
                    )
                    self.assertEqual(interval_seconds, 10.0)

                    return (
                        VideoFrame(0, 0, b"jpeg frame zero"),
                        VideoFrame(1, 10000, b"jpeg frame ten seconds"),
                    )

                result = ingest_video_frames(
                    source_object_id=original.object_id,
                    source_acquisition_id=original.acquisition_id,
                    source_path=original.archive_path,
                    source_url="https://example.test/video",
                    source_title="Test Video",
                    repository=repository,
                    object_store=store,
                    job_id=job.job_id,
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                    collection_id=collection.collection_id,
                    interval_seconds=10.0,
                    extractor=fake_extractor,
                )

                self.assertEqual(result.source_object_id, original.object_id)
                self.assertEqual(len(result.frames), 2)

                self.assertEqual(result.frames[0].timestamp_ms, 0)
                self.assertEqual(result.frames[1].timestamp_ms, 10000)

                first = repository.get_object(
                    result.frames[0].frame_object_id
                )
                second = repository.get_object(
                    result.frames[1].frame_object_id
                )

                self.assertIsNotNone(first)
                self.assertIsNotNone(second)

                self.assertEqual(
                    store.read_bytes(first["sha256"]),
                    b"jpeg frame zero",
                )
                self.assertEqual(
                    store.read_bytes(second["sha256"]),
                    b"jpeg frame ten seconds",
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
