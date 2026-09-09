from __future__ import annotations

import mimetypes
from pathlib import Path

from warrigal.acquisition.service import AcquisitionService
from warrigal.audio_ingestion import ingest_audio_object
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


def run_ingest_audio(
    path: str,
    *,
    model_path: str,
    repository=None,
    object_store=None,
    transcriber=None,
) -> int:
    """Archive local audio, then transcribe the preserved copy."""

    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    model = Path(model_path).expanduser().resolve()
    if not model.is_file():
        raise FileNotFoundError(model)

    owns_database = repository is None
    db = None

    if owns_database:
        db = initialize_database()
        repository = WarrigalRepository(db)

    if object_store is None:
        object_store = ObjectStore()

    try:
        node = Node(name="Warrigal Audio")
        repository.save_node(node)

        batch = Batch(
            node_id=node.node_id,
            label="Local audio ingestion",
        )
        repository.save_batch(batch)

        job = Job(
            name="Local audio ingestion",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)

        collection = Collection(
            name="Audio Acquisitions",
            description="Original audio and derived transcripts preserved by Warrigal.",
        )
        repository.save_collection(collection)

        source = Source(
            source_type="local_audio",
            locator=source_path.as_uri(),
            title=source_path.name,
            metadata={"original_path": str(source_path)},
        )
        repository.save_source(source)

        service = AcquisitionService(repository, object_store)
        original = service.acquire_bytes(
            data=source_path.read_bytes(),
            source_id=source.source_id,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            method="local_audio_file",
            mime_type=mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
            original_filename=source_path.name,
            collection_id=collection.collection_id,
        )

        kwargs = {}
        if transcriber is not None:
            kwargs["transcriber"] = transcriber

        result = ingest_audio_object(
            source_object_id=original.object_id,
            source_acquisition_id=original.acquisition_id,
            source_path=original.archive_path,
            source_url=source_path.as_uri(),
            source_title=source_path.name,
            model_path=model,
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
            **kwargs,
        )

        print()
        print("=== WARRIGAL AUDIO INGESTION ===")
        print(f"SOURCE:         {source_path}")
        print(f"ORIGINAL:       {original.object_id}")
        print(f"ORIGINAL SHA256:{original.sha256}")
        print(f"TRANSCRIPT:     {result.transcript_object_id}")
        print(f"ACQUISITION:    {result.transcript_acquisition_id}")
        print(f"SEGMENTS:       {len(result.transcript.segments)}")
        print(f"NEW PASSAGES:   {result.passage_count}")
        return 0
    finally:
        if db is not None:
            db.close()
