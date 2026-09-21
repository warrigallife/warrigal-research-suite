"""Read-only integrity and coverage reporting for the Warrigal archive."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from warrigal.config import CONFIG, WarrigalConfig


@dataclass(frozen=True)
class ArchiveHealth:
    objects: int
    acquisitions: int
    passages: int
    collections: int
    storage_locations: int
    missing_object_files: tuple[str, ...]
    broken_storage_paths: tuple[str, ...]
    hash_failures: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return not (
            self.missing_object_files
            or self.broken_storage_paths
            or self.hash_failures
        )


def _count(connection: sqlite3.Connection, table: str) -> int:
    allowed = {
        "objects", "acquisitions", "passages", "collections", "storage_locations"
    }
    if table not in allowed:
        raise ValueError(f"Unsupported health-count table: {table}")
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_archive(
    config: WarrigalConfig = CONFIG,
    *,
    verify_hashes: bool = False,
) -> ArchiveHealth:
    """Inspect database references and archive files without modifying either."""

    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    try:
        object_rows = connection.execute(
            "SELECT object_id, sha256 FROM objects ORDER BY sha256"
        ).fetchall()
        storage_rows = connection.execute(
            "SELECT object_id, path FROM storage_locations ORDER BY path"
        ).fetchall()
        missing: list[str] = []
        hash_failures: list[str] = []
        for row in object_rows:
            digest = row["sha256"]
            path = config.object_store_path / digest[:2] / digest[2:4] / digest
            if not path.is_file():
                missing.append(row["object_id"])
            elif verify_hashes and _sha256(path) != digest:
                hash_failures.append(row["object_id"])
        broken_storage = tuple(
            row["path"] for row in storage_rows if not Path(row["path"]).is_file()
        )
        return ArchiveHealth(
            objects=len(object_rows),
            acquisitions=_count(connection, "acquisitions"),
            passages=_count(connection, "passages"),
            collections=_count(connection, "collections"),
            storage_locations=len(storage_rows),
            missing_object_files=tuple(missing),
            broken_storage_paths=broken_storage,
            hash_failures=tuple(hash_failures),
        )
    finally:
        connection.close()


def run_archive_health(*, verify_hashes: bool = False) -> int:
    report = inspect_archive(verify_hashes=verify_hashes)
    print("=== WARRIGAL ARCHIVE HEALTH ===")
    print(f"OBJECTS:                {report.objects}")
    print(f"ACQUISITIONS:           {report.acquisitions}")
    print(f"PASSAGES:               {report.passages}")
    print(f"COLLECTIONS:            {report.collections}")
    print(f"STORAGE LOCATIONS:      {report.storage_locations}")
    print(f"MISSING OBJECT FILES:   {len(report.missing_object_files)}")
    print(f"BROKEN STORAGE PATHS:   {len(report.broken_storage_paths)}")
    print(f"HASH FAILURES:          {len(report.hash_failures)}")
    print(f"FULL HASH VERIFICATION: {'YES' if verify_hashes else 'NO'}")
    print(f"RESULT:                 {'HEALTHY' if report.healthy else 'ATTENTION REQUIRED'}")
    return 0 if report.healthy else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Warrigal archive integrity.")
    parser.add_argument(
        "--verify-hashes",
        action="store_true",
        help="Read and SHA-256 verify every archived object (slower).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run_archive_health(verify_hashes=args.verify_hashes)


if __name__ == "__main__":
    raise SystemExit(main())
