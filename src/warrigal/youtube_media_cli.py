from __future__ import annotations

import mimetypes
import tempfile
from pathlib import Path

import yt_dlp

from warrigal.acquisition.service import AcquisitionService
from warrigal.audio_ingestion import ingest_audio_object
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


def download_youtube_media(url: str, destination: Path) -> tuple[Path, dict]:
    """Download one YouTube video into a temporary directory."""
    options = {
        "format": "bestvideo*+bestaudio/best",
        "outtmpl": str(destination / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # Modern YouTube extraction needs a JavaScript runtime. Warrigal's
        # doctor documents Deno as the supported local runtime.
        "js_runtimes": {"deno": {}},
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise ValueError("YouTube did not return media information.")
        info = ydl.sanitize_info(info)
        path = Path(ydl.prepare_filename(info))

    if not path.is_file():
        candidates = [
            candidate for candidate in destination.iterdir()
            if candidate.is_file()
            and candidate.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
        ]
        if len(candidates) != 1:
            raise FileNotFoundError("Could not identify the downloaded video.")
        path = candidates[0]

    return path, info


def run_ingest_youtube_media(
    url: str,
    *,
    model_path: str,
    repository=None,
    object_store=None,
    downloader=download_youtube_media,
    transcriber=None,
) -> int:
    """Download, archive, and transcribe one YouTube video."""
    model = Path(model_path).expanduser().resolve()
    if not model.is_file():
        raise FileNotFoundError(model)

    db = None
    if repository is None:
        db = initialize_database()
        repository = WarrigalRepository(db)

    if object_store is None:
        object_store = ObjectStore()

    try:
        with tempfile.TemporaryDirectory(prefix="warrigal-youtube-") as directory:
            media_path, info = downloader(url, Path(directory))
            media_path = Path(media_path)
            if not media_path.is_file():
                raise FileNotFoundError(media_path)

            video_id = str(info.get("id") or "")
            title = str(info.get("title") or media_path.name)
            canonical_url = str(info.get("webpage_url") or url)
            mime_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"

            node = Node(name="Warrigal YouTube Media")
            repository.save_node(node)

            batch = Batch(node_id=node.node_id, label="YouTube media ingestion")
            repository.save_batch(batch)

            job = Job(
                name="YouTube media ingestion",
                node_id=node.node_id,
                batch_id=batch.batch_id,
            )
            repository.save_job(job)

            collection = Collection(
                name="YouTube Media Acquisitions",
                description="Original YouTube media and derived transcripts.",
            )
            repository.save_collection(collection)

            source = Source(
                source_type="youtube_media",
                locator=url,
                final_locator=canonical_url,
                title=title,
                metadata={
                    "video_id": video_id,
                    "channel": info.get("channel"),
                    "channel_id": info.get("channel_id"),
                    "upload_date": info.get("upload_date"),
                    "duration": info.get("duration"),
                    "original_filename": media_path.name,
                },
            )
            repository.save_source(source)

            service = AcquisitionService(repository, object_store)
            original = service.acquire_bytes(
                data=media_path.read_bytes(),
                source_id=source.source_id,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                method="youtube_media_download",
                mime_type=mime_type,
                original_filename=media_path.name,
                collection_id=collection.collection_id,
                metadata={
                    "video_id": video_id,
                    "video_url": canonical_url,
                },
            )

            kwargs = {}
            if transcriber is not None:
                kwargs["transcriber"] = transcriber

            result = ingest_audio_object(
                source_object_id=original.object_id,
                source_acquisition_id=original.acquisition_id,
                source_path=original.archive_path,
                source_url=canonical_url,
                source_title=title,
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
            print("=== WARRIGAL YOUTUBE MEDIA INGESTION ===")
            print(f"VIDEO:           {canonical_url}")
            print(f"TITLE:           {title}")
            print(f"ORIGINAL:        {original.object_id}")
            print(f"ORIGINAL SHA256: {original.sha256}")
            print(f"TRANSCRIPT:      {result.transcript_object_id}")
            print(f"ACQUISITION:     {result.transcript_acquisition_id}")
            print(f"SEGMENTS:        {len(result.transcript.segments)}")
            print(f"NEW PASSAGES:    {result.passage_count}")
            return 0
    finally:
        if db is not None:
            db.close()
