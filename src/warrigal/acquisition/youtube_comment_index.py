"""Local indexing and author discovery for archived YouTube comments."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable, Mapping

from warrigal.models import Passage
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


@dataclass(frozen=True)
class YouTubeCommentIndexResult:
    objects_scanned: int
    snapshots_indexed: int
    comments_seen: int
    already_indexed: int
    passages_created: int
    invalid_snapshots: int


@dataclass(frozen=True)
class YouTubeCommentAuthorSummary:
    identity: str
    author_id: str | None
    handles: tuple[str, ...]
    profile_urls: tuple[str, ...]
    comment_count: int
    video_count: int


def _load_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        metadata = json.loads(row["metadata_json"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _comment_url(video_url: str, comment_id: str) -> str:
    separator = "&" if "?" in video_url else "?"
    return f"{video_url}{separator}lc={comment_id}"


def index_archived_youtube_comments(
    *,
    repository: WarrigalRepository,
    object_store: ObjectStore,
) -> YouTubeCommentIndexResult:
    """Index every unique comment from locally archived comment snapshots."""

    acquisitions = repository.list_acquisitions_by_method(
        "youtube_comments_ytdlp"
    )
    object_acquisitions: dict[str, str] = {}
    for acquisition in acquisitions:
        object_acquisitions.setdefault(
            acquisition["object_id"],
            acquisition["acquisition_id"],
        )

    existing_comment_ids: set[str] = set()
    object_next_indexes: dict[str, int] = {}
    for passage in repository.list_passages():
        metadata = _load_metadata(passage)
        comment_id = metadata.get("comment_id")
        if comment_id is not None:
            existing_comment_ids.add(str(comment_id))
        object_id = str(passage["object_id"])
        object_next_indexes[object_id] = max(
            object_next_indexes.get(object_id, 0),
            int(passage["passage_index"]) + 1,
        )

    comments_seen = 0
    already_indexed = 0
    passages_created = 0
    snapshots_indexed = 0
    invalid_snapshots = 0

    for object_id, acquisition_id in object_acquisitions.items():
        object_row = repository.get_object(object_id)
        if object_row is None:
            invalid_snapshots += 1
            continue
        try:
            payload = json.loads(
                object_store.read_bytes(object_row["sha256"])
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            invalid_snapshots += 1
            continue
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != "warrigal.youtube-comments.v1"
            or not isinstance(payload.get("video"), dict)
            or not isinstance(payload.get("comments"), list)
        ):
            invalid_snapshots += 1
            continue

        video = payload["video"]
        video_id = str(video.get("id") or "")
        video_title = str(video.get("title") or "YouTube video")
        video_url = str(video.get("url") or "")
        if not video_id or not video_url:
            invalid_snapshots += 1
            continue
        snapshots_indexed += 1

        for raw_comment in payload["comments"]:
            if not isinstance(raw_comment, dict):
                continue
            comment_id = raw_comment.get("comment_id")
            text = raw_comment.get("text")
            if comment_id is None or text is None:
                continue
            comment_id = str(comment_id)
            comments_seen += 1
            if comment_id in existing_comment_ids:
                already_indexed += 1
                continue

            passage_index = object_next_indexes.get(object_id, 0)
            metadata = dict(raw_comment)
            metadata.update(
                {
                    "comment_id": comment_id,
                    "video_id": video_id,
                    "context_role": "archive_comment",
                    "match_basis": None,
                    "evidence_status": "explicit_source",
                }
            )
            repository.save_passage(
                Passage(
                    object_id=object_id,
                    acquisition_id=acquisition_id,
                    passage_index=passage_index,
                    text=str(text),
                    source_url=_comment_url(video_url, comment_id),
                    source_title=video_title,
                    metadata=metadata,
                )
            )
            object_next_indexes[object_id] = passage_index + 1
            existing_comment_ids.add(comment_id)
            passages_created += 1

    return YouTubeCommentIndexResult(
        objects_scanned=len(object_acquisitions),
        snapshots_indexed=snapshots_indexed,
        comments_seen=comments_seen,
        already_indexed=already_indexed,
        passages_created=passages_created,
        invalid_snapshots=invalid_snapshots,
    )


def build_youtube_comment_author_directory(
    passages: Iterable[Mapping[str, Any]],
) -> list[YouTubeCommentAuthorSummary]:
    """Aggregate stable author identities from indexed comment passages."""

    authors: dict[str, dict[str, Any]] = {}
    seen_comments: set[str] = set()
    for passage in passages:
        metadata = _load_metadata(passage)
        comment_id = metadata.get("comment_id")
        if comment_id is None or str(comment_id) in seen_comments:
            continue
        seen_comments.add(str(comment_id))
        author_id = metadata.get("author_id")
        author = metadata.get("author")
        author_url = metadata.get("author_url")
        identity = str(author_id or author_url or author or "unknown")
        record = authors.setdefault(
            identity,
            {
                "author_id": str(author_id) if author_id else None,
                "handles": set(),
                "profile_urls": set(),
                "comments": 0,
                "videos": set(),
            },
        )
        if author:
            record["handles"].add(str(author))
        if author_url:
            record["profile_urls"].add(str(author_url))
        record["comments"] += 1
        if metadata.get("video_id"):
            record["videos"].add(str(metadata["video_id"]))

    return sorted(
        (
            YouTubeCommentAuthorSummary(
                identity=identity,
                author_id=record["author_id"],
                handles=tuple(sorted(record["handles"], key=str.casefold)),
                profile_urls=tuple(
                    sorted(record["profile_urls"], key=str.casefold)
                ),
                comment_count=record["comments"],
                video_count=len(record["videos"]),
            )
            for identity, record in authors.items()
        ),
        key=lambda author: (-author.comment_count, author.identity.casefold()),
    )


def find_youtube_comment_authors(
    passages: Iterable[Mapping[str, Any]],
    query: str,
) -> list[YouTubeCommentAuthorSummary]:
    """Find archived authors by stable ID, known handle, or profile URL."""

    needle = query.strip().casefold()
    if not needle:
        raise ValueError("author query must not be empty")
    return [
        author
        for author in build_youtube_comment_author_directory(passages)
        if needle in author.identity.casefold()
        or any(needle in handle.casefold() for handle in author.handles)
        or any(needle in url.casefold() for url in author.profile_urls)
    ]


def comments_by_author(
    passages: Iterable[Mapping[str, Any]],
    author_identity: str,
) -> list[Mapping[str, Any]]:
    """Return indexed comments belonging to a stable ID or exact handle."""

    needle = author_identity.strip().casefold()
    if not needle:
        raise ValueError("author identity must not be empty")
    matches = []
    seen_comments: set[str] = set()
    for passage in passages:
        metadata = _load_metadata(passage)
        comment_id = metadata.get("comment_id")
        identities = {
            str(value).casefold()
            for value in (
                metadata.get("author_id"),
                metadata.get("author"),
                metadata.get("author_url"),
            )
            if value
        }
        if (
            comment_id is not None
            and str(comment_id) not in seen_comments
            and needle in identities
        ):
            seen_comments.add(str(comment_id))
            matches.append(passage)
    return matches
