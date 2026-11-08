"""Publish archived YouTube evidence as human-readable collections.

This module is read-only against the Warrigal database and object store.
It never acquires anything: it composes already-archived rows from the
``sources`` / ``acquisitions`` / ``objects`` / ``passages`` tables (written
by ``warrigal.acquisition.youtube`` and ``warrigal.acquisition.youtube_comments``)
into clickable per-video folders, mirroring the existing, already-tested
``warrigal.publish_instagram_collection`` pattern exactly.

Re-running is safe and idempotent: materialized media/evidence objects are
skipped when already present with the expected bytes (see
``materialize_object``), and the generated Markdown/JSON/metadata files are
regenerated deterministically from current database contents each run.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from warrigal.database import initialize_database
from warrigal.object_store import ObjectStore
from warrigal.publish_instagram_collection import (
    atomic_write_text,
    json_value,
    materialize_object,
    read_archived_json,
)


DEFAULT_OUTPUT_ROOT = (
    Path.home()
    / "Desktop"
    / "INFORMATION_ARCHIVE"
    / "COLLECTIONS"
    / "YOUTUBE"
)

_FOLDER_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_FOLDER_WHITESPACE = re.compile(r"\s+")

# Comfortable headroom under the 255-byte filename limit shared by APFS
# and HFS+, once the " [<11-char video id>]" suffix is appended.
_MAX_TITLE_BYTES = 200


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate ``text`` to at most ``max_bytes`` UTF-8 bytes without ever
    splitting a multi-byte character."""

    encoded = text.encode("utf-8")

    if len(encoded) <= max_bytes:
        return text

    truncated = encoded[:max_bytes]

    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]

    return ""


def video_folder_name(title: str | None, video_id: str) -> str:
    """Human-readable publication folder name: ``"<title> [<video_id>]"``.

    The ``video_id`` suffix is always present and always unique, so two
    videos that happen to share an identical (or missing/blank) title
    still get distinct folders -- no separate duplicate-title
    disambiguation pass is needed. Only characters that are unsafe or
    awkward in a macOS Finder folder name (path separators, reserved
    punctuation, control characters) are replaced; spaces and ordinary
    punctuation are kept so the folder name reads naturally. A long title
    is truncated, at a safe UTF-8 boundary, to stay comfortably under the
    filesystem's name-length limit.
    """

    cleaned = _FOLDER_UNSAFE_CHARS.sub("-", (title or "").strip())
    cleaned = _FOLDER_WHITESPACE.sub(" ", cleaned).strip(" .")
    cleaned = _truncate_utf8(cleaned, _MAX_TITLE_BYTES).strip()

    if not cleaned:
        return f"[{video_id}]"

    return f"{cleaned} [{video_id}]"


def video_markdown_link(folder_name: str) -> str:
    """URL-encode a per-video folder's relative ``VIDEO.md`` path for use
    as a Markdown link destination.

    CommonMark link destinations that are not wrapped in ``<...>`` must
    not contain a literal space, so a destination built from a
    human-readable folder name (e.g. ``"Title [videoId]/VIDEO.md"``)
    would otherwise fail to parse as a link at all in a strict renderer
    -- it would show as plain, unclickable text. Percent-encoding keeps
    the on-disk path exactly as it is (nothing here is renamed) while
    making the link itself resolve correctly.
    """

    return quote(f"{folder_name}/VIDEO.md", safe="/")


def migrate_legacy_video_folder(
    output_root: Path, video_id: str, video_root: Path
) -> None:
    """Move a video's old, bare-``video_id`` publication folder (if one
    exists from a prior run of this module, before folders were named
    ``"<title> [<video_id>]"``) to its new location in place.

    A directory rename preserves its entire contents exactly -- VIDEO.md,
    manifest.json, and every hard-linked file under evidence/ -- without
    touching the archive/object store. Never leaves both the old and new
    folder behind: if the new-style folder already exists (e.g. this
    video's title changed since an earlier run under the new naming
    scheme), the legacy folder is left untouched rather than overwritten
    or deleted, and is reported as a stray folder rather than silently
    resolved.
    """

    legacy_root = output_root / video_id

    if legacy_root == video_root:
        return

    if legacy_root.is_dir() and not video_root.exists():
        legacy_root.rename(video_root)


def load_video_collection_names(database) -> dict[str, list[str]]:
    """Existing collection membership per archived object, read-only.

    Reuses the database's own pre-existing ``collections`` /
    ``collection_objects`` tables -- no new metadata is invented. A video
    whose object has no collection membership simply maps to an empty
    list.
    """

    rows = database.execute(
        """
        SELECT co.object_id AS object_id, c.name AS name
        FROM collection_objects AS co
        JOIN collections AS c ON c.collection_id = co.collection_id
        """
    ).fetchall()

    by_object_id: dict[str, list[str]] = defaultdict(list)

    for original in rows:
        row = dict(original)
        name = row["name"]

        # A small number of objects (e.g. GhramXiUrY4's known duplicate
        # acquisition pair, WRS_MASTER_STATE.md §21/§22) have the same
        # collection recorded twice in the database. Not corrected here
        # (no database row is touched) -- only de-duplicated for display,
        # same spirit as the folder-naming fix handling messy real data
        # gracefully rather than failing or showing a confusing repeat.
        if name not in by_object_id[row["object_id"]]:
            by_object_id[row["object_id"]].append(name)

    return by_object_id


def load_video_rows(database, limit: int | None = None) -> list[dict]:
    """Load the most recently acquired YouTube videos, newest first.

    Each row carries its transcript acquisition/object identity. Only
    successful ``youtube`` acquisitions using the transcript-capture
    method are considered a "video acquisition" for publication purposes.
    """

    query = """
        SELECT
            a.acquisition_id,
            a.source_id,
            a.object_id,
            a.acquired_at,
            a.metadata_json AS acquisition_metadata_json,
            s.source_type,
            s.locator,
            s.final_locator,
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
          AND s.source_type = 'youtube'
          AND a.method = 'youtube_caption_json3'
        ORDER BY a.acquired_at DESC, a.acquisition_id DESC
    """

    if limit is not None:
        query += " LIMIT :limit"
        rows = database.execute(query, {"limit": limit}).fetchall()
    else:
        rows = database.execute(query).fetchall()

    return [dict(row) for row in rows]


def load_acquisition_status_summary(database) -> dict:
    """Summarise every ``source_type='youtube'`` row regardless of status.

    This is a read-only reporting addition only: it does not change which
    videos are published. It exists so a publication run can distinguish
    material that was **never successfully acquired** (a ``sources`` row
    exists but no linked ``acquisitions`` row has ``status='success'``)
    from material that **was** acquired successfully but may simply not
    have been published by a given run (e.g. an explicit ``--limit``).
    """

    status_rows = database.execute(
        """
        SELECT a.status AS status, COUNT(*) AS row_count
        FROM sources AS s
        LEFT JOIN acquisitions AS a ON a.source_id = s.source_id
        WHERE s.source_type = 'youtube'
        GROUP BY a.status
        """
    ).fetchall()

    by_status: dict[str, int] = {}
    total_sources = 0

    for row in status_rows:
        mapped = dict(row)
        status_label = mapped["status"] or "no_acquisition_attempt"
        count = mapped["row_count"]
        by_status[status_label] = by_status.get(status_label, 0) + count
        total_sources += count

    channel_rows = database.execute(
        """
        SELECT DISTINCT s.metadata_json AS source_metadata_json
        FROM acquisitions AS a
        JOIN sources AS s ON s.source_id = a.source_id
        WHERE a.status = 'success'
          AND s.source_type = 'youtube'
          AND a.method = 'youtube_caption_json3'
        """
    ).fetchall()

    channels: set[str] = set()

    for original in channel_rows:
        metadata = json_value(dict(original)["source_metadata_json"])
        channel = metadata.get("channel")

        if channel:
            channels.add(str(channel))

    return {
        "total_youtube_sources": total_sources,
        "youtube_sources_by_status": by_status,
        "distinct_channels": sorted(channels),
        "distinct_channel_count": len(channels),
    }


def load_comment_snapshots(database) -> dict[str, list[dict]]:
    """Load successful YouTube comment snapshots, keyed by video_id."""

    rows = database.execute(
        """
        SELECT
            a.acquisition_id,
            a.acquired_at,
            a.metadata_json AS acquisition_metadata_json,
            s.locator,
            s.final_locator,
            s.metadata_json AS source_metadata_json,
            o.sha256
        FROM acquisitions AS a
        JOIN sources AS s ON s.source_id = a.source_id
        JOIN objects AS o ON o.object_id = a.object_id
        WHERE a.status = 'success'
          AND s.source_type = 'youtube_comments'
          AND a.method = 'youtube_comments_ytdlp'
        ORDER BY a.acquired_at
        """
    ).fetchall()

    by_video_id: dict[str, list[dict]] = defaultdict(list)

    for original in rows:
        row = dict(original)
        acquisition_metadata = json_value(row["acquisition_metadata_json"])
        source_metadata = json_value(row["source_metadata_json"])
        video_id = acquisition_metadata.get("video_id") or source_metadata.get(
            "video_id"
        )

        if not video_id:
            continue

        by_video_id[str(video_id)].append(row)

    return by_video_id


def load_transcript_passages(database, acquisition_id: str) -> list[dict]:
    """Load transcript passages for one video's transcript acquisition."""

    rows = database.execute(
        """
        SELECT passage_index, text, metadata_json
        FROM passages
        WHERE acquisition_id = :acquisition_id
        ORDER BY passage_index
        """,
        {"acquisition_id": acquisition_id},
    ).fetchall()

    return [dict(row) for row in rows]


def format_timestamp(start_ms: object) -> str | None:
    """Render a transcript passage's start offset as ``HH:MM:SS``."""

    if not isinstance(start_ms, (int, float)):
        return None

    total_seconds = int(start_ms) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"{minutes:02d}:{seconds:02d}"


def render_transcript_markdown(passages: list[dict]) -> str:
    """Render ordered transcript passages as readable Markdown lines."""

    if not passages:
        return "_No transcript was recorded for this video._"

    lines: list[str] = []

    for passage in passages:
        metadata = json_value(passage["metadata_json"])
        timestamp = format_timestamp(metadata.get("start_ms"))
        text = (passage["text"] or "").strip()

        if not text:
            continue

        if timestamp:
            lines.append(f"**[{timestamp}]** {text}")
        else:
            lines.append(text)

    return "\n\n".join(lines) if lines else (
        "_No transcript was recorded for this video._"
    )


def render_comments_markdown(comments: list[dict]) -> str:
    """Render archived comment records as a readable Markdown list."""

    if not comments:
        return "_No comments were captured for this video._"

    lines: list[str] = []

    for comment in comments:
        text = str(comment.get("text") or "").strip()

        if not text:
            continue

        author = comment.get("author") or "Unknown"
        pinned = " *(pinned)*" if comment.get("is_pinned") else ""
        uploader = (
            " *(uploader)*" if comment.get("author_is_uploader") else ""
        )
        likes = comment.get("like_count")
        like_note = f" · {likes} likes" if likes else ""
        text_indented = text.replace("\n", "\n  ")
        lines.append(
            f"- **{author}**{uploader}{pinned}{like_note}  \n  {text_indented}"
        )

    return "\n".join(lines) if lines else (
        "_No comments were captured for this video._"
    )


def publish_youtube_collection(
    *,
    database,
    object_store: ObjectStore,
    output_root: Path,
    limit: int | None = None,
) -> dict:
    """Publish archived YouTube videos into clickable per-video folders."""

    # Always load every successful acquisition first (cheap: this table is
    # small) so the "distinct successful videos" count used in reporting
    # reflects the whole database, never just whatever window `limit`
    # happens to apply to the publish loop below.
    all_video_rows = load_video_rows(database, limit=None)
    video_rows = all_video_rows if limit is None else all_video_rows[:limit]
    comments_by_video_id = load_comment_snapshots(database)
    acquisition_status_summary = load_acquisition_status_summary(database)
    collection_names_by_object_id = load_video_collection_names(database)

    def _video_id_for_row(row: dict) -> str:
        acquisition_metadata = json_value(row["acquisition_metadata_json"])
        source_metadata = json_value(row["source_metadata_json"])
        return str(
            acquisition_metadata.get("video_id")
            or source_metadata.get("video_id")
            or row["object_id"]
        )

    distinct_successful_video_ids = {
        _video_id_for_row(row) for row in all_video_rows
    }

    # A video can have more than one successful acquisition row (e.g. a
    # re-run that re-detected an already-extracted object) — the loop below
    # still publishes only the newest per video_id, but transcript passages
    # are sometimes linked to an OLDER duplicate's acquisition_id instead of
    # the newest one's (see WRS_MASTER_STATE.md §21/§22: GhramXiUrY4). This
    # index lets the transcript lookup fall back to a sibling duplicate
    # without any database change — read-only, and only ever consulted when
    # the selected row's own passages are empty.
    rows_by_video_id: dict[str, list[dict]] = defaultdict(list)
    for sibling_row in all_video_rows:
        rows_by_video_id[_video_id_for_row(sibling_row)].append(sibling_row)

    output_root.mkdir(parents=True, exist_ok=True)

    published = 0
    with_transcript = 0
    with_comments = 0
    missing_objects: list[dict] = []
    index_entries: list[dict] = []
    seen_video_ids: set[str] = set()

    for row in video_rows:
        source_metadata = json_value(row["source_metadata_json"])
        acquisition_metadata = json_value(row["acquisition_metadata_json"])
        video_id = _video_id_for_row(row)

        if video_id in seen_video_ids:
            continue

        seen_video_ids.add(video_id)

        title = row["title"] or video_id
        original_url = row["locator"] or row["final_locator"] or (
            f"https://www.youtube.com/watch?v={video_id}"
        )
        canonical_url = row["final_locator"] or original_url
        acquired_at = row["acquired_at"]

        folder_name = video_folder_name(title, video_id)
        video_root = output_root / folder_name
        migrate_legacy_video_folder(output_root, video_id, video_root)
        video_root.mkdir(parents=True, exist_ok=True)

        archived_transcript_object = object_store.path_for_hash(row["sha256"])
        transcript_object_present = archived_transcript_object.is_file()

        if not transcript_object_present:
            missing_objects.append(
                {
                    "video_id": video_id,
                    "acquisition_id": row["acquisition_id"],
                    "sha256": row["sha256"],
                    "kind": "transcript_capture",
                }
            )

        passages = load_transcript_passages(database, row["acquisition_id"])
        transcript_passages_acquisition_id = row["acquisition_id"]

        if not passages:
            for sibling_row in rows_by_video_id.get(video_id, []):
                if sibling_row["acquisition_id"] == row["acquisition_id"]:
                    continue

                sibling_passages = load_transcript_passages(
                    database, sibling_row["acquisition_id"]
                )

                if sibling_passages:
                    passages = sibling_passages
                    transcript_passages_acquisition_id = sibling_row[
                        "acquisition_id"
                    ]
                    break

        transcript_markdown = render_transcript_markdown(passages)

        if passages:
            with_transcript += 1

        comment_snapshots = comments_by_video_id.get(video_id, [])
        comments: list[dict] = []
        comment_snapshot_meta: list[dict] = []

        for snapshot_row in comment_snapshots:
            archived_comments_object = object_store.path_for_hash(
                snapshot_row["sha256"]
            )

            if not archived_comments_object.is_file():
                missing_objects.append(
                    {
                        "video_id": video_id,
                        "acquisition_id": snapshot_row["acquisition_id"],
                        "sha256": snapshot_row["sha256"],
                        "kind": "comments_snapshot",
                    }
                )
                continue

            payload = read_archived_json(object_store, snapshot_row["sha256"])
            snapshot_comments = payload.get("comments")

            if isinstance(snapshot_comments, list):
                comments.extend(
                    comment
                    for comment in snapshot_comments
                    if isinstance(comment, dict)
                )

            comment_snapshot_meta.append(
                {
                    "acquisition_id": snapshot_row["acquisition_id"],
                    "sha256": snapshot_row["sha256"],
                    "acquired_at": snapshot_row["acquired_at"],
                }
            )

        if comments:
            with_comments += 1

        comments_markdown = render_comments_markdown(comments)

        evidence_root = video_root / "evidence"
        evidence_links: list[dict] = []

        if transcript_object_present:
            destination = evidence_root / "transcript.json3.json"
            method = materialize_object(
                archived_transcript_object, destination
            )
            evidence_links.append(
                {
                    "label": "Raw transcript capture (json3)",
                    "path": str(destination.relative_to(video_root)),
                    "sha256": row["sha256"],
                    "object_id": row["object_id"],
                    "acquisition_id": row["acquisition_id"],
                    "publication_method": method,
                }
            )

        for index, snapshot_row in enumerate(comment_snapshots):
            archived_comments_object = object_store.path_for_hash(
                snapshot_row["sha256"]
            )

            if not archived_comments_object.is_file():
                continue

            suffix = f"-{index + 1}" if index else ""
            destination = evidence_root / f"comments{suffix}.json"
            method = materialize_object(archived_comments_object, destination)
            evidence_links.append(
                {
                    "label": "Raw comments capture",
                    "path": str(destination.relative_to(video_root)),
                    "sha256": snapshot_row["sha256"],
                    "acquisition_id": snapshot_row["acquisition_id"],
                    "publication_method": method,
                }
            )

        video_markdown = (
            f"# {title}\n\n"
            f"- **Video ID:** `{video_id}`\n"
            f"- **Original URL:** [{original_url}]({original_url})\n"
            f"- **Canonical URL:** [{canonical_url}]({canonical_url})\n"
            f"- **Acquired:** {acquired_at}\n"
            f"- **Channel:** {source_metadata.get('channel') or 'Unknown'}\n"
            f"- **Upload date:** "
            f"{source_metadata.get('upload_date') or 'Unknown'}\n"
            f"- **Transcript acquisition:** `{row['acquisition_id']}`\n"
            + (
                "- **Transcript passages retrieved from duplicate "
                f"acquisition:** `{transcript_passages_acquisition_id}`\n"
                if transcript_passages_acquisition_id != row["acquisition_id"]
                else ""
            )
            + "\n"
            f"## Transcript\n\n"
            f"{transcript_markdown}\n\n"
            f"## Comments\n\n"
            f"{comments_markdown}\n"
        )

        atomic_write_text(video_root / "VIDEO.md", video_markdown)

        manifest = {
            "video_id": video_id,
            "title": title,
            "original_url": original_url,
            "canonical_url": canonical_url,
            "acquired_at": acquired_at,
            "transcript_acquisition_id": row["acquisition_id"],
            "transcript_passages_acquisition_id": transcript_passages_acquisition_id,
            "transcript_object_id": row["object_id"],
            "transcript_sha256": row["sha256"],
            "transcript_passage_count": len(passages),
            "comment_snapshots": comment_snapshot_meta,
            "comment_count": len(comments),
            "evidence": evidence_links,
        }
        atomic_write_text(
            video_root / "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        )

        index_entries.append(
            {
                "video_id": video_id,
                "title": title,
                "folder_name": folder_name,
                "original_url": original_url,
                "acquired_at": str(acquired_at),
                "channel": source_metadata.get("channel"),
                "collections": collection_names_by_object_id.get(
                    row["object_id"], []
                ),
                "has_transcript": bool(passages),
                "has_comments": bool(comments),
                "passage_count": len(passages),
                "comment_count": len(comments),
            }
        )
        published += 1

    index_entries.sort(key=lambda item: item["acquired_at"], reverse=True)

    published_video_ids = {entry["video_id"] for entry in index_entries}
    unpublished_successful_video_ids = sorted(
        distinct_successful_video_ids - published_video_ids
    )

    index_lines = [
        "# Warrigal YouTube Collections",
        "",
        f"Published videos: **{published}** "
        f"(of **{len(distinct_successful_video_ids)}** distinct videos with "
        "a successful archived acquisition in the database)",
        "",
        "Sorted by acquisition date, most recent first. See \"By channel\" "
        "below for the same videos grouped by creator.",
        "",
        "| Acquired | Title | YouTube URL | Channel | Collection | "
        "Transcript | Comments |",
        "|---|---|---|---|---|---|---|",
    ]

    for entry in index_entries:
        relative = video_markdown_link(entry['folder_name'])
        transcript_label = (
            f"Yes ({entry['passage_count']} passages)"
            if entry["has_transcript"]
            else "No"
        )
        comments_label = (
            f"Yes ({entry['comment_count']})" if entry["has_comments"] else "No"
        )
        channel_label = entry["channel"] or "Unknown"
        collection_label = (
            ", ".join(entry["collections"]) if entry["collections"] else "—"
        )
        index_lines.append(
            f"| {entry['acquired_at']} "
            f"| [{entry['title']}]({relative}) "
            f"| {entry['original_url']} "
            f"| {channel_label} "
            f"| {collection_label} "
            f"| {transcript_label} "
            f"| {comments_label} |"
        )

    if unpublished_successful_video_ids:
        index_lines.append("")
        index_lines.append(
            "**Not published by this run "
            f"({len(unpublished_successful_video_ids)}, e.g. a smaller "
            "`--limit` than the database total):** "
            + ", ".join(unpublished_successful_video_ids)
        )

    # A second, channel-first view of the same already-collected entries --
    # no new metadata, no second index/database, just an alternate grouping
    # of data this run already has in memory.
    entries_by_channel: dict[str, list[dict]] = defaultdict(list)

    for entry in index_entries:
        entries_by_channel[entry["channel"] or "Unknown"].append(entry)

    index_lines.append("")
    index_lines.append("## By channel")
    index_lines.append("")

    for channel_name in sorted(entries_by_channel, key=str.casefold):
        channel_entries = sorted(
            entries_by_channel[channel_name],
            key=lambda item: item["acquired_at"],
            reverse=True,
        )
        index_lines.append(f"### {channel_name} ({len(channel_entries)})")
        index_lines.append("")

        for entry in channel_entries:
            relative = video_markdown_link(entry['folder_name'])
            index_lines.append(
                f"- [{entry['title']}]({relative}) — {entry['acquired_at']}"
            )

        index_lines.append("")

    atomic_write_text(
        output_root / "INDEX.md",
        "\n".join(index_lines) + "\n",
    )

    result = {
        "published_videos": published,
        "videos_with_transcript": with_transcript,
        "videos_without_transcript": published - with_transcript,
        "videos_with_comments": with_comments,
        "videos_without_comments": published - with_comments,
        "missing_objects": missing_objects,
        "output_root": str(output_root.resolve()),
        "videos": index_entries,
        # Report-only accounting (added so a partial run, e.g. via --limit,
        # can be distinguished from material that was never successfully
        # acquired at all). None of this changes what gets published.
        "distinct_successful_video_count": len(distinct_successful_video_ids),
        "unpublished_successful_video_ids": unpublished_successful_video_ids,
        "total_youtube_sources": acquisition_status_summary[
            "total_youtube_sources"
        ],
        "youtube_sources_by_status": acquisition_status_summary[
            "youtube_sources_by_status"
        ],
        "distinct_channel_count": acquisition_status_summary[
            "distinct_channel_count"
        ],
        "distinct_channels": acquisition_status_summary["distinct_channels"],
    }

    atomic_write_text(
        output_root / "PUBLICATION_REPORT.json",
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
    )

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish archived YouTube evidence into clickable "
            "human-readable folders."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Publish only the N most recently acquired videos.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database = initialize_database()

    try:
        result = publish_youtube_collection(
            database=database,
            object_store=ObjectStore(),
            output_root=args.output_root.expanduser(),
            limit=args.limit,
        )
    finally:
        database.close()

    print("=== WARRIGAL YOUTUBE PUBLICATION COMPLETE ===")
    print("VIDEOS PUBLISHED THIS RUN:", result["published_videos"])
    print(
        "DISTINCT VIDEOS WITH A SUCCESSFUL ACQUISITION (DB-WIDE):",
        result["distinct_successful_video_count"],
    )
    print(
        "ALL youtube-SOURCE ROWS BY STATUS:",
        result["youtube_sources_by_status"],
    )
    print(
        "DISTINCT CHANNELS AMONG PUBLISHED VIDEOS:",
        result["distinct_channel_count"],
    )
    print("WITH TRANSCRIPT:", result["videos_with_transcript"])
    print("WITHOUT TRANSCRIPT:", result["videos_without_transcript"])
    print("WITH COMMENTS:", result["videos_with_comments"])
    print("WITHOUT COMMENTS:", result["videos_without_comments"])
    print("MISSING OBJECTS:", len(result["missing_objects"]))
    print(
        "SUCCESSFUL BUT NOT PUBLISHED THIS RUN:",
        result["unpublished_successful_video_ids"],
    )
    print("OUTPUT:", result["output_root"])

    return 1 if result["missing_objects"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
