"""Bounded acquisition and preservation of public YouTube comments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Mapping

import yt_dlp

from warrigal.acquisition.service import AcquisitionService
from warrigal.models import Passage, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


CommentExtractor = Callable[[str, int | None], Mapping[str, Any]]


@dataclass(frozen=True)
class YouTubeComment:
    comment_id: str
    text: str
    author: str | None
    author_id: str | None
    author_url: str | None
    timestamp: int | None
    parent_id: str | None
    like_count: int | None
    author_is_uploader: bool | None
    author_is_verified: bool | None
    is_pinned: bool | None


@dataclass(frozen=True)
class YouTubeCommentIngestionResult:
    video_id: str
    video_title: str
    object_id: str
    acquisition_id: str
    sha256: str
    collected_count: int
    matched_count: int
    context_count: int
    indexed_count: int
    match_basis: str
    matched_author_ids: tuple[str, ...]
    target_author_id: str | None
    target_author_handle: str | None
    deduplicated: bool


@dataclass(frozen=True)
class YouTubeCommentSnapshotResult:
    """Result of preserving a complete bounded comment snapshot."""

    video_id: str
    video_title: str
    object_id: str
    acquisition_id: str
    sha256: str
    collected_count: int
    deduplicated: bool


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_integer(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_boolean(value: Any) -> bool | None:
    return bool(value) if value is not None else None


def normalize_youtube_handle(value: str | None) -> str | None:
    """Normalize a handle or author URL for cautious fallback matching."""

    if value is None:
        return None

    normalized = value.strip().rstrip("/")
    if "/@" in normalized:
        normalized = "@" + normalized.rsplit("/@", 1)[1]
    elif not normalized.startswith("@"):
        normalized = "@" + normalized

    return normalized.casefold()


def parse_youtube_comments(info: Mapping[str, Any]) -> list[YouTubeComment]:
    """Convert yt-dlp comment dictionaries into a stable evidence schema."""

    comments: list[YouTubeComment] = []
    for raw in info.get("comments") or []:
        if not isinstance(raw, Mapping):
            continue
        comment_id = raw.get("id")
        text = raw.get("text")
        if comment_id is None or text is None:
            continue
        comments.append(
            YouTubeComment(
                comment_id=str(comment_id),
                text=str(text),
                author=_optional_string(raw.get("author")),
                author_id=_optional_string(raw.get("author_id")),
                author_url=_optional_string(raw.get("author_url")),
                timestamp=_optional_integer(raw.get("timestamp")),
                parent_id=_optional_string(raw.get("parent")),
                like_count=_optional_integer(raw.get("like_count")),
                author_is_uploader=_optional_boolean(
                    raw.get("author_is_uploader")
                ),
                author_is_verified=_optional_boolean(
                    raw.get("author_is_verified")
                ),
                is_pinned=_optional_boolean(raw.get("is_pinned")),
            )
        )
    return comments


def extract_youtube_comments(
    video_url: str,
    max_comments: int | None,
) -> Mapping[str, Any]:
    """Collect a bounded public comment snapshot with yt-dlp."""

    if max_comments is not None and max_comments < 1:
        raise ValueError("max_comments must be at least 1")

    options = {
        "getcomments": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"comment_sort": ["new"]}},
    }
    if max_comments is not None:
        options["extractor_args"]["youtube"]["max_comments"] = [str(max_comments)]
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(video_url, download=False)


def _comment_match_basis(
    comment: YouTubeComment,
    *,
    target_author_id: str | None,
    target_author_handle: str | None,
) -> str | None:
    if target_author_id and comment.author_id == target_author_id:
        return "author_id"

    target_handle = normalize_youtube_handle(target_author_handle)
    if target_handle is None:
        return None

    candidates = {
        normalize_youtube_handle(comment.author),
        normalize_youtube_handle(comment.author_url),
    }
    if target_handle in candidates:
        return "author_handle_provisional"
    return None


def select_target_thread_context(
    comments: list[YouTubeComment],
    matches: list[tuple[YouTubeComment, str]],
) -> list[tuple[YouTubeComment, str, str | None]]:
    """Select target comments plus available parents and direct replies."""

    target_basis = {
        comment.comment_id: basis
        for comment, basis in matches
    }
    target_ids = set(target_basis)
    parent_ids = {
        comment.parent_id
        for comment, _ in matches
        if comment.parent_id not in {None, "root"}
    }

    selected: list[tuple[YouTubeComment, str, str | None]] = []
    for comment in comments:
        if comment.comment_id in target_ids:
            selected.append(
                (comment, "target_author", target_basis[comment.comment_id])
            )
        elif comment.comment_id in parent_ids:
            selected.append((comment, "parent_context", None))
        elif comment.parent_id in target_ids:
            selected.append((comment, "reply_context", None))
    return selected


def preserve_youtube_comment_snapshot(
    video_url: str,
    *,
    max_comments: int | None = None,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    extractor: CommentExtractor = extract_youtube_comments,
) -> YouTubeCommentSnapshotResult:
    """Preserve every comment returned by one bounded public snapshot.

    This is deliberately independent of target-author research.  It stores the
    same stable snapshot schema used by ``ingest_youtube_comments`` and leaves
    indexing to the archive-wide comment indexer.
    """

    if max_comments is not None and max_comments < 1:
        raise ValueError("max_comments must be at least 1")

    info = extractor(video_url, max_comments)
    video_id = _optional_string(info.get("id"))
    video_title = _optional_string(info.get("title"))
    if not video_id or not video_title:
        raise ValueError("YouTube comment snapshot lacks video identity")

    final_url = _optional_string(info.get("webpage_url")) or video_url
    comments = parse_youtube_comments(info)
    snapshot = {
        "schema": "warrigal.youtube-comments.v1",
        "video": {
            "id": video_id,
            "title": video_title,
            "url": final_url,
            "channel": _optional_string(info.get("channel")),
            "channel_id": _optional_string(info.get("channel_id")),
        },
        "comments": [asdict(comment) for comment in comments],
    }
    data = (
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")

    source = Source(
        source_type="youtube_comments",
        locator=video_url,
        final_locator=final_url,
        title=f"Comments: {video_title}",
        metadata={
            "video_id": video_id,
            "channel": _optional_string(info.get("channel")),
            "channel_id": _optional_string(info.get("channel_id")),
        },
    )
    repository.save_source(source)
    acquisition = AcquisitionService(repository, object_store).acquire_bytes(
        data=data,
        source_id=source.source_id,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        method="youtube_comments_ytdlp",
        mime_type="application/json",
        original_filename=f"{video_id}.comments.json",
        collection_id=collection_id,
        metadata={
            "video_id": video_id,
            "video_url": final_url,
            "collected_count": len(comments),
            "max_comments": max_comments,
            "snapshot_scope": (
                "all_available_comments"
                if max_comments is None
                else "complete_bounded_snapshot"
            ),
        },
    )
    return YouTubeCommentSnapshotResult(
        video_id=video_id,
        video_title=video_title,
        object_id=acquisition.object_id,
        acquisition_id=acquisition.acquisition_id,
        sha256=acquisition.sha256,
        collected_count=len(comments),
        deduplicated=acquisition.deduplicated,
    )


def ingest_youtube_comments(
    video_url: str,
    *,
    target_author_id: str | None = None,
    target_author_handle: str | None = None,
    max_comments: int = 1000,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    extractor: CommentExtractor = extract_youtube_comments,
) -> YouTubeCommentIngestionResult:
    """Preserve a comment snapshot and index comments by one target author."""

    if not target_author_id and not target_author_handle:
        raise ValueError("A target author ID or handle is required")
    if max_comments < 1:
        raise ValueError("max_comments must be at least 1")

    info = extractor(video_url, max_comments)
    video_id = _optional_string(info.get("id"))
    video_title = _optional_string(info.get("title"))
    if not video_id or not video_title:
        raise ValueError("YouTube comment snapshot lacks video identity")

    final_url = _optional_string(info.get("webpage_url")) or video_url
    comments = parse_youtube_comments(info)
    matches = [
        (comment, basis)
        for comment in comments
        if (
            basis := _comment_match_basis(
                comment,
                target_author_id=target_author_id,
                target_author_handle=target_author_handle,
            )
        )
    ]
    selected_comments = select_target_thread_context(comments, matches)

    snapshot = {
        "schema": "warrigal.youtube-comments.v1",
        "video": {
            "id": video_id,
            "title": video_title,
            "url": final_url,
            "channel": _optional_string(info.get("channel")),
            "channel_id": _optional_string(info.get("channel_id")),
        },
        "comments": [asdict(comment) for comment in comments],
    }
    data = (
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")

    source = Source(
        source_type="youtube_comments",
        locator=video_url,
        final_locator=final_url,
        title=f"Comments: {video_title}",
        metadata={
            "video_id": video_id,
            "channel": _optional_string(info.get("channel")),
            "channel_id": _optional_string(info.get("channel_id")),
        },
    )
    repository.save_source(source)
    acquisition = AcquisitionService(repository, object_store).acquire_bytes(
        data=data,
        source_id=source.source_id,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        method="youtube_comments_ytdlp",
        mime_type="application/json",
        original_filename=f"{video_id}.comments.json",
        collection_id=collection_id,
        metadata={
            "video_id": video_id,
            "video_url": final_url,
            "collected_count": len(comments),
            "max_comments": max_comments,
            "target_author_id": target_author_id,
            "target_author_handle": target_author_handle,
        },
    )

    existing_rows = repository.get_passages_for_object(acquisition.object_id)
    existing_comment_ids: set[str] = set()
    next_passage_index = 0
    for row in existing_rows:
        next_passage_index = max(next_passage_index, row["passage_index"] + 1)
        try:
            existing_metadata = json.loads(row["metadata_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        comment_id = existing_metadata.get("comment_id")
        if comment_id is not None:
            existing_comment_ids.add(str(comment_id))

    indexed_count = 0
    for comment, context_role, basis in selected_comments:
        if comment.comment_id in existing_comment_ids:
            continue
        repository.save_passage(
            Passage(
                object_id=acquisition.object_id,
                acquisition_id=acquisition.acquisition_id,
                passage_index=next_passage_index,
                text=comment.text,
                source_url=(
                    f"{final_url}&lc={comment.comment_id}"
                    if "?" in final_url
                    else f"{final_url}?lc={comment.comment_id}"
                ),
                source_title=video_title,
                metadata={
                    **asdict(comment),
                    "video_id": video_id,
                    "context_role": context_role,
                    "match_basis": basis,
                    "evidence_status": (
                        "explicit_identity"
                        if basis == "author_id"
                        else "provisional_identity"
                        if basis == "author_handle_provisional"
                        else "context_only"
                    ),
                },
            )
        )
        existing_comment_ids.add(comment.comment_id)
        next_passage_index += 1
        indexed_count += 1

    bases = {basis for _, basis in matches}
    match_basis = (
        "author_id"
        if "author_id" in bases
        else "author_handle_provisional"
        if bases
        else "none"
    )
    return YouTubeCommentIngestionResult(
        video_id=video_id,
        video_title=video_title,
        object_id=acquisition.object_id,
        acquisition_id=acquisition.acquisition_id,
        sha256=acquisition.sha256,
        collected_count=len(comments),
        matched_count=len(matches),
        context_count=len(selected_comments) - len(matches),
        indexed_count=indexed_count,
        match_basis=match_basis,
        matched_author_ids=tuple(sorted({
            comment.author_id
            for comment, _ in matches
            if comment.author_id is not None
        })),
        target_author_id=target_author_id,
        target_author_handle=target_author_handle,
        deduplicated=acquisition.deduplicated,
    )
