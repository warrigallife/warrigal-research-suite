import sqlite3
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


    def test_passage_metadata_survives_persistence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "warrigal.db"
            connection = initialize_database(database_path)

            try:
                repository = WarrigalRepository(connection)

                node = Node(name="metadata-node")
                repository.save_node(node)

                job = Job(
                    name="metadata-job",
                    node_id=node.node_id,
                )
                repository.save_job(job)

                source = Source(
                    source_type="youtube",
                    locator="https://www.youtube.com/watch?v=test",
                    final_locator="https://www.youtube.com/watch?v=test",
                    title="Test Video",
                )
                repository.save_source(source)

                obj = Object(
                    sha256="c" * 64,
                    size_bytes=789,
                    mime_type="application/json",
                    original_filename="test.en-orig.json3",
                )
                repository.save_object(obj)

                acquisition = Acquisition(
                    source_id=source.source_id,
                    object_id=obj.object_id,
                    job_id=job.job_id,
                    node_id=node.node_id,
                    method="youtube_caption",
                )
                repository.save_acquisition(acquisition)

                metadata = {
                    "start_ms": 1000,
                    "end_ms": 2500,
                    "source_segment_start": 0,
                    "source_start_char": 0,
                    "source_segment_end": 1,
                    "source_end_char": 8,
                }

                passage = Passage(
                    object_id=obj.object_id,
                    acquisition_id=acquisition.acquisition_id,
                    passage_index=0,
                    text="Transcript evidence.",
                    source_url=source.final_locator,
                    source_title=source.title,
                    metadata=metadata,
                )
                repository.save_passage(passage)

                rows = repository.list_passages()

                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    rows[0]["metadata_json"],
                    '{"start_ms": 1000, "end_ms": 2500, '
                    '"source_segment_start": 0, "source_start_char": 0, '
                    '"source_segment_end": 1, "source_end_char": 8}',
                )
            finally:
                connection.close()

    def test_initialize_database_migrates_existing_passages_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "warrigal.db"

            connection = sqlite3.connect(database_path)

            try:
                connection.execute(
                    """
                    CREATE TABLE passages (
                        passage_id TEXT PRIMARY KEY,
                        object_id TEXT NOT NULL,
                        acquisition_id TEXT NOT NULL,
                        passage_index INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        source_url TEXT,
                        source_title TEXT,
                        created_at TEXT NOT NULL,
                        UNIQUE (acquisition_id, passage_index)
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO passages (
                        passage_id,
                        object_id,
                        acquisition_id,
                        passage_index,
                        text,
                        source_url,
                        source_title,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "WRG-PASSAGE-OLD",
                        "WRG-OBJ-OLD",
                        "WRG-ACQ-OLD",
                        0,
                        "Existing evidence.",
                        "old-source",
                        "Old Source",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            connection = initialize_database(database_path)

            try:
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(passages)"
                    )
                }

                self.assertIn("metadata_json", columns)

                row = connection.execute(
                    """
                    SELECT
                        passage_id,
                        text,
                        metadata_json
                    FROM passages
                    WHERE passage_id = ?
                    """,
                    ("WRG-PASSAGE-OLD",),
                ).fetchone()

                self.assertIsNotNone(row)
                self.assertEqual(
                    row["text"],
                    "Existing evidence.",
                )
                self.assertEqual(
                    row["metadata_json"],
                    "{}",
                )
            finally:
                connection.close()




class InstagramCheckpointPersistenceTests(unittest.TestCase):
    def test_checkpoint_persists_and_rejects_replacement(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from warrigal.acquisition.service import AcquisitionService
        from warrigal.database import initialize_database
        from warrigal.models import Batch, Job, Node
        from warrigal.object_store import ObjectStore
        from warrigal.repository import WarrigalRepository

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = initialize_database(root / "warrigal.db")
            try:
                repository = WarrigalRepository(db)
                store = ObjectStore(root / "objects")
                node = Node(name="Checkpoint Test")
                repository.save_node(node)
                batch = Batch(node_id=node.node_id, label="Checkpoint Batch")
                repository.save_batch(batch)
                job = Job(
                    name="Checkpoint Job",
                    node_id=node.node_id,
                    batch_id=batch.batch_id,
                )
                repository.save_job(job)
                service = AcquisitionService(repository, store)

                def acquire(data):
                    return service.acquire_bytes(
                        data=data,
                        source_id=source.source_id,
                        job_id=job.job_id,
                        node_id=node.node_id,
                        batch_id=batch.batch_id,
                        method="checkpoint_test",
                    )

                from warrigal.models import Source
                source = Source(
                    source_type="instagram_post",
                    locator="https://www.instagram.com/p/TEST123/",
                )
                repository.save_source(source)

                snapshot = acquire(b"snapshot")
                evidence = acquire(b"evidence")

                self.assertIsNone(
                    repository.get_instagram_post_checkpoint(
                        "Example", "TEST123"
                    )
                )

                kwargs = dict(
                    profile_username="Example",
                    shortcode="TEST123",
                    snapshot_acquisition_id=snapshot.acquisition_id,
                    evidence_acquisition_ids=[evidence.acquisition_id],
                )
                repository.save_instagram_post_checkpoint(**kwargs)
                repository.save_instagram_post_checkpoint(**kwargs)

                row = repository.get_instagram_post_checkpoint(
                    "example", "TEST123"
                )
                self.assertEqual(row["contract_version"], 1)
                self.assertEqual(
                    row["snapshot_acquisition_id"],
                    snapshot.acquisition_id,
                )
                self.assertEqual(
                    json.loads(row["evidence_acquisition_ids_json"]),
                    [evidence.acquisition_id],
                )

                with self.assertRaisesRegex(ValueError, "Unknown"):
                    repository.save_instagram_post_checkpoint(
                        **{**kwargs, "evidence_acquisition_ids": ["MISSING"]}
                    )

                replacement = acquire(b"replacement")
                with self.assertRaisesRegex(ValueError, "different"):
                    repository.save_instagram_post_checkpoint(
                        **{
                            **kwargs,
                            "evidence_acquisition_ids": [
                                replacement.acquisition_id
                            ],
                        }
                    )

                preserved = repository.get_instagram_post_checkpoint(
                    "example", "TEST123"
                )
                self.assertEqual(
                    preserved["snapshot_acquisition_id"],
                    snapshot.acquisition_id,
                )
            finally:
                db.close()

if __name__ == "__main__":
    unittest.main()
