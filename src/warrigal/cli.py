from __future__ import annotations

import argparse
from warrigal.acquisition.crawler import WebCrawler
from warrigal.acquisition.content import extract_html_content
from warrigal.acquisition.links import extract_links
from warrigal.acquisition.service import AcquisitionService
from warrigal.acquisition.web import WebFetcher
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.retrieval.passages import split_into_passages

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
        if response.content_type == "text/html":
            content = extract_html_content(response.data)

            passages = split_into_passages(
                content.text,
                source_url=response.final_url,
                source_title=content.title,
                object_id=acquisition_result.object_id,
                acquisition_id=acquisition_result.acquisition_id,
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
     
def main() -> int:
    """Run the Warrigal command-line interface."""

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "acquire":
        return run_acquire(args.url)

    if args.command == "history":
        return run_history()

    if args.command == "inspect":
        return run_inspect(args.object_id)

    if args.command == "discover":
        return run_discover(args.url)

    if args.command == "crawl":
        return run_crawl(args.url)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

    