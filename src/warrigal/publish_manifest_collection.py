from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from warrigal.object_store import ObjectStore


SUCCESS_STATUSES = {"acquired", "archived"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(
            lambda: stream.read(8 * 1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def safe_segment(value: str) -> str:
    value = unquote(value).strip()
    value = re.sub(r'[/:*?"<>|]+', "_", value)

    if value in {"", ".", ".."}:
        return "_"

    return value


def branch_parts(resource: dict) -> list[str]:
    branch = (
        resource.get("metadata", {}).get("branch")
        or "UNCLASSIFIED"
    )

    parts = [
        safe_segment(part)
        for part in branch.split("/")
        if part not in {"", ".", ".."}
    ]

    return parts or ["UNCLASSIFIED"]


def relative_original_path(resource: dict) -> Path:
    url_parts = [
        safe_segment(part)
        for part in urlparse(resource["url"]).path.split("/")
        if part
    ]
    branch = branch_parts(resource)

    if url_parts[:len(branch)] == branch:
        remaining = url_parts[len(branch):]
    else:
        remaining = url_parts[-1:]

    if not remaining:
        remaining = ["resource.bin"]

    return Path(*remaining)


def publish(
    *,
    manifest_path: Path,
    checkpoint_path: Path,
    output_root: Path,
) -> int:
    manifest = load_json(manifest_path)
    checkpoint = load_json(checkpoint_path)

    manifest_id = manifest["manifest_id"]

    if checkpoint.get("manifest_id") != manifest_id:
        raise ValueError(
            "Checkpoint belongs to a different manifest: "
            f"{checkpoint.get('manifest_id')!r} != {manifest_id!r}"
        )

    checkpoint_records = checkpoint.get("resources") or {}
    resources = manifest.get("resources") or []
    object_store = ObjectStore()

    manifest_by_branch = defaultdict(list)
    published_by_branch = defaultdict(list)

    for resource in resources:
        branch = "/".join(branch_parts(resource))
        manifest_by_branch[branch].append(resource)

        record = checkpoint_records.get(resource["url"])
        if (
            not record
            or record.get("status") not in SUCCESS_STATUSES
        ):
            continue

        metadata = record.get("metadata") or {}
        sha256 = metadata.get("sha256")
        object_id = metadata.get("object_id")
        acquisition_id = metadata.get("acquisition_id")

        if not sha256:
            raise RuntimeError(
                f"Completed checkpoint lacks SHA-256: "
                f"{resource['url']}"
            )

        archived = object_store.path_for_hash(sha256)

        if not archived.is_file():
            raise RuntimeError(
                f"Archived object is missing: {archived}"
            )

        if calculate_sha256(archived) != sha256:
            raise RuntimeError(
                f"Archived object failed verification: {archived}"
            )

        branch_root = output_root.joinpath(
            *branch_parts(resource)
        )
        originals_root = branch_root / "ORIGINALS"
        target = originals_root / relative_original_path(resource)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            if not target.is_file():
                raise RuntimeError(
                    f"Target is not a regular file: {target}"
                )

            if calculate_sha256(target) != sha256:
                raise RuntimeError(
                    f"Existing target has different bytes: {target}"
                )

            publication_method = "existing_verified"
        else:
            try:
                os.link(archived, target)
                publication_method = "hard_link"
            except OSError:
                shutil.copy2(archived, target)
                publication_method = "verified_copy"

            if calculate_sha256(target) != sha256:
                raise RuntimeError(
                    f"Published file failed verification: {target}"
                )

        published = {
            "url": resource["url"],
            "relative_path": str(
                target.relative_to(branch_root)
            ),
            "media_type": resource["media_type"],
            "size_bytes": metadata.get("size_bytes"),
            "sha256": sha256,
            "object_id": object_id,
            "acquisition_id": acquisition_id,
            "checkpoint_status": record["status"],
            "publication_method": publication_method,
        }

        published_by_branch[branch].append(published)

        print(
            "PUBLISHED:",
            branch,
            "|",
            published["relative_path"],
        )

    for branch, published in published_by_branch.items():
        branch_root = output_root.joinpath(
            *[safe_segment(part) for part in branch.split("/")]
        )
        branch_resources = manifest_by_branch[branch]

        branch_manifest = {
            "manifest_id": manifest_id,
            "source_manifest": str(manifest_path.resolve()),
            "branch": branch,
            "resource_count": len(branch_resources),
            "resources": branch_resources,
        }

        report = {
            "manifest_id": manifest_id,
            "branch": branch,
            "generated_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "manifest_resource_count": len(branch_resources),
            "published_resource_count": len(published),
            "publication_status": (
                "COMPLETE"
                if len(published) == len(branch_resources)
                else "PARTIAL"
            ),
            "object_store": str(
                object_store.root.resolve()
            ),
            "resources": published,
        }

        save_json(branch_root / "MANIFEST.json", branch_manifest)
        save_json(
            branch_root / "ACQUISITION_REPORT.json",
            report,
        )

    completed_count = sum(
        len(records)
        for records in published_by_branch.values()
    )

    print()
    print("=== MANIFEST COLLECTION PUBLICATION COMPLETE ===")
    print("MANIFEST:", manifest_id)
    print("CHECKPOINTED RESOURCES:", len(checkpoint_records))
    print("PUBLISHED OR VERIFIED:", completed_count)
    print("BRANCHES UPDATED:", len(published_by_branch))
    print("OUTPUT ROOT:", output_root.resolve())

    return completed_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish verified Warrigal manifest objects as "
            "readable branch files."
        )
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    publish(
        manifest_path=args.manifest.expanduser().resolve(),
        checkpoint_path=args.checkpoint.expanduser().resolve(),
        output_root=args.output_root.expanduser().resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
