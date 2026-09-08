from __future__ import annotations

import argparse
from pathlib import Path
from warrigal.acquisition.crawler import WebCrawler
from warrigal.acquisition.content import (
    extract_html_content,
    extract_pdf_content,
)
from warrigal.acquisition.links import extract_links
from warrigal.acquisition.service import AcquisitionService
from warrigal.acquisition.youtube import ingest_video_transcript
from warrigal.instagram_cli import run_ingest_instagram
from warrigal.acquisition.web import WebFetcher
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node, Passage as PassageRecord, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.retrieval.passages import passages_from_rows, split_into_passages
from warrigal.retrieval.search import search_passages

def build_parser() -> argparse.ArgumentParser:
    """Build Warrigal's command-line interface."""

    parser = argparse.ArgumentParser(
        prog="warrigal",
        description="Warrigal Research Suite",
    )

    subparsers = parser.add_subparsers(dest="command")

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


    youtube_parser = subparsers.add_parser(
        "ingest-youtube",
        help="Ingest transcript evidence from a YouTube video.",
    )

    youtube_parser.add_argument(
        "url",
        help="Public YouTube video URL to ingest.",
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

    archive_parser = subparsers.add_parser(
        "ingest-archive",
        help="Recursively ingest PDFs from a local archive directory.",
    )

    archive_parser.add_argument(
        "path",
        help="Local archive directory containing PDFs.",
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
        print(f"OBJECT:         {result.passage.object_id}")
        print(f"ACQUISITION:    {result.passage.acquisition_id}")
        print(f"EVIDENCE:       {result.passage.text}")

    db.close()
    return 0


def main() -> int:
    """Run the Warrigal command-line interface."""

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "acquire":
        return run_acquire(args.url)

    if args.command == "ingest-pdf":
        return run_ingest_pdf(args.path)

    if args.command == "ingest-archive":
        return run_ingest_archive(args.path)

    if args.command == "ingest-youtube":
        return run_ingest_youtube(args.url)

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

    
