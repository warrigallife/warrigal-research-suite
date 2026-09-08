from __future__ import annotations

import re
from urllib.parse import urlparse

from warrigal.acquisition.instagram import ingest_instagram_post, ingest_instagram_profile
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


def instagram_shortcode(value: str) -> str:
    """Accept a shortcode or an Instagram post/reel URL."""
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Expected an Instagram shortcode or post URL.")
    if parsed.hostname not in {"instagram.com", "www.instagram.com"}:
        raise ValueError("Expected an Instagram URL.")

    match = re.fullmatch(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)/?", parsed.path)
    if not match:
        raise ValueError("Expected an Instagram post, reel, or TV URL.")
    return match.group(1)


def run_ingest_instagram(value: str, *, username: str) -> int:
    """Ingest one Instagram post using an existing saved session."""
    import instaloader

    shortcode = instagram_shortcode(value)
    loader = instaloader.Instaloader(
        dirname_pattern="{target}",
        filename_pattern="{shortcode}",
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=True,
        compress_json=False,
        post_metadata_txt_pattern="",
        max_connection_attempts=1,
    )

    loader.load_session_from_file(username)
    raw_post = instaloader.Post.from_shortcode(loader.context, shortcode)

    db = initialize_database()
    try:
        repository = WarrigalRepository(db)
        object_store = ObjectStore()

        node = Node(name="Warrigal Instagram")
        repository.save_node(node)

        batch = Batch(
            node_id=node.node_id,
            label="Instagram post ingestion",
        )
        repository.save_batch(batch)

        job = Job(
            name="Instagram post ingestion",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)

        collection = Collection(
            name="Instagram Acquisitions",
            description="Instagram evidence preserved by Warrigal.",
        )
        repository.save_collection(collection)

        result = ingest_instagram_post(
            raw_post,
            downloader=loader,
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
        )

        print()
        print("=== WARRIGAL INSTAGRAM INGESTION ===")
        print(f"POST:           {result['post'].url}")
        print(f"SNAPSHOT:       {result['snapshot'].object_id}")
        print(f"ACQUISITION:    {result['snapshot'].acquisition_id}")
        print(f"EVIDENCE FILES: {len(result['evidence'])}")
        for evidence in result["evidence"]:
            print(f"  OBJECT: {evidence.object_id}")
            print(f"  SHA256: {evidence.sha256}")
        return 0
    finally:
        db.close()


def run_ingest_instagram_profile(
    profile_username: str, *, username: str, max_posts: int = 3,
    resume: bool = False,
) -> int:
    """Ingest a bounded number of posts using an existing saved session."""
    import instaloader

    if max_posts < 0:
        raise ValueError("max_posts must be non-negative")
    if max_posts == 0:
        print("No posts requested.")
        return 0

    loader = instaloader.Instaloader(
        dirname_pattern="{target}",
        filename_pattern="{shortcode}",
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=True,
        compress_json=False,
        post_metadata_txt_pattern="",
        max_connection_attempts=1,
    )
    loader.load_session_from_file(username)
    requested_username = profile_username.lstrip("@").lower()
    authenticated_username = loader.test_login()

    if (
        authenticated_username is not None
        and requested_username == authenticated_username.lower()
    ):
        profile = instaloader.Profile.own_profile(loader.context)
    else:
        profile = instaloader.Profile.from_username(
            loader.context, requested_username
        )

    db = initialize_database()
    try:
        repository = WarrigalRepository(db)
        object_store = ObjectStore()
        node = Node(name="Warrigal Instagram")
        repository.save_node(node)
        batch = Batch(
            node_id=node.node_id, label="Instagram profile ingestion"
        )
        repository.save_batch(batch)
        job = Job(
            name="Instagram profile ingestion",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)
        collection = Collection(
            name="Instagram Acquisitions",
            description="Instagram evidence preserved by Warrigal.",
        )
        repository.save_collection(collection)

        results = ingest_instagram_profile(
            profile,
            downloader=loader,
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
            max_posts=max_posts,
            resume=resume,
        )

        print()
        print("=== WARRIGAL INSTAGRAM PROFILE INGESTION ===")
        print(f"PROFILE:        {profile.username}")
        print(f"POSTS INGESTED: {len(results)}")
        if resume:
            print(f"POSTS SKIPPED:  {getattr(results, 'skipped', 0)}")
        if hasattr(results, "attempted"):
            print(f"POSTS ATTEMPTED: {results.attempted}")
            print(f"POSTS SUCCEEDED: {results.succeeded}")
            print(f"POSTS FAILED:    {results.failed}")
        for result in results:
            print(f"  POST: {result['post'].url}")
            print(f"  SNAPSHOT OBJECT:      {result['snapshot'].object_id}")
            print(f"  SNAPSHOT ACQUISITION: {result['snapshot'].acquisition_id}")
            print(f"  SNAPSHOT DEDUP:       {result['snapshot'].deduplicated}")
            print(f"  EVIDENCE FILES:       {len(result['evidence'])}")

            for evidence in result["evidence"]:
                print(f"    EVIDENCE OBJECT:      {evidence.object_id}")
                print(f"    EVIDENCE ACQUISITION: {evidence.acquisition_id}")
                print(f"    EVIDENCE DEDUP:       {evidence.deduplicated}")
        if hasattr(results, "failures") and results.failures:
            print()
            print("=== INSTAGRAM POST FAILURES ===")
            for failure in results.failures:
                print(f"  POST: {failure['source_url'] or failure['shortcode'] or 'unknown'}")
                print(f"  ERROR: {failure['error_type']}: {failure['message']}")

        return 1 if getattr(results, "failed", 0) else 0
    finally:
        db.close()
