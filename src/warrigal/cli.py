from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from warrigal.acquisition.crawler import WebCrawler
from warrigal.acquisition.content import (
    extract_html_content,
    extract_pdf_content,
)
from warrigal.acquisition.links import extract_links
from warrigal.acquisition.service import AcquisitionService
from warrigal.audio_cli import run_ingest_audio
from warrigal.video_cli import run_ingest_video
from warrigal.youtube_media_cli import run_ingest_youtube_media
from warrigal.acquisition.youtube import ingest_video_transcript, resolve_youtube_channel
from warrigal.acquisition.youtube_comments import ingest_youtube_comments
from warrigal.acquisition.youtube_comment_campaign import (
    run_youtube_comment_campaign,
)
from warrigal.acquisition.youtube_comment_index import (
    comments_by_author,
    find_youtube_comment_authors,
    index_archived_youtube_comments,
)
from warrigal.acquisition.youtube_posts import ingest_youtube_posts
from warrigal.acquisition.youtube_post_comments import (
    ingest_youtube_post_comments,
    resolve_post_id,
    run_post_comment_campaign,
)
from warrigal.acquisition.youtube_channel_workflow import (
    run_youtube_channel_workflow,
)
from warrigal.instagram_cli import run_ingest_instagram, run_ingest_instagram_profile
from warrigal.acquisition.web import WebFetcher
from warrigal.database import initialize_database
from warrigal.config import CONFIG
from warrigal.doctor import run_doctor
from warrigal.archive_health import run_archive_health
from warrigal.workflows import actions_for, build_workflow_plan
from warrigal.models import Batch, Collection, Job, Node, Passage as PassageRecord, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.retrieval.passages import passages_from_rows, split_into_passages
from warrigal.retrieval.search import search_passages
from warrigal.retrieval.jufe_archive_search import (
    export_jufe_search,
    load_triggers,
    search_jufe_archive,
)

def build_parser() -> argparse.ArgumentParser:
    """Build Warrigal's command-line interface."""

    parser = argparse.ArgumentParser(
        prog="warrigal",
        description="Warrigal Research Suite",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "doctor",
        help="Check Warrigal paths, dependencies, tools, and configured models.",
    )
    archive_health_parser = subparsers.add_parser(
        "archive-health",
        help="Report database coverage and missing or damaged archive objects.",
    )
    archive_health_parser.add_argument(
        "--verify-hashes",
        action="store_true",
        help="Read and SHA-256 verify every archived object (slower).",
    )
    plan_source_parser = subparsers.add_parser(
        "plan-source",
        help="Show the exact shared workflow plan without running it.",
    )
    plan_source_parser.add_argument(
        "source_type",
        choices=("Instagram", "YouTube", "Website", "Local Documents"),
    )
    plan_source_parser.add_argument("target", help="Profile name or source URL.")
    plan_source_parser.add_argument("--action", required=True)
    plan_source_parser.add_argument("--delay", type=float, default=3.0)

    acquire_parser = subparsers.add_parser(
        "acquire",
        help="Acquire and preserve a resource.",
    )

    acquire_parser.add_argument(
        "url",
        help="Public HTTP/HTTPS URL to acquire.",
    )

    ingest_pdf_parser = subparsers.add_parser(
        "ingest-pdf",
        help="Ingest a local PDF into the Warrigal research library.",
    )

    ingest_pdf_parser.add_argument(
        "path",
        help="Path to a local PDF file.",
    )

    subparsers.add_parser(
        "history",
        help="Show acquisition history.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a preserved Warrigal object.",
    )

    inspect_parser.add_argument(
        "object_id",
        help="Warrigal object ID to inspect.",
    )

    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover links from a public web page.",
    )

    discover_parser.add_argument(
        "url",
        help="Public HTTP/HTTPS URL to discover links from.",
    )

    crawl_parser = subparsers.add_parser(
        "crawl",
        help="Crawl public web pages within controlled boundaries.",
    )

    crawl_parser.add_argument(
        "url",
        help="Public HTTP/HTTPS URL to start crawling from.",
    )

    website_inventory_parser = subparsers.add_parser(
        "inventory-website-documents",
        help="Inventory direct PDF and ZIP links without acquiring their bodies.",
    )
    website_inventory_parser.add_argument("url", help="Public HTML index URL.")
    website_inventory_parser.add_argument("--output", required=True)

    website_verify_parser = subparsers.add_parser(
        "verify-website-manifest",
        help="Compare a website document manifest with its acquisition checkpoint.",
    )
    website_verify_parser.add_argument("manifest")
    website_verify_parser.add_argument("--checkpoint", required=True)


    youtube_parser = subparsers.add_parser(
        "ingest-youtube",
        help="Ingest transcript evidence from a YouTube video.",
    )

    youtube_parser.add_argument(
        "url",
        help="Public YouTube video URL to ingest.",
    )

    youtube_comments_parser = subparsers.add_parser(
        "ingest-youtube-comments",
        help="Archive bounded comments and index one target author.",
    )
    youtube_comments_parser.add_argument(
        "url",
        help="Public YouTube video URL whose comments will be collected.",
    )
    youtube_comments_parser.add_argument(
        "--target-author-id",
        help="Stable YouTube channel ID for the target comment author.",
    )
    youtube_comments_parser.add_argument(
        "--target-author-handle",
        help="Target handle such as @TFJ7; handle-only matches are provisional.",
    )
    youtube_comments_parser.add_argument(
        "--max-comments",
        type=int,
        default=1000,
        help="Maximum comments to collect from this video (default: 1000).",
    )

    youtube_comment_campaign_parser = subparsers.add_parser(
        "ingest-youtube-channel-comments",
        help="Checkpoint comment evidence across a bounded channel view.",
    )
    youtube_comment_campaign_parser.add_argument(
        "channel",
        help="Public YouTube channel videos URL.",
    )
    youtube_comment_campaign_parser.add_argument(
        "--target-author-id",
        required=True,
        help="Confirmed stable channel ID for the target comment author.",
    )
    youtube_comment_campaign_parser.add_argument(
        "--target-author-handle",
        help="Optional human-readable target handle for provenance.",
    )
    youtube_comment_campaign_parser.add_argument(
        "--checkpoint",
        required=True,
        help="JSON checkpoint path used to resume the campaign.",
    )
    youtube_comment_campaign_parser.add_argument(
        "--scan-videos",
        type=int,
        default=100,
        help="Maximum channel videos to discover (default: 100).",
    )
    youtube_comment_campaign_parser.add_argument(
        "--max-videos",
        type=int,
        default=5,
        help="Maximum unfinished videos to process this run (default: 5).",
    )
    youtube_comment_campaign_parser.add_argument(
        "--max-comments",
        type=int,
        default=1000,
        help="Maximum comments collected per video (default: 1000).",
    )

    subparsers.add_parser(
        "index-youtube-comments",
        help="Index comments from Warrigal's local YouTube snapshots.",
    )

    find_comment_authors_parser = subparsers.add_parser(
        "find-youtube-comment-authors",
        help="Find archived YouTube commenters by handle or stable ID.",
    )
    find_comment_authors_parser.add_argument(
        "query",
        help="Case-insensitive author handle, name, profile URL, or ID fragment.",
    )

    show_author_comments_parser = subparsers.add_parser(
        "show-youtube-comments-by-author",
        help="Show indexed comments from one exact handle or stable ID.",
    )
    show_author_comments_parser.add_argument(
        "identity",
        help="Exact stable author ID, handle, or archived profile URL.",
    )

    jufe_search_parser = subparsers.add_parser(
        "search-jufe-archive",
        help="Search indexed evidence with a reviewed JUFE trigger vocabulary.",
    )
    jufe_search_parser.add_argument("--triggers", required=True)
    jufe_search_parser.add_argument("--output", required=True)
    jufe_search_parser.add_argument("--max-results", type=int, default=500)

    youtube_posts_parser = subparsers.add_parser(
        "ingest-youtube-posts",
        help="Archive and index bounded YouTube Community posts.",
    )
    youtube_posts_parser.add_argument(
        "channel",
        help="Public YouTube channel URL or its /posts tab.",
    )
    youtube_posts_parser.add_argument(
        "--checkpoint",
        required=True,
        help="JSON checkpoint path used to deduplicate archived posts.",
    )
    youtube_posts_parser.add_argument(
        "--max-posts",
        type=int,
        default=100,
        help="Maximum posts collected this run (default: 100).",
    )
    youtube_posts_parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum Community-tab pages requested (default: 20).",
    )

    post_comments_parser = subparsers.add_parser(
        "ingest-youtube-post-comments",
        help="Archive and index one Community post's comment threads.",
    )
    post_comments_parser.add_argument(
        "post",
        help="Community post ID or its https://www.youtube.com/post/<id> URL.",
    )
    post_comments_parser.add_argument(
        "--checkpoint",
        required=True,
        help="JSON checkpoint path used to deduplicate archived comment/reply IDs.",
    )
    post_comments_parser.add_argument(
        "--max-continuation-fetches",
        type=int,
        default=None,
        help=(
            "Optional safety cap on continuation fetches for this post. "
            "Default is unlimited. Reaching it marks the post INCOMPLETE, "
            "never completed."
        ),
    )

    post_comments_campaign_parser = subparsers.add_parser(
        "ingest-youtube-post-comments-campaign",
        help=(
            "Refresh the Community-post feed, then archive and index comment "
            "threads for every post that is not already completed."
        ),
    )
    post_comments_campaign_parser.add_argument(
        "channel",
        help="Public YouTube channel /posts URL.",
    )
    post_comments_campaign_parser.add_argument(
        "--posts-checkpoint",
        required=True,
        help="Post-listing checkpoint JSON written/refreshed by ingest-youtube-posts.",
    )
    post_comments_campaign_parser.add_argument(
        "--comments-checkpoint",
        required=True,
        help="JSON checkpoint path used to deduplicate archived comment/reply IDs.",
    )
    post_comments_campaign_parser.add_argument(
        "--max-continuation-fetches",
        type=int,
        default=None,
        help=(
            "Optional safety cap on continuation fetches per post. Default "
            "is unlimited. Reaching it marks that post INCOMPLETE, never "
            "completed."
        ),
    )
    post_comments_campaign_parser.add_argument(
        "--skip-completed",
        action="store_true",
        help=(
            "Opt in to skipping posts already marked completed. Default "
            "behaviour revisits every known post, including previously "
            "completed ones, so newly added comments/replies are discovered."
        ),
    )

    youtube_channel_parser = subparsers.add_parser(
        "ingest-youtube-channel",
        help="Resume a complete public YouTube channel research workflow.",
    )
    youtube_channel_parser.add_argument("channel", help="Public YouTube channel URL.")
    youtube_channel_parser.add_argument("--checkpoint", required=True)
    youtube_channel_parser.add_argument("--posts-checkpoint", required=True)
    youtube_channel_parser.add_argument(
        "--scan-videos", type=int, default=0,
        help="Maximum videos to discover; 0 means all available videos.",
    )
    youtube_channel_parser.add_argument(
        "--max-videos", type=int, default=0,
        help="Maximum unfinished videos processed this run; 0 means all.",
    )
    youtube_channel_parser.add_argument(
        "--max-comments", type=int, default=0,
        help="Maximum comments per video; 0 collects all available comments.",
    )
    youtube_channel_parser.add_argument("--max-posts", type=int, default=1000)
    youtube_channel_parser.add_argument("--max-post-pages", type=int, default=100)
    youtube_channel_parser.add_argument(
        "--stage",
        action="append",
        choices=("inventory", "transcripts", "comments", "posts", "index"),
        help="Run only this layer; repeat for multiple layers. Default: all research layers.",
    )

    instagram_parser = subparsers.add_parser(
        "ingest-instagram",
        help="Ingest one Instagram post using a saved session.",
    )
    instagram_parser.add_argument(
        "post",
        help="Instagram shortcode or post/reel URL.",
    )
    instagram_parser.add_argument(
        "--username",
        required=True,
        help="Username of the existing saved Instaloader session.",
    )

    instagram_profile_parser = subparsers.add_parser(
        "ingest-instagram-profile",
        help="Ingest a bounded number of posts from an Instagram profile.",
    )
    instagram_profile_parser.add_argument(
        "profile", help="Instagram profile username.",
    )
    instagram_profile_parser.add_argument(
        "--username", required=True,
        help="Username of the existing saved Instaloader session.",
    )
    instagram_profile_parser.add_argument(
        "--max-posts", type=int, default=3,
        help="Maximum number of posts to ingest (default: 3).",
    )
    instagram_profile_parser.add_argument(
        "--resume", action="store_true",
        help="Skip posts with completed acquisition checkpoints.",
    )

    archive_parser = subparsers.add_parser(
        "ingest-archive",
        help="Recursively ingest PDFs from a local archive directory.",
    )

    archive_parser.add_argument(
        "path",
        help="Local archive directory containing PDFs.",
    )

    audio_parser = subparsers.add_parser(
        "ingest-audio",
        help="Archive and transcribe a local audio file.",
    )
    audio_parser.add_argument("path", help="Path to a local audio file.")
    audio_parser.add_argument(
        "--model",
        required=True,
        help="Path to a local whisper.cpp model.",
    )

    youtube_media_parser = subparsers.add_parser(
        "ingest-youtube-media",
        help="Download, archive, and transcribe a YouTube video.",
    )
    youtube_media_parser.add_argument("url", help="Public YouTube video URL.")
    youtube_media_parser.add_argument(
        "--model",
        default=str(CONFIG.whisper_model) if CONFIG.whisper_model else None,
        help=(
            "Path to a local whisper.cpp model. Defaults to the model in "
            "warrigal.local.toml or WARRIGAL_WHISPER_MODEL."
        ),
    )

    video_parser = subparsers.add_parser(
        "ingest-video",
        help="Archive and transcribe a local video file.",
    )
    video_parser.add_argument("path", help="Path to a local video file.")
    video_parser.add_argument(
        "--model",
        required=True,
        help="Path to a local whisper.cpp model.",
    )

    search_parser = subparsers.add_parser(
        "search",
        help="Search persistent Warrigal passages.",
    )

    search_parser.add_argument(
        "query",
        help="Question or search terms to find relevant evidence.",
    )

    search_parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.0,
        help="Minimum query coverage required, from 0.0 to 1.0.",
    )

    search_parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Maximum number of ranked results to return.",
    )

    manifest_parser = subparsers.add_parser(
        "acquire-manifest",
        help="Acquire a bounded number of resources from a collection manifest.",
    )
    manifest_parser.add_argument(
        "manifest",
        help="Path to a Warrigal collection manifest JSON file.",
    )
    manifest_parser.add_argument(
        "--checkpoint",
        required=True,
        help="Path to the persistent campaign checkpoint JSON file.",
    )
    manifest_parser.add_argument(
        "--max-resources",
        type=int,
        required=True,
        help="Maximum number of non-verified manifest resources to select.",
    )
    manifest_parser.add_argument(
        "--max-resource-bytes",
        type=int,
        default=None,
        help=(
            "Maximum expected size in bytes for any selected resource. "
            "Unknown-size and oversized resources are skipped."
        ),
    )
    manifest_parser.add_argument(
        "--retry-failures",
        type=int,
        default=0,
        help="Retry each failed resource individually this many times.",
    )
    manifest_parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=0.0,
        help="Initial delay before isolated retries; later delays double.",
    )
    manifest_parser.add_argument(
        "--read-timeout",
        type=float,
        default=30.0,
        help="HTTP read timeout in seconds for manifest resources.",
    )

    return parser

def run_acquire(url: str) -> int:
    """Acquire a public web resource and preserve it in Warrigal."""

    db = initialize_database()
    repository = WarrigalRepository(db)
    object_store = ObjectStore()

    node = Node(name="Warrigal CLI")
    repository.save_node(node)

    batch = Batch(
        node_id=node.node_id,
        label="CLI acquisition",
    )
    repository.save_batch(batch)

    job = Job(
        name="Public web acquisition",
        node_id=node.node_id,
        batch_id=batch.batch_id,
    )
    repository.save_job(job)

    collection = Collection(
        name="CLI Web Acquisitions",
        description="Resources acquired through the Warrigal CLI.",
    )
    repository.save_collection(collection)

    fetcher = WebFetcher()
    response = fetcher.fetch(url)

    source = Source(
        source_type="web",
        locator=response.requested_url,
        final_locator=response.final_url,
        metadata={
            "http_status": response.status,
            "content_type": response.content_type,
        },
    )
    repository.save_source(source)

    service = AcquisitionService(
        repository=repository,
        object_store=object_store,
    )

    result = service.acquire_bytes(
        data=response.data,
        source_id=source.source_id,
        job_id=job.job_id,
        node_id=node.node_id,
        batch_id=batch.batch_id,
        method="web",
        collection_id=collection.collection_id,
    )

    print()
    print("=== WARRIGAL ACQUISITION ===")
    print(f"URL:            {response.final_url}")
    print(f"OBJECT:         {result.object_id}")
    print(f"ACQUISITION:    {result.acquisition_id}")
    print(f"SHA-256:        {result.sha256}")
    print(f"SIZE:           {result.size_bytes}")
    print(f"ARCHIVE PATH:   {result.archive_path}")
    print(f"DEDUPLICATED:   {result.deduplicated}")
    print()
    print("WARRIGAL: acquisition complete")

    db.close()
    return 0

def run_ingest_pdf(path: str) -> int:
    """Ingest a local PDF into the persistent Warrigal research corpus."""

    pdf_path = Path(path).expanduser().resolve()

    if not pdf_path.is_file():
        print(f"WARRIGAL: PDF not found: {pdf_path}")
        return 1

    if pdf_path.suffix.lower() != ".pdf":
        print(f"WARRIGAL: not a PDF file: {pdf_path}")
        return 1

    data = pdf_path.read_bytes()

    db = initialize_database()
    repository = WarrigalRepository(db)
    object_store = ObjectStore()

    node = Node(name="Warrigal CLI")
    repository.save_node(node)

    batch = Batch(
        node_id=node.node_id,
        label="CLI PDF ingestion",
    )
    repository.save_batch(batch)

    job = Job(
        name="Local PDF ingestion",
        node_id=node.node_id,
        batch_id=batch.batch_id,
    )
    repository.save_job(job)

    collection = Collection(
        name="CLI PDF Library",
        description="Local PDFs ingested through the Warrigal CLI.",
    )
    repository.save_collection(collection)

    source = Source(
        source_type="file",
        locator=str(pdf_path),
        final_locator=str(pdf_path),
        metadata={
            "content_type": "application/pdf",
            "filename": pdf_path.name,
        },
    )
    repository.save_source(source)

    service = AcquisitionService(
        repository=repository,
        object_store=object_store,
    )

    acquisition_result = service.acquire_bytes(
        data=data,
        source_id=source.source_id,
        job_id=job.job_id,
        node_id=node.node_id,
        batch_id=batch.batch_id,
        method="local_pdf",
        mime_type="application/pdf",
        original_filename=pdf_path.name,
        collection_id=collection.collection_id,
        metadata={
            "path": str(pdf_path),
        },
    )

    content = extract_pdf_content(data)

    passages = split_into_passages(
        content.text,
        source_url=str(pdf_path),
        source_title=content.title or pdf_path.name,
        object_id=acquisition_result.object_id,
        acquisition_id=acquisition_result.acquisition_id,
    )

    for passage in passages:
        repository.save_passage(
            PassageRecord(
                object_id=acquisition_result.object_id,
                acquisition_id=acquisition_result.acquisition_id,
                passage_index=passage.index,
                text=passage.text,
                source_url=passage.source_url,
                source_title=passage.source_title,
            )
        )

    print()
    print("=== WARRIGAL PDF INGESTION ===")
    print(f"FILE:           {pdf_path}")
    print(f"TITLE:          {content.title or pdf_path.name}")
    print(f"OBJECT:         {acquisition_result.object_id}")
    print(f"ACQUISITION:    {acquisition_result.acquisition_id}")
    print(f"SHA-256:        {acquisition_result.sha256}")
    print(f"SIZE:           {acquisition_result.size_bytes}")
    print(f"ARCHIVE PATH:   {acquisition_result.archive_path}")
    print(f"DEDUPLICATED:   {acquisition_result.deduplicated}")
    print(f"PASSAGES:       {len(passages)}")
    print()
    print("WARRIGAL: PDF ingestion complete")

    db.close()
    return 0


def run_history() -> int:
    """Show Warrigal's acquisition history."""

    db = initialize_database()
    repository = WarrigalRepository(db)

    rows = repository.list_acquisitions()

    print()
    print("=== WARRIGAL ACQUISITION HISTORY ===")
    print(f"TOTAL ACQUISITIONS: {len(rows)}")
    print()

    for row in rows:
        source = repository.get_source(row["source_id"])
      
        print(f"ACQUISITION: {row['acquisition_id']}")
        print(f"OBJECT:      {row['object_id']}")
        print(f"SOURCE:      {row['source_id']}")

        if source is not None:
            print(f"URL:         {source['final_locator'] or source['locator']}")

        print(f"ACQUIRED:    {row['acquired_at']}")
        print()

    db.close()
    return 0

def run_inspect(object_id: str) -> int:
    """Inspect a preserved Warrigal object."""

    db = initialize_database()
    repository = WarrigalRepository(db)
    

    obj = repository.get_object(object_id)

    if obj is None:
        print(f"WARRIGAL: object not found: {object_id}")
        db.close()
        return 1

    acquisitions = repository.get_acquisitions_for_object(object_id)
    storage_locations = repository.get_storage_locations(object_id)

    print()
    print("=== WARRIGAL OBJECT INSPECTION ===")
    print(f"OBJECT:         {obj['object_id']}")
    print(f"SHA-256:        {obj['sha256']}")
    print(f"SIZE:           {obj['size_bytes']}")
    print(f"MIME TYPE:      {obj['mime_type']}")
    print(f"FILENAME:       {obj['original_filename']}")
    print(f"CREATED:        {obj['created_at']}")
    print()
    print(f"ACQUISITIONS:   {len(acquisitions)}")

    for acquisition in acquisitions:
        source = repository.get_source(acquisition["source_id"])

        print()
        print(f"  ACQUISITION: {acquisition['acquisition_id']}")
        print(f"  SOURCE:      {acquisition['source_id']}")

        if source is not None:
            print(f"  URL:         {source['final_locator'] or source['locator']}")

        print(f"  METHOD:      {acquisition['method']}")
        print(f"  STATUS:      {acquisition['status']}")
        print(f"  ACQUIRED:    {acquisition['acquired_at']}")

    print()
    print(f"STORAGE COPIES: {len(storage_locations)}")

    for storage in storage_locations:
        print()
        print(f"  STORAGE:     {storage['storage_id']}")
        print(f"  TYPE:        {storage['location_type']}")
        print(f"  PATH:        {storage['path']}")
        print(f"  VERIFIED:    {storage['verified_at']}")

    db.close()
    return 0

def run_discover(url: str) -> int:
    """Discover links from a public web page."""

    fetcher = WebFetcher()
    response = fetcher.fetch(url)

    links = extract_links(
        response.data,
        response.final_url,
    )

    print()
    print("=== WARRIGAL LINK DISCOVERY ===")
    print(f"URL:   {response.final_url}")
    print(f"LINKS: {len(links)}")
    print()

    for link in links:
        print(link)

    return 0


def run_inventory_website_documents(url: str, *, output_path: str) -> int:
    """Write a reviewable PDF/ZIP inventory without acquiring resources."""

    from warrigal.acquisition.manifest_inventory import build_collection_manifest

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    slug = output.stem.removesuffix("-website-documents")
    fetcher = WebFetcher()

    def safe_size_probe(resource_url: str) -> int | None:
        from warrigal.acquisition.manifest_inventory import head_content_length
        try:
            return head_content_length(resource_url, fetcher=fetcher)
        except Exception:
            return None

    manifest = build_collection_manifest(
        index_url=url,
        manifest_id=f"website-{slug}",
        name=f"Website documents: {slug}",
        description=f"Direct PDF and ZIP resources inventoried from {url}",
        discovery_provenance={
            "method": "warrigal_direct_index_inventory",
            "index_url": url,
        },
        fetcher=fetcher,
        size_probe=safe_size_probe,
    )
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(manifest.to_json(), encoding="utf-8")
    temporary.replace(output)

    print("=== WARRIGAL WEBSITE DOCUMENT INVENTORY ===")
    print(f"INDEX:     {url}")
    print(f"RESOURCES: {len(manifest.resources)}")
    print(f"OUTPUT:    {output}")
    def readable_size(size: int | None) -> str:
        if size is None:
            return "Unknown"
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return (
                    f"{value:.1f} {unit}"
                    if unit != "B"
                    else f"{int(value)} B"
                )
            value /= 1024
        return f"{size} B"

    for resource in manifest.resources:
        size = resource.expected_size_bytes
        print(
            f"{resource.media_type:20} "
            f"{readable_size(size):>12} {resource.url}"
        )
    return 0


def run_verify_website_manifest(
    manifest_path: str,
    *,
    checkpoint_path: str,
) -> int:
    """Report manifest acquisition coverage without downloading anything."""

    from warrigal.acquisition.manifest import CollectionManifest
    from warrigal.acquisition.manifest_runner import ManifestCheckpointStore

    manifest_file = Path(manifest_path).expanduser().resolve()
    checkpoint_file = Path(checkpoint_path).expanduser().resolve()
    manifest = CollectionManifest.from_json(manifest_file.read_text(encoding="utf-8"))
    checkpoint = ManifestCheckpointStore(checkpoint_file).load(manifest.manifest_id)
    statuses = {
        resource.url: checkpoint.get(resource.url, {}).get("status", "pending")
        for resource in manifest.resources
    }
    complete_statuses = {"acquired", "archived", "verified", "skipped_duplicate"}
    completed = sum(status in complete_statuses for status in statuses.values())
    failed = sum(status == "failed" for status in statuses.values())
    pending = len(statuses) - completed - failed
    unknown_size = sum(
        resource.expected_size_bytes is None
        for resource in manifest.resources
    )
    print("=== WARRIGAL WEBSITE MANIFEST VERIFICATION ===")
    print(f"MANIFEST:  {manifest_file}")
    print(f"CHECKPOINT:{checkpoint_file}")
    print(f"TOTAL:     {len(statuses)}")
    print(f"COMPLETED: {completed}")
    print(f"FAILED:    {failed}")
    print(f"PENDING:   {pending}")
    print(f"UNKNOWN SIZE: {unknown_size}")
    for url, status in statuses.items():
        print(f"{status:20} {url}")
    return 1 if failed else 0

def run_crawl(url: str) -> int:
    """Crawl public web pages within controlled boundaries."""

    db = initialize_database()
    repository = WarrigalRepository(db)
    object_store = ObjectStore()
    node = Node(name="Warrigal Crawler")
    repository.save_node(node)
    batch = Batch(
        node_id=node.node_id,
        label="Web crawl",
    )
    repository.save_batch(batch)
    job = Job(
        name="Public web crawl",
        node_id=node.node_id,
        batch_id=batch.batch_id,
    )
    repository.save_job(job)

    collection = Collection(
        name="Web Crawl Acquisitions",
        description="Resources preserved during a Warrigal web crawl.",
    )
    repository.save_collection(collection)
    service = AcquisitionService(
        repository=repository,
        object_store=object_store,
    )
    fetcher = WebFetcher()

    crawler = WebCrawler(
        fetcher=fetcher,
        max_pages=10,
        same_domain=True,
    )

    result = crawler.crawl(url)

    for response in result.responses:
        source = Source(
            source_type="web",
            locator=response.requested_url,
            final_locator=response.final_url,
            metadata={
                "http_status": response.status,
                "content_type": response.content_type,
            },
        )
        repository.save_source(source)
        acquisition_result = service.acquire_bytes(
            data=response.data,
            source_id=source.source_id,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            method="web_crawl",
            mime_type=response.content_type,
            collection_id=collection.collection_id,
            http_status=response.status,
            metadata={
                "requested_url": response.requested_url,
                "final_url": response.final_url,
            },
        )
        if repository.object_has_passages(acquisition_result.object_id):
            continue

        if response.content_type == "text/html":
            content = extract_html_content(response.data)
        elif response.content_type == "application/pdf":
            content = extract_pdf_content(response.data)
        else:
            continue

        passages = split_into_passages(
            content.text,
            source_url=response.final_url,
            source_title=content.title,
            object_id=acquisition_result.object_id,
            acquisition_id=acquisition_result.acquisition_id,
        )

        for passage in passages:
            repository.save_passage(
                PassageRecord(
                    object_id=acquisition_result.object_id,
                    acquisition_id=acquisition_result.acquisition_id,
                    passage_index=passage.index,
                    text=passage.text,
                    source_url=passage.source_url,
                    source_title=passage.source_title,
                )
            )
        if passages:
            passage = passages[0]

            print()
            print("=== WARRIGAL REAL PROVENANCE BRIDGE ===")
            print("TITLE:", passage.source_title)
            print("SOURCE:", passage.source_url)
            print("OBJECT:", passage.object_id)
            print("ACQUISITION:", passage.acquisition_id)
            print("EVIDENCE:", passage.text[:300])

    print()
    print("=== WARRIGAL WEB CRAWL ===")
    print(f"START:      {result.start_url}")
    print(f"VISITED:    {len(result.visited)}")
    print(f"DISCOVERED: {len(result.discovered)}")
    print()

    print("VISITED URLS:")
    for visited_url in result.visited:
        print(f"  {visited_url}")

    print()
    print("DISCOVERED URLS:")
    for discovered_url in result.discovered:
        print(f"  {discovered_url}")

    db.close()
    return 0


def run_ingest_archive(path: str) -> int:
    """Recursively ingest PDFs from a local archive directory."""

    from pathlib import Path

    from warrigal.acquisition.archive import ingest_pdf_archive
    from warrigal.models import Batch, Collection, Job, Node
    from warrigal.object_store import ObjectStore

    archive_root = Path(path).expanduser().resolve()

    db = initialize_database()
    repository = WarrigalRepository(db)

    try:
        node = Node(name="Warrigal CLI")
        repository.save_node(node)

        batch = Batch(
            node_id=node.node_id,
            label=f"Archive ingestion: {archive_root}",
        )
        repository.save_batch(batch)

        job = Job(
            name="Local PDF archive ingestion",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)

        collection = Collection(
            name=f"Archive: {archive_root.name}",
            description=f"PDFs recursively ingested from {archive_root}.",
        )
        repository.save_collection(collection)

        result = ingest_pdf_archive(
            archive_root,
            repository=repository,
            object_store=ObjectStore(),
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
        )

        print()
        print("=== WARRIGAL ARCHIVE INGESTION ===")
        print(f"ROOT: {result.root}")
        print()

        for file_result in result.files:
            print(
                f"{file_result.status.upper():9} "
                f"{file_result.path}"
            )

            if file_result.error is not None:
                print(f"          ERROR: {file_result.error}")

        print()
        print("SUMMARY")
        print(f"DISCOVERED: {result.discovered_count}")
        print(f"INGESTED:   {result.ingested_count}")
        print(f"DUPLICATE:  {result.duplicate_count}")
        print(f"NO TEXT:    {result.no_text_count}")
        print(f"FAILED:     {result.failed_count}")
        print(f"PASSAGES:   {result.passage_count}")

        return 1 if result.failed_count else 0

    finally:
        db.close()


def run_ingest_youtube(url: str) -> int:
    """Ingest public YouTube transcript evidence into Warrigal."""

    db = initialize_database()
    repository = WarrigalRepository(db)
    object_store = ObjectStore()

    node = Node(name="Warrigal YouTube")
    repository.save_node(node)

    batch = Batch(
        node_id=node.node_id,
        label="YouTube transcript ingestion",
    )
    repository.save_batch(batch)

    job = Job(
        name="YouTube transcript ingestion",
        node_id=node.node_id,
        batch_id=batch.batch_id,
    )
    repository.save_job(job)

    collection = Collection(
        name="YouTube Acquisitions",
        description="YouTube evidence preserved by Warrigal.",
    )
    repository.save_collection(collection)

    result = ingest_video_transcript(
        url,
        repository=repository,
        object_store=object_store,
        job_id=job.job_id,
        node_id=node.node_id,
        batch_id=batch.batch_id,
        collection_id=collection.collection_id,
    )

    print()
    print("=== WARRIGAL YOUTUBE INGESTION ===")
    print(f"VIDEO ID:       {result.video_id}")
    print(f"OBJECT:         {result.object_id}")
    print(f"ACQUISITION:    {result.acquisition_id}")
    print(f"SHA256:         {result.sha256}")
    print(f"PASSAGES:       {result.passage_count}")
    print(f"DEDUPLICATED:   {result.deduplicated}")

    db.close()
    return 0


def run_ingest_youtube_channel(
    channel_url: str,
    *,
    checkpoint_path: str,
    posts_checkpoint_path: str,
    scan_videos: int = 0,
    max_videos: int = 0,
    max_comments: int = 0,
    max_posts: int = 1000,
    max_post_pages: int = 100,
    stages: list[str] | tuple[str, ...] | None = None,
) -> int:
    """Preserve a channel inventory, transcripts, comments, and posts."""

    try:
        identity = resolve_youtube_channel(channel_url)
    except ValueError as exc:
        print("=== WARRIGAL YOUTUBE CHANNEL ERROR ===")
        print(f"SOURCE: {channel_url}")
        print(f"ERROR:  {exc}")
        print("NO WORKFLOW RECORDS WERE CREATED")
        return 1

    channel_url = identity.canonical_url
    db = initialize_database()
    repository = WarrigalRepository(db)
    try:
        object_store = ObjectStore()
        node = Node(name="Warrigal YouTube Channel")
        repository.save_node(node)
        batch = Batch(node_id=node.node_id, label="YouTube channel workflow")
        repository.save_batch(batch)
        job = Job(
            name="YouTube channel workflow",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)
        collection = Collection(
            name="YouTube Channel Evidence",
            description="Public YouTube channel evidence preserved by Warrigal.",
        )
        repository.save_collection(collection)
        result = run_youtube_channel_workflow(
            channel_url,
            checkpoint_path=checkpoint_path,
            posts_checkpoint_path=posts_checkpoint_path,
            scan_videos=scan_videos,
            max_videos=max_videos,
            max_comments=max_comments,
            max_posts=max_posts,
            max_post_pages=max_post_pages,
            stages=tuple(stages or ("transcripts", "comments", "posts", "index")),
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
        )
        print("=== WARRIGAL YOUTUBE CHANNEL WORKFLOW ===")
        print(f"CHANNEL:                 {result.channel_url}")
        print(f"CHANNEL ID:              {identity.channel_id}")
        print(f"CHANNEL NAME:            {identity.title}")
        print(f"INVENTORY OBJECT:        {result.inventory_object_id}")
        print(f"VIDEOS DISCOVERED:       {result.discovered_count}")
        print(f"VIDEOS SELECTED:         {result.selected_count}")
        print(f"VIDEOS COMPLETED:        {result.completed_count}")
        print(f"VIDEOS FAILED:           {result.failed_count}")
        print(f"TRANSCRIPTS UNAVAILABLE: {result.unavailable_transcript_count}")
        print(f"TRANSCRIPTS ACQUIRED:    {result.acquired_transcript_count}")
        print(f"COMMENTS PRESERVED:      {result.comments_collected}")
        print(f"COMMENT PASSAGES ADDED:  {result.indexed_comment_count}")
        print(f"COMMENT INDEX SCOPE:     {result.comment_index_scope}")
        print(f"COMMUNITY POSTS:         {result.community_posts_status}")
        print(f"POSTS COLLECTED:         {result.community_posts_collected}")
        print(f"POSTS NEW:               {result.community_posts_new}")
        print(f"POST SNAPSHOT REUSED:    {result.community_posts_deduplicated}")
        print(f"CHECKPOINT:              {Path(checkpoint_path).expanduser().resolve()}")
        failed = result.failed_count or (
            "posts" in tuple(stages or ("transcripts", "comments", "posts", "index"))
            and result.community_posts_status == "failed"
        )
        return 1 if failed else 0
    finally:
        db.close()


def run_ingest_youtube_comments(
    url: str,
    *,
    target_author_id: str | None = None,
    target_author_handle: str | None = None,
    max_comments: int = 1000,
) -> int:
    """Archive public comments and index statements by one target author."""

    if not target_author_id and not target_author_handle:
        raise ValueError(
            "Provide --target-author-id or --target-author-handle"
        )
    if max_comments < 1:
        raise ValueError("--max-comments must be at least 1")

    db = initialize_database()
    repository = WarrigalRepository(db)
    try:
        object_store = ObjectStore()
        node = Node(name="Warrigal YouTube Comments")
        repository.save_node(node)
        batch = Batch(
            node_id=node.node_id,
            label="YouTube comment ingestion",
        )
        repository.save_batch(batch)
        job = Job(
            name="YouTube comment ingestion",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)
        collection = Collection(
            name="YouTube Comment Evidence",
            description="Public YouTube comments preserved by Warrigal.",
        )
        repository.save_collection(collection)

        result = ingest_youtube_comments(
            url,
            target_author_id=target_author_id,
            target_author_handle=target_author_handle,
            max_comments=max_comments,
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
        )

        print("=== WARRIGAL YOUTUBE COMMENT INGESTION ===")
        print(f"VIDEO:          {result.video_id} — {result.video_title}")
        print(f"OBJECT:         {result.object_id}")
        print(f"ACQUISITION:    {result.acquisition_id}")
        print(f"COMMENTS:       {result.collected_count}")
        print(f"TARGET MATCHES: {result.matched_count}")
        print(f"THREAD CONTEXT: {result.context_count}")
        print(f"NEW PASSAGES:   {result.indexed_count}")
        print(f"MATCH BASIS:    {result.match_basis}")
        if result.matched_author_ids:
            print(
                "AUTHOR IDS:     "
                + ", ".join(result.matched_author_ids)
            )
        if result.match_basis == "author_handle_provisional":
            print("IDENTITY:       PROVISIONAL — confirm stable author ID")
        elif result.match_basis == "author_id":
            print("IDENTITY:       EXPLICIT AUTHOR ID")
        else:
            print("IDENTITY:       NO MATCH FOUND")
        print(f"DEDUPLICATED:   {result.deduplicated}")
        return 0
    finally:
        db.close()


def run_ingest_youtube_channel_comments(
    channel_url: str,
    *,
    target_author_id: str,
    target_author_handle: str | None,
    checkpoint_path: str,
    scan_videos: int,
    max_videos: int,
    max_comments: int,
) -> int:
    """Run a resumable bounded comment campaign over channel videos."""

    if scan_videos < 1 or max_videos < 1 or max_comments < 1:
        raise ValueError("YouTube comment campaign bounds must be at least 1")

    db = initialize_database()
    repository = WarrigalRepository(db)
    try:
        object_store = ObjectStore()
        node = Node(name="Warrigal YouTube Comment Campaign")
        repository.save_node(node)
        batch = Batch(
            node_id=node.node_id,
            label="YouTube channel comment campaign",
        )
        repository.save_batch(batch)
        job = Job(
            name="YouTube channel comment campaign",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)
        collection = Collection(
            name="YouTube Comment Evidence",
            description="Public YouTube comments preserved by Warrigal.",
        )
        repository.save_collection(collection)

        result = run_youtube_comment_campaign(
            channel_url,
            target_author_id=target_author_id,
            target_author_handle=target_author_handle,
            checkpoint_path=checkpoint_path,
            scan_videos=scan_videos,
            max_videos=max_videos,
            max_comments=max_comments,
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
        )

        print("=== WARRIGAL YOUTUBE COMMENT CAMPAIGN ===")
        print(f"CHANNEL:        {channel_url}")
        print(f"TARGET ID:      {target_author_id}")
        print(f"CHECKPOINT:     {Path(checkpoint_path).expanduser().resolve()}")
        for item in result.items:
            if item.status in {"completed", "failed"}:
                print(
                    f"{item.status:20} "
                    f"matches={item.matched_count:<4} "
                    f"context={item.context_count:<4} "
                    f"{item.url}"
                )
                if item.error:
                    print(f"  ERROR: {item.error}")

        print("=== CAMPAIGN RUN COMPLETE ===")
        print(f"DISCOVERED:     {result.discovered_count}")
        print(f"SELECTED:       {result.selected_count}")
        print(f"COMPLETED:      {result.completed_count}")
        print(f"FAILED:         {result.failed_count}")
        print(f"TARGET MATCHES: {result.matched_count}")
        print(f"THREAD CONTEXT: {result.context_count}")
        if result.selected_count == 0:
            print("NO UNFINISHED VIDEOS IN SCANNED RANGE")
        return 1 if result.failed_count else 0
    finally:
        db.close()


def run_index_youtube_comments() -> int:
    """Index all comments already preserved in Warrigal's local archive."""

    db = initialize_database()
    repository = WarrigalRepository(db)
    try:
        result = index_archived_youtube_comments(
            repository=repository,
            object_store=ObjectStore(),
        )
        print("=== WARRIGAL YOUTUBE COMMENT INDEX ===")
        print(f"OBJECTS SCANNED:   {result.objects_scanned}")
        print(f"VALID SNAPSHOTS:   {result.snapshots_indexed}")
        print(f"COMMENTS SEEN:     {result.comments_seen}")
        print(f"ALREADY INDEXED:   {result.already_indexed}")
        print(f"PASSAGES CREATED:  {result.passages_created}")
        print(f"INVALID SNAPSHOTS: {result.invalid_snapshots}")
        return 1 if result.invalid_snapshots else 0
    finally:
        db.close()


def run_ingest_youtube_posts(
    channel_url: str,
    *,
    checkpoint_path: str,
    max_posts: int = 100,
    max_pages: int = 20,
) -> int:
    """Archive and index a bounded public YouTube Community-post view."""

    if max_posts < 1 or max_pages < 1:
        raise ValueError("YouTube post bounds must be at least 1")
    db = initialize_database()
    repository = WarrigalRepository(db)
    try:
        object_store = ObjectStore()
        node = Node(name="Warrigal YouTube Posts")
        repository.save_node(node)
        batch = Batch(node_id=node.node_id, label="YouTube post ingestion")
        repository.save_batch(batch)
        job = Job(
            name="YouTube post ingestion",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)
        collection = Collection(
            name="YouTube Community Post Evidence",
            description="Public YouTube Community posts preserved by Warrigal.",
        )
        repository.save_collection(collection)
        result = ingest_youtube_posts(
            channel_url,
            checkpoint_path=checkpoint_path,
            max_posts=max_posts,
            max_pages=max_pages,
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
        )
        print("=== WARRIGAL YOUTUBE COMMUNITY POSTS ===")
        print(f"CHANNEL:          {result.channel_id} — {result.channel_title}")
        print(f"OBJECT:           {result.object_id}")
        print(f"ACQUISITION:      {result.acquisition_id}")
        print(f"POSTS COLLECTED:  {result.collected_count}")
        print(f"NEW POSTS:        {result.new_count}")
        print(f"PASSAGES CREATED: {result.indexed_count}")
        print(f"DEDUPLICATED:     {result.deduplicated}")
        if result.new_count == 0:
            print("NO NEW POSTS")
        return 0
    finally:
        db.close()


def run_ingest_youtube_post_comments(
    post: str, *, checkpoint_path: str, max_continuation_fetches: int | None = None
) -> int:
    """Archive and index one Community post's top-level comments and replies."""

    if max_continuation_fetches is not None and max_continuation_fetches < 1:
        raise ValueError("--max-continuation-fetches must be at least 1")
    post_id = resolve_post_id(post)
    db = initialize_database()
    repository = WarrigalRepository(db)
    try:
        object_store = ObjectStore()
        node = Node(name="Warrigal YouTube Post Comments")
        repository.save_node(node)
        batch = Batch(node_id=node.node_id, label="YouTube post-comment ingestion")
        repository.save_batch(batch)
        job = Job(
            name="YouTube post-comment ingestion",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)
        collection = Collection(
            name="YouTube Community Post Comment Evidence",
            description="Public YouTube Community-post comment threads preserved by Warrigal.",
        )
        repository.save_collection(collection)
        result = ingest_youtube_post_comments(
            post_id,
            checkpoint_path=checkpoint_path,
            max_continuation_fetches=max_continuation_fetches,
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
        )
        print("=== WARRIGAL YOUTUBE POST COMMENTS ===")
        print(f"POST:              {result.post_id}")
        print(f"POST URL:          {result.post_url}")
        print(f"OBJECT:            {result.object_id}")
        print(f"ACQUISITION:       {result.acquisition_id}")
        print(f"SHA256:            {result.sha256}")
        print(f"STATUS:            {result.status}")
        print(f"REASONS:           {', '.join(result.reasons) or 'none'}")
        print(f"VISIBLE COUNT:     {result.counts.visible_comment_count}")
        print(f"VISIBLE BASIS:     {result.counts.visible_count_basis}")
        print(f"TOP-LEVEL COUNT:   {result.counts.top_level_count}")
        print(f"REPLY COUNT:       {result.counts.reply_count}")
        print(f"TOTAL COUNT:       {result.counts.total_count}")
        print(f"COUNT MATCH:       {result.counts.count_match}")
        print(f"STABLE-ID COUNT:   {result.identity_coverage.stable_id_count}")
        print(f"PROVISIONAL COUNT: {result.identity_coverage.unresolved_provisional_count}")
        print(f"IDENTITY COMPLETE: {result.identity_coverage.stable_id_coverage_complete}")
        print(f"NEW:               {result.new_count}")
        print(f"INDEXED:           {result.indexed_count}")
        print(f"CONFIRMED TOM:     {result.target_author_comment_count}")
        print(f"DEDUPLICATED:      {result.deduplicated}")
        if result.status == "failed":
            return 1
        if result.status == "incomplete":
            return 2
        return 0
    finally:
        db.close()


def run_ingest_youtube_post_comments_campaign(
    channel_url: str,
    *,
    posts_checkpoint_path: str,
    comments_checkpoint_path: str,
    max_continuation_fetches: int | None = None,
    skip_completed: bool = False,
) -> int:
    """Refresh the Community-post feed, then ingest comment threads for
    every currently-known post. By default, previously completed posts are
    revisited too; pass skip_completed=True to opt into skipping them."""

    if max_continuation_fetches is not None and max_continuation_fetches < 1:
        raise ValueError("--max-continuation-fetches must be at least 1")

    db = initialize_database()
    repository = WarrigalRepository(db)
    try:
        object_store = ObjectStore()
        node = Node(name="Warrigal YouTube Post Comment Campaign")
        repository.save_node(node)
        batch = Batch(node_id=node.node_id, label="YouTube post-comment campaign")
        repository.save_batch(batch)
        job = Job(
            name="YouTube post-comment campaign",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)
        collection = Collection(
            name="YouTube Community Post Comment Evidence",
            description="Public YouTube Community-post comment threads preserved by Warrigal.",
        )
        repository.save_collection(collection)
        result = run_post_comment_campaign(
            channel_url,
            posts_checkpoint_path=posts_checkpoint_path,
            comments_checkpoint_path=comments_checkpoint_path,
            max_continuation_fetches=max_continuation_fetches,
            skip_completed=skip_completed,
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
        )
        print("=== WARRIGAL YOUTUBE POST-COMMENT CAMPAIGN ===")
        print(f"CHANNEL:            {channel_url}")
        print(f"FEED COVERAGE:      {result.feed_coverage_status}")
        print(f"FEED REASONS:       {', '.join(result.feed_coverage_reasons) or 'none'}")
        print(f"KNOWN BEFORE:       {len(result.known_before_refresh)}")
        print(f"NEWLY DISCOVERED:   {len(result.newly_discovered)}")
        for post_id in result.newly_discovered:
            print(f"  NEW POST: {post_id}")
        print(f"ATTEMPTED:          {len(result.attempted)}")
        for item in result.items:
            print(
                f"{item.status:10} {item.post_id}  "
                f"new={item.new_count} tom={item.target_author_comment_count} "
                f"reasons={', '.join(item.reasons) or 'none'}"
            )
        print("=== CAMPAIGN COMPLETE ===")
        print(f"COMPLETED: {len(result.completed)}")
        print(f"INCOMPLETE:{len(result.incomplete)}")
        print(f"FAILED:    {len(result.failed)}")
        if result.failed:
            return 1
        if result.incomplete or result.feed_coverage_status == "incomplete":
            return 2
        return 0
    finally:
        db.close()


def run_find_youtube_comment_authors(query: str) -> int:
    """Find identities represented in locally indexed YouTube comments."""

    db = initialize_database()
    repository = WarrigalRepository(db)
    try:
        authors = find_youtube_comment_authors(
            repository.list_passages(),
            query,
        )
        print("=== WARRIGAL YOUTUBE COMMENT AUTHORS ===")
        print(f"QUERY:   {query}")
        print(f"RESULTS: {len(authors)}")
        for author in authors:
            print()
            print(f"AUTHOR ID: {author.author_id or 'UNAVAILABLE'}")
            print(f"HANDLES:   {', '.join(author.handles) or 'UNAVAILABLE'}")
            print(
                f"PROFILES:  {', '.join(author.profile_urls) or 'UNAVAILABLE'}"
            )
            print(f"COMMENTS:  {author.comment_count}")
            print(f"VIDEOS:    {author.video_count}")
        return 0
    finally:
        db.close()


def run_show_youtube_comments_by_author(author_identity: str) -> int:
    """Print locally indexed comments belonging to one exact identity."""

    import json

    db = initialize_database()
    repository = WarrigalRepository(db)
    try:
        rows = comments_by_author(
            repository.list_passages(),
            author_identity,
        )
        print("=== WARRIGAL YOUTUBE COMMENTS BY AUTHOR ===")
        print(f"IDENTITY: {author_identity}")
        print(f"COMMENTS: {len(rows)}")
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            print()
            print(f"VIDEO:   {metadata.get('video_id')}")
            print(f"COMMENT: {metadata.get('comment_id')}")
            print(f"SOURCE:  {row['source_url']}")
            print(f"TEXT:    {row['text']}")
        return 0
    finally:
        db.close()


def run_search_jufe_archive(
    *, trigger_path: str, output_path: str, max_results: int = 500
) -> int:
    """Search indexed Warrigal evidence and export reviewable results."""

    triggers = load_triggers(trigger_path)
    db = initialize_database()
    try:
        hits = search_jufe_archive(
            WarrigalRepository(db).list_passages(),
            triggers,
            max_results=max_results,
        )
        markdown, data, count = export_jufe_search(
            hits, output_path=output_path, triggers=triggers
        )
        print("=== WARRIGAL JUFE ARCHIVE SEARCH ===")
        print(f"TRIGGERS:       {len(triggers)}")
        print(f"RESULTS:        {count}")
        print(f"REVIEW STATUS:  UNREVIEWED")
        print(f"MARKDOWN:       {markdown.resolve()}")
        print(f"JSON:           {data.resolve()}")
        return 0
    finally:
        db.close()


def run_search(
    query: str,
    min_query_coverage: float = 0.0,
    max_results: int | None = None,
) -> int:
    """Search persistent Warrigal passages."""

    db = initialize_database()
    repository = WarrigalRepository(db)

    rows = repository.list_passages()
    passages = passages_from_rows(rows)
    results = search_passages(
        query,
        passages,
        min_query_coverage=min_query_coverage,
        max_results=max_results,
    )

    print()
    print("=== WARRIGAL SEARCH ===")
    print(f"QUERY:   {query}")
    print(f"RESULTS: {len(results)}")

    for result in results:
        acquisition = repository.get_acquisition(
            result.passage.acquisition_id
        )
        print()
        print(f"SCORE:          {result.score}")
        print(f"COVERAGE:       {result.query_coverage:.2f}")
        print(f"MATCHED:        {', '.join(result.matched_terms)}")
        print(f"EXACT:          {', '.join(result.exact_matched_terms)}")
        print(f"FAMILY:         {', '.join(result.family_matched_terms)}")
        print(f"TERM FREQUENCY: {result.query_term_frequency}")
        print(f"TERM SPAN:      {result.term_span}")
        print(f"TITLE COVERAGE: {result.title_query_coverage:.2f}")
        print(f"TITLE MATCHED:  {', '.join(result.title_matched_terms)}")
        print(f"TITLE EXACT:    {', '.join(result.title_exact_matched_terms)}")
        print(f"TITLE FAMILY:   {', '.join(result.title_family_matched_terms)}")
        print(f"TITLE:          {result.passage.source_title}")
        print(f"SOURCE:         {result.passage.source_url}")
        source_url = result.passage.source_url or ""
        parsed_source = urlparse(source_url)
        video_id = parse_qs(parsed_source.query).get("v", [None])[0]
        evidence_group = (
            f"youtube-video:{video_id}"
            if video_id and "youtube.com" in parsed_source.netloc
            else f"object:{result.passage.object_id}"
        )
        print(f"EVIDENCE GROUP: {evidence_group}")
        print(f"OBJECT:         {result.passage.object_id}")
        print(f"ACQUISITION:    {result.passage.acquisition_id}")
        print(
            "METHOD:         "
            f"{acquisition['method'] if acquisition is not None else 'unknown'}"
        )
        print(f"EVIDENCE:       {result.passage.text}")

    db.close()
    return 0


def run_plan_source(
    source_type: str,
    target: str,
    action: str,
    *,
    delay: float = 3.0,
) -> int:
    """Print the panel's exact workflow plan without executing any step."""

    if action not in actions_for(source_type):
        choices = "\n  - ".join(actions_for(source_type))
        raise ValueError(
            f"Unknown {source_type} action: {action}\nAvailable actions:\n  - {choices}"
        )
    plan = build_workflow_plan(
        source_type, target, action, delay=delay
    )
    print("=== WARRIGAL SOURCE PLAN (READ ONLY) ===")
    print(f"SOURCE TYPE: {plan.source_type}")
    print(f"TARGET:      {plan.target}")
    print(f"ACTION:      {plan.action}")
    print(f"STEPS:       {len(plan.steps)}")
    for index, step in enumerate(plan.steps, start=1):
        print()
        print(f"[{index}] {step.label}")
        print("    " + " ".join(step.command))
    print()
    print("NO COMMANDS WERE RUN")
    return 0


def run_acquire_manifest(
    manifest_path: str,
    *,
    checkpoint_path: str,
    max_resources: int,
    max_resource_bytes: int | None = None,
    retry_failures: int = 0,
    retry_delay_seconds: float = 0.0,
    read_timeout: float = 30.0,
) -> int:
    """Acquire a bounded collection manifest into Warrigal."""

    from warrigal.acquisition.manifest import CollectionManifest
    from warrigal.acquisition.manifest_adapters import (
        make_generic_document_manifest_handler,
        make_pdf_manifest_handler,
        make_web_archive_manifest_handler,
    )
    from warrigal.acquisition.manifest_campaign import run_manifest_campaign
    from warrigal.acquisition.web import WebFetcher

    manifest_file = Path(manifest_path).expanduser().resolve()
    checkpoint_file = Path(checkpoint_path).expanduser().resolve()

    manifest = CollectionManifest.from_json(
        manifest_file.read_text(encoding="utf-8")
    )

    if max_resources < 1:
        raise ValueError("--max-resources must be at least 1")

    if max_resource_bytes is not None and max_resource_bytes < 0:
        raise ValueError("--max-resource-bytes must be non-negative")
    if retry_failures < 0:
        raise ValueError("--retry-failures must be non-negative")
    if retry_delay_seconds < 0:
        raise ValueError("--retry-delay-seconds must be non-negative")
    if read_timeout <= 0:
        raise ValueError("--read-timeout must be greater than zero")

    db = initialize_database()
    repository = WarrigalRepository(db)

    try:
        node = Node(name="Warrigal CLI")
        repository.save_node(node)

        batch = Batch(
            node_id=node.node_id,
            label=f"Manifest campaign: {manifest.name}",
        )
        repository.save_batch(batch)

        job = Job(
            name=f"Manifest acquisition: {manifest.name}",
            node_id=node.node_id,
            batch_id=batch.batch_id,
        )
        repository.save_job(job)

        collection = Collection(
            name=manifest.name,
            description=manifest.description,
        )
        repository.save_collection(collection)

        object_store = ObjectStore()
        fetcher = WebFetcher(timeout=read_timeout)

        discovery_metadata = dict(manifest.discovery_provenance)
        discovery_metadata["manifest_id"] = manifest.manifest_id

        pdf_handler = make_pdf_manifest_handler(
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
            discovery_metadata=discovery_metadata,
            fetcher=fetcher,
        )

        document_handler = (
            make_generic_document_manifest_handler(
                repository=repository,
                object_store=object_store,
                job_id=job.job_id,
                node_id=node.node_id,
                batch_id=batch.batch_id,
                collection_id=collection.collection_id,
                discovery_metadata=discovery_metadata,
                fetcher=fetcher,
            )
        )

        zip_handler = make_web_archive_manifest_handler(
            repository=repository,
            object_store=object_store,
            job_id=job.job_id,
            node_id=node.node_id,
            batch_id=batch.batch_id,
            collection_id=collection.collection_id,
            discovery_metadata=discovery_metadata,
            fetcher=fetcher,
        )

        result = run_manifest_campaign(
            manifest,
            pdf_handler=pdf_handler,
            zip_handler=zip_handler,
            document_handler=document_handler,
            checkpoint_path=checkpoint_file,
            max_resources=max_resources,
            max_resource_bytes=max_resource_bytes,
            retry_failures=retry_failures,
            retry_delay_seconds=retry_delay_seconds,
        )

        print("=== WARRIGAL MANIFEST CAMPAIGN ===")
        print(f"MANIFEST:           {manifest.manifest_id}")
        print(f"COLLECTION:         {collection.collection_id}")
        print(f"CHECKPOINT:         {checkpoint_file}")
        print(f"RESOURCE LIMIT:     {max_resources}")
        print(f"RESOURCE BYTE LIMIT:{max_resource_bytes!s:>11}")
        print(f"READ TIMEOUT:       {read_timeout:g} seconds")
        print(f"RETRY LIMIT:        {retry_failures}")
        print(f"SELECTED RESOURCES: {result.selected_resources}")

        for item in result.run_result.items:
            print(
                f"{item.status:20} "
                f"{item.action:20} "
                f"{item.url}"
            )

        failed = result.run_result.count("failed")

        print("=== CAMPAIGN COMPLETE ===")
        print(f"SELECTED: {result.selected_resources}")
        print(f"ACQUIRED: {result.run_result.count('acquired')}")
        print(f"ARCHIVED: {result.run_result.count('archived')}")
        print(f"FAILED:   {failed}")
        print(f"RETRY ATTEMPTS:    {result.retry_attempts}")
        print(f"RETRIED SUCCESS:   {result.retried_resources}")
        print(f"EXHAUSTED:         {result.exhausted_failures}")
        if result.selected_resources == 0:
            print("NO NEW RESOURCES")

        return 1 if failed else 0
    finally:
        db.close()


def main() -> int:
    """Run the Warrigal command-line interface."""

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "doctor":
        return run_doctor()

    if args.command == "archive-health":
        return run_archive_health(verify_hashes=args.verify_hashes)

    if args.command == "plan-source":
        return run_plan_source(
            args.source_type,
            args.target,
            args.action,
            delay=args.delay,
        )

    if args.command == "acquire-manifest":
        return run_acquire_manifest(
            args.manifest,
            checkpoint_path=args.checkpoint,
            max_resources=args.max_resources,
            max_resource_bytes=args.max_resource_bytes,
            retry_failures=args.retry_failures,
            retry_delay_seconds=args.retry_delay_seconds,
            read_timeout=args.read_timeout,
        )

    if args.command == "acquire":
        return run_acquire(args.url)

    if args.command == "inventory-website-documents":
        return run_inventory_website_documents(args.url, output_path=args.output)

    if args.command == "verify-website-manifest":
        return run_verify_website_manifest(
            args.manifest,
            checkpoint_path=args.checkpoint,
        )

    if args.command == "ingest-youtube-media":
        if not args.model:
            parser.error(
                "ingest-youtube-media requires --model or a configured "
                "[models] whisper value"
            )
        return run_ingest_youtube_media(args.url, model_path=args.model)

    if args.command == "ingest-video":
        return run_ingest_video(args.path, model_path=args.model)

    if args.command == "ingest-audio":
        return run_ingest_audio(args.path, model_path=args.model)

    if args.command == "ingest-pdf":
        return run_ingest_pdf(args.path)

    if args.command == "ingest-archive":
        return run_ingest_archive(args.path)

    if args.command == "ingest-youtube":
        return run_ingest_youtube(args.url)

    if args.command == "ingest-youtube-channel":
        return run_ingest_youtube_channel(
            args.channel,
            checkpoint_path=args.checkpoint,
            posts_checkpoint_path=args.posts_checkpoint,
            scan_videos=args.scan_videos,
            max_videos=args.max_videos,
            max_comments=args.max_comments,
            max_posts=args.max_posts,
            max_post_pages=args.max_post_pages,
            stages=args.stage,
        )

    if args.command == "ingest-youtube-comments":
        return run_ingest_youtube_comments(
            args.url,
            target_author_id=args.target_author_id,
            target_author_handle=args.target_author_handle,
            max_comments=args.max_comments,
        )

    if args.command == "ingest-youtube-channel-comments":
        return run_ingest_youtube_channel_comments(
            args.channel,
            target_author_id=args.target_author_id,
            target_author_handle=args.target_author_handle,
            checkpoint_path=args.checkpoint,
            scan_videos=args.scan_videos,
            max_videos=args.max_videos,
            max_comments=args.max_comments,
        )

    if args.command == "index-youtube-comments":
        return run_index_youtube_comments()

    if args.command == "ingest-youtube-posts":
        return run_ingest_youtube_posts(
            args.channel,
            checkpoint_path=args.checkpoint,
            max_posts=args.max_posts,
            max_pages=args.max_pages,
        )

    if args.command == "ingest-youtube-post-comments":
        return run_ingest_youtube_post_comments(
            args.post,
            checkpoint_path=args.checkpoint,
            max_continuation_fetches=args.max_continuation_fetches,
        )

    if args.command == "ingest-youtube-post-comments-campaign":
        return run_ingest_youtube_post_comments_campaign(
            args.channel,
            posts_checkpoint_path=args.posts_checkpoint,
            comments_checkpoint_path=args.comments_checkpoint,
            max_continuation_fetches=args.max_continuation_fetches,
            skip_completed=args.skip_completed,
        )

    if args.command == "find-youtube-comment-authors":
        return run_find_youtube_comment_authors(args.query)

    if args.command == "show-youtube-comments-by-author":
        return run_show_youtube_comments_by_author(args.identity)

    if args.command == "search-jufe-archive":
        return run_search_jufe_archive(
            trigger_path=args.triggers,
            output_path=args.output,
            max_results=args.max_results,
        )

    if args.command == "ingest-instagram-profile":
        return run_ingest_instagram_profile(
            args.profile,
            username=args.username,
            max_posts=args.max_posts,
            resume=args.resume,
        )

    if args.command == "ingest-instagram":
        return run_ingest_instagram(args.post, username=args.username)

    if args.command == "history":
        return run_history()

    if args.command == "inspect":
        return run_inspect(args.object_id)

    if args.command == "discover":
        return run_discover(args.url)

    if args.command == "crawl":
        return run_crawl(args.url)

    if args.command == "search":
        return run_search(
            args.query,
            min_query_coverage=args.min_coverage,
            max_results=args.max_results,
        )

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

    
