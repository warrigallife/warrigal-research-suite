from __future__ import annotations

import argparse

from warrigal.acquisition.service import AcquisitionService
from warrigal.acquisition.web import WebFetcher
from warrigal.database import initialize_database
from warrigal.models import Batch, Collection, Job, Node, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository

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

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

    