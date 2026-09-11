from __future__ import annotations

import argparse

from warrigal.database import initialize_database
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository
from warrigal.video_frame_ingestion import ingest_video_frames


def select_acquisition(acquisitions, acquisition_id: str | None):
    """Select provenance without silently resolving ambiguity."""
    if not acquisitions:
        raise ValueError("No acquisition exists for this object.")

    if acquisition_id is not None:
        for acquisition in acquisitions:
            if acquisition["acquisition_id"] == acquisition_id:
                return acquisition
        raise ValueError(
            f"Acquisition {acquisition_id} does not belong to this object."
        )

    if len(acquisitions) > 1:
        ids = ", ".join(
            acquisition["acquisition_id"]
            for acquisition in acquisitions
        )
        raise ValueError(
            "Object has multiple acquisitions. "
            f"Specify --acquisition-id. Available: {ids}"
        )

    return acquisitions[0]


def run_extract_video_frames(
    object_id: str,
    *,
    interval_seconds: float = 10.0,
    acquisition_id: str | None = None,
    repository=None,
    object_store=None,
    extractor=None,
) -> int:
    """Extract timestamped visual evidence from an archived Warrigal video."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    db = None
    if repository is None:
        db = initialize_database()
        repository = WarrigalRepository(db)

    if object_store is None:
        object_store = ObjectStore()

    try:
        object_row = repository.get_object(object_id)
        if object_row is None:
            raise ValueError(f"Unknown Warrigal object: {object_id}")

        archive_path = object_store.path_for_hash(object_row["sha256"])
        if not archive_path.is_file():
            raise FileNotFoundError(
                f"Archived bytes are missing for {object_id}: {archive_path}"
            )

        acquisitions = repository.get_acquisitions_for_object(object_id)
        acquisition = select_acquisition(acquisitions, acquisition_id)

        source = repository.get_source(acquisition["source_id"])
        if source is None:
            raise ValueError(
                f"Source {acquisition['source_id']} does not exist."
            )

        source_url = (
            source["final_locator"]
            or source["locator"]
            or f"warrigal:{object_id}"
        )
        source_title = source["title"] or object_id

        kwargs = {}
        if extractor is not None:
            kwargs["extractor"] = extractor

        result = ingest_video_frames(
            source_object_id=object_id,
            source_acquisition_id=acquisition["acquisition_id"],
            source_path=archive_path,
            source_url=source_url,
            source_title=source_title,
            repository=repository,
            object_store=object_store,
            job_id=acquisition["job_id"],
            node_id=acquisition["node_id"],
            batch_id=acquisition["batch_id"],
            interval_seconds=interval_seconds,
            **kwargs,
        )

        print()
        print("=== WARRIGAL VIDEO FRAME EXTRACTION ===")
        print(f"SOURCE OBJECT:   {object_id}")
        print(f"ACQUISITION:     {acquisition['acquisition_id']}")
        print(f"TITLE:           {source_title}")
        print(f"INTERVAL:        {interval_seconds:g} seconds")
        print(f"FRAMES ARCHIVED: {len(result.frames)}")

        for frame in result.frames:
            seconds = frame.timestamp_ms / 1000
            print(
                f"  {frame.frame_index:04d}  "
                f"{seconds:10.3f}s  "
                f"{frame.frame_object_id}"
            )

        return 0
    finally:
        if db is not None:
            db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract timestamped frames from an archived Warrigal video."
    )
    parser.add_argument("object_id")
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Seconds between representative frames (default: 10).",
    )
    parser.add_argument(
        "--acquisition-id",
        help="Explicit parent acquisition when an object has multiple acquisitions.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run_extract_video_frames(
        args.object_id,
        interval_seconds=args.interval,
        acquisition_id=args.acquisition_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
