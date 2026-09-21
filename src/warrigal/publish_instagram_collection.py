"""Publish archived Instagram evidence as human-readable collections."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from warrigal.database import initialize_database
from warrigal.object_store import ObjectStore


DEFAULT_OUTPUT_ROOT = (
    Path.home()
    / "Desktop"
    / "INFORMATION_ARCHIVE"
    / "COLLECTIONS"
    / "INSTAGRAM"
)


def safe_name(value: str, fallback: str = "unknown") -> str:
    """Return a safe name while preserving valid shortcode endings."""

    parts = [
        part
        for part in value.strip().replace("\\", "/").split("/")
        if part not in {"", ".", ".."}
    ]
    combined = "-".join(parts)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", combined)
    cleaned = cleaned.lstrip(".")

    if cleaned in {"", ".", ".."}:
        return fallback

    return cleaned

def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically without leaving a partial publication file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def json_value(value: str | None) -> dict:
    """Decode a JSON object or return an empty dictionary."""

    if not value:
        return {}

    try:
        result = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}

    return result if isinstance(result, dict) else {}


def nested_username(payload: object) -> str | None:
    """Find a likely Instagram account username in archived metadata."""

    preferred = (
        "profile_username",
        "owner_username",
        "username",
    )

    if isinstance(payload, dict):
        for key in preferred:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lstrip("@")

        for value in payload.values():
            found = nested_username(value)
            if found:
                return found

    elif isinstance(payload, list):
        for value in payload:
            found = nested_username(value)
            if found:
                return found

    return None


def profile_from_url(source_url: str) -> str | None:
    """Extract a profile from profile-qualified Instagram post URLs."""

    parts = [
        part
        for part in urlparse(source_url).path.split("/")
        if part
    ]

    for marker in ("p", "reel", "tv"):
        if marker in parts:
            position = parts.index(marker)
            if position > 0:
                return parts[position - 1].lstrip("@")

    return None


def shortcode_from_url(source_url: str) -> str | None:
    """Extract an Instagram shortcode from a post URL."""

    parts = [
        part
        for part in urlparse(source_url).path.split("/")
        if part
    ]

    for marker in ("p", "reel", "tv"):
        if marker in parts:
            position = parts.index(marker)
            if position + 1 < len(parts):
                return parts[position + 1]

    return None


def materialize_object(source: Path, destination: Path) -> str:
    """Hard-link an archived object, falling back to a byte-for-byte copy."""

    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        if (
            destination.stat().st_size == source.stat().st_size
            and os.path.samefile(source, destination)
        ):
            return "existing"

        destination.unlink()

    temporary = destination.with_name(destination.name + ".tmp")

    if temporary.exists():
        temporary.unlink()

    try:
        os.link(source, temporary)
        method = "hardlink"
    except OSError:
        shutil.copy2(source, temporary)
        method = "copy"

    temporary.replace(destination)
    return method


def unique_destination(
    directory: Path,
    filename: str,
    used: set[str],
) -> Path:
    """Choose a deterministic collision-free destination filename."""

    original = safe_name(filename, "evidence.bin")
    candidate = original
    counter = 2

    while candidate.lower() in used:
        path = Path(original)
        candidate = f"{path.stem}-{counter}{path.suffix}"
        counter += 1

    used.add(candidate.lower())
    return directory / candidate


def read_archived_json(store: ObjectStore, sha256: str) -> dict:
    """Read an archived JSON object without altering it."""

    try:
        payload = json.loads(
            store.read_bytes(sha256).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def load_publication_records(database) -> tuple[list[dict], dict, dict]:
    """Load snapshots, linked acquisitions, captions and profile hints."""

    acquisition_rows = database.execute(
        """
        SELECT
            a.acquisition_id,
            a.source_id,
            a.object_id,
            a.job_id,
            a.batch_id,
            a.method,
            a.status,
            a.acquired_at,
            a.metadata_json AS acquisition_metadata_json,
            s.source_type,
            s.locator,
            s.title,
            s.metadata_json AS source_metadata_json,
            o.sha256,
            o.size_bytes,
            o.mime_type,
            o.original_filename
        FROM acquisitions AS a
        JOIN sources AS s ON s.source_id = a.source_id
        JOIN objects AS o ON o.object_id = a.object_id
        WHERE a.status = 'success'
          AND (
                a.method = 'instagram_metadata_snapshot'
             OR a.method = 'instagram_evidence_file'
          )
        ORDER BY a.acquired_at, a.acquisition_id
        """
    ).fetchall()

    by_url: dict[str, list[dict]] = defaultdict(list)
    snapshots: list[dict] = []

    for original in acquisition_rows:
        row = dict(original)
        acquisition_metadata = json_value(
            row["acquisition_metadata_json"]
        )
        source_url = (
            acquisition_metadata.get("source_url")
            or row["locator"]
        )

        if not isinstance(source_url, str) or not source_url:
            continue

        row["source_url"] = source_url
        by_url[source_url].append(row)

        if row["method"] == "instagram_metadata_snapshot":
            snapshots.append(row)

    captions: dict[tuple[str, str], list[str]] = defaultdict(list)

    for row in database.execute(
        """
        SELECT source_url, object_id, text
        FROM passages
        WHERE source_url LIKE '%instagram.com/%'
        ORDER BY source_url, passage_index, created_at
        """
    ):
        text = row["text"] or ""

        if text.strip():
            captions[
                (row["source_url"], row["object_id"])
            ].append(text.strip())

    checkpoint_profiles: dict[tuple[str, str], str] = {}

    for row in database.execute(
        """
        SELECT
            profile_username,
            shortcode,
            snapshot_acquisition_id
        FROM instagram_post_checkpoints
        """
    ):
        checkpoint_profiles[
            (row["shortcode"], row["snapshot_acquisition_id"])
        ] = row["profile_username"]

    latest_snapshots = {}

    for snapshot in snapshots:
        latest_snapshots[snapshot["source_url"]] = snapshot

    return list(latest_snapshots.values()), by_url, {
        "captions": captions,
        "checkpoint_profiles": checkpoint_profiles,
    }


def publish_instagram_collection(
    *,
    database,
    object_store: ObjectStore,
    output_root: Path,
    profile_filter: str | None = None,
) -> dict:
    """Publish archived Instagram posts into clickable folders."""

    snapshots, acquisitions_by_url, extra = load_publication_records(
        database
    )
    captions = extra["captions"]
    checkpoint_profiles = extra["checkpoint_profiles"]

    profile_filter_normalized = (
        profile_filter.lower().lstrip("@")
        if profile_filter
        else None
    )

    output_root.mkdir(parents=True, exist_ok=True)

    profile_entries: dict[str, list[dict]] = defaultdict(list)
    published = 0
    media_files = 0
    metadata_files = 0
    captioned = 0
    missing_objects: list[dict] = []
    seen_posts: set[tuple[str, str]] = set()

    for snapshot in snapshots:
        source_url = snapshot["source_url"]
        source_metadata = json_value(
            snapshot["source_metadata_json"]
        )
        acquisition_metadata = json_value(
            snapshot["acquisition_metadata_json"]
        )
        payload = read_archived_json(
            object_store,
            snapshot["sha256"],
        )

        shortcode = (
            shortcode_from_url(source_url)
            or source_metadata.get("shortcode")
            or acquisition_metadata.get("shortcode")
            or payload.get("shortcode")
            or snapshot["title"]
            or snapshot["object_id"]
        )
        shortcode = safe_name(str(shortcode), snapshot["object_id"])

        profile = (
            profile_from_url(source_url)
            or checkpoint_profiles.get(
                (shortcode, snapshot["acquisition_id"])
            )
            or nested_username(payload)
            or "unknown-profile"
        )
        profile = safe_name(str(profile).lstrip("@")).lower()

        if (
            profile_filter_normalized is not None
            and profile.lower() != profile_filter_normalized
        ):
            continue

        identity = (profile, shortcode)

        if identity in seen_posts:
            continue

        seen_posts.add(identity)

        post_root = (
            output_root
            / profile
            / "posts"
            / shortcode
        )
        media_root = post_root / "media"
        metadata_root = post_root / "metadata"

        media_root.mkdir(parents=True, exist_ok=True)
        metadata_root.mkdir(parents=True, exist_ok=True)

        records = [
            record
            for record in acquisitions_by_url.get(source_url, [])
            if record["batch_id"] == snapshot["batch_id"]
        ]
        used_media: set[str] = set()
        used_metadata: set[str] = set()
        links: list[dict] = []

        for record in records:
            archived = object_store.path_for_hash(record["sha256"])

            if not archived.is_file():
                missing_objects.append(
                    {
                        "shortcode": shortcode,
                        "acquisition_id": record["acquisition_id"],
                        "sha256": record["sha256"],
                    }
                )
                continue

            is_json = (
                record["mime_type"] == "application/json"
                or str(record["original_filename"]).lower().endswith(
                    ".json"
                )
            )

            if record["acquisition_id"] == snapshot["acquisition_id"]:
                destination = metadata_root / "normalized.json"
                label = "Normalized metadata"
                kind = "metadata"
            elif is_json:
                destination = unique_destination(
                    metadata_root,
                    record["original_filename"] or "evidence.json",
                    used_metadata,
                )
                label = record["original_filename"] or "Metadata"
                kind = "metadata"
            else:
                destination = unique_destination(
                    media_root,
                    record["original_filename"] or "media.bin",
                    used_media,
                )
                label = record["original_filename"] or "Media"
                kind = "media"

            method = materialize_object(archived, destination)
            relative = destination.relative_to(post_root)

            links.append(
                {
                    "label": label,
                    "path": relative.as_posix(),
                    "mime_type": record["mime_type"],
                    "sha256": record["sha256"],
                    "object_id": record["object_id"],
                    "acquisition_id": record["acquisition_id"],
                    "publication_method": method,
                    "kind": kind,
                }
            )

            if kind == "media":
                media_files += 1
            else:
                metadata_files += 1

        caption_parts = captions.get(
            (source_url, snapshot["object_id"]),
            [],
        )
        caption = "\n\n".join(caption_parts).strip()

        if caption:
            captioned += 1
        else:
            caption = "_No caption was recorded for this post._"

        date_utc = (
            source_metadata.get("date_utc")
            or payload.get("date_utc")
            or snapshot["acquired_at"]
        )
        typename = (
            source_metadata.get("typename")
            or payload.get("typename")
            or "Instagram post"
        )

        media_lines: list[str] = []

        for link in links:
            if link["kind"] != "media":
                continue

            path = link["path"]
            mime_type = link["mime_type"] or ""

            if mime_type.startswith("image/"):
                media_lines.append(
                    f"![{link['label']}]({path})"
                )
            else:
                media_lines.append(
                    f"- [{link['label']}]({path})"
                )

        if not media_lines:
            media_lines.append(
                "_No publishable media file was found._"
            )

        evidence_lines = [
            (
                f"- [{link['label']}]({link['path']})  \n"
                f"  `{link['object_id']}` · "
                f"`{link['sha256']}`"
            )
            for link in links
        ]

        if not evidence_lines:
            evidence_lines.append("_No linked evidence was found._")

        post_markdown = (
            f"# Instagram post `{shortcode}`\n\n"
            f"- **Profile:** @{profile}\n"
            f"- **Published:** {date_utc}\n"
            f"- **Type:** {typename}\n"
            f"- **Original post:** [{source_url}]({source_url})\n"
            f"- **Snapshot object:** `{snapshot['object_id']}`\n"
            f"- **Snapshot acquisition:** "
            f"`{snapshot['acquisition_id']}`\n\n"
            f"## Caption\n\n"
            f"{caption}\n\n"
            f"## Media\n\n"
            f"{chr(10).join(media_lines)}\n\n"
            f"## Preserved evidence\n\n"
            f"{chr(10).join(evidence_lines)}\n"
        )

        atomic_write_text(post_root / "POST.md", post_markdown)

        manifest = {
            "profile": profile,
            "shortcode": shortcode,
            "source_url": source_url,
            "date_utc": date_utc,
            "typename": typename,
            "snapshot_object_id": snapshot["object_id"],
            "snapshot_acquisition_id": snapshot["acquisition_id"],
            "caption_recorded": bool(caption_parts),
            "evidence": links,
        }
        atomic_write_text(
            post_root / "manifest.json",
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
        )

        profile_entries[profile].append(
            {
                "shortcode": shortcode,
                "date_utc": str(date_utc),
                "caption": (
                    caption_parts[0]
                    if caption_parts
                    else "No caption recorded."
                ),
                "source_url": source_url,
                "media_count": sum(
                    link["kind"] == "media"
                    for link in links
                ),
            }
        )
        published += 1

    root_lines = [
        "# Warrigal Instagram Collections",
        "",
        f"Published posts: **{published}**",
        "",
    ]

    for profile in sorted(profile_entries):
        entries = sorted(
            profile_entries[profile],
            key=lambda item: (
                item["date_utc"],
                item["shortcode"],
            ),
            reverse=True,
        )
        profile_root = output_root / profile
        profile_lines = [
            f"# Instagram archive: @{profile}",
            "",
            f"Published posts: **{len(entries)}**",
            "",
            "| Date | Post | Media | Caption preview |",
            "|---|---|---:|---|",
        ]

        for entry in entries:
            preview = re.sub(
                r"\s+",
                " ",
                entry["caption"],
            ).replace("|", "\\|")
            preview = preview[:180]
            relative = (
                f"posts/{entry['shortcode']}/POST.md"
            )
            profile_lines.append(
                f"| {entry['date_utc']} "
                f"| [`{entry['shortcode']}`]({relative}) "
                f"| {entry['media_count']} "
                f"| {preview} |"
            )

        atomic_write_text(
            profile_root / "INDEX.md",
            "\n".join(profile_lines) + "\n",
        )
        root_lines.append(
            f"- [@{profile}]({profile}/INDEX.md): "
            f"{len(entries)} posts"
        )

    atomic_write_text(
        output_root / "INDEX.md",
        "\n".join(root_lines) + "\n",
    )

    result = {
        "published_posts": published,
        "profiles": {
            profile: len(entries)
            for profile, entries in profile_entries.items()
        },
        "captioned_posts": captioned,
        "posts_without_captions": published - captioned,
        "media_files": media_files,
        "metadata_files": metadata_files,
        "missing_objects": missing_objects,
        "output_root": str(output_root.resolve()),
    }

    atomic_write_text(
        output_root / "PUBLICATION_REPORT.json",
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
    )

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish archived Instagram evidence into clickable "
            "human-readable folders."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    parser.add_argument(
        "--profile",
        help="Publish only this resolved Instagram profile.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database = initialize_database()

    try:
        result = publish_instagram_collection(
            database=database,
            object_store=ObjectStore(),
            output_root=args.output_root.expanduser(),
            profile_filter=args.profile,
        )
    finally:
        database.close()

    print("=== WARRIGAL INSTAGRAM PUBLICATION COMPLETE ===")
    print("POSTS:", result["published_posts"])
    print("CAPTIONED:", result["captioned_posts"])
    print(
        "WITHOUT CAPTIONS:",
        result["posts_without_captions"],
    )
    print("MEDIA FILES:", result["media_files"])
    print("METADATA FILES:", result["metadata_files"])
    print("MISSING OBJECTS:", len(result["missing_objects"]))
    print("PROFILES:", result["profiles"])
    print("OUTPUT:", result["output_root"])

    return 1 if result["missing_objects"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
