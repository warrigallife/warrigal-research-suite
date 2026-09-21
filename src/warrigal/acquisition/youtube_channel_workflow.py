"""Checkpointed, inventory-led acquisition of a public YouTube channel."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Callable

from warrigal.acquisition.service import AcquisitionService
from warrigal.acquisition.youtube import (
    YouTubeVideo,
    discover_channel_videos,
    ingest_video_transcript,
)
from warrigal.acquisition.youtube_comment_index import (
    index_archived_youtube_comments,
)
from warrigal.acquisition.youtube_comments import (
    preserve_youtube_comment_snapshot,
)
from warrigal.acquisition.youtube_posts import ingest_youtube_posts
from warrigal.models import Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


Discoverer = Callable[..., list[YouTubeVideo]]
StageCallable = Callable[..., Any]


def _channel_checkpoint_key(channel_url: object) -> str:
    """Treat canonical channel roots and their /videos tab as one channel."""

    value = str(channel_url or "").strip().rstrip("/")
    if value.endswith("/videos"):
        value = value[:-7].rstrip("/")
    return value


@dataclass(frozen=True)
class YouTubeChannelWorkflowItem:
    video_id: str
    title: str
    url: str
    transcript_status: str
    comments_status: str
    error_count: int


@dataclass(frozen=True)
class YouTubeChannelWorkflowResult:
    channel_url: str
    inventory_object_id: str
    discovered_count: int
    selected_count: int
    completed_count: int
    failed_count: int
    unavailable_transcript_count: int
    acquired_transcript_count: int
    comments_collected: int
    community_posts_status: str
    community_posts_collected: int
    community_posts_new: int
    community_posts_deduplicated: bool | None
    indexed_comment_count: int
    comment_index_scope: str
    items: tuple[YouTubeChannelWorkflowItem, ...]


class YouTubeChannelCheckpointStore:
    """Atomic per-stage progress for one channel URL."""

    schema = "warrigal.youtube-channel-checkpoint.v1"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self, channel_url: str) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema": self.schema,
                "channel_url": channel_url,
                "videos": {},
                "community_posts": {"status": "pending"},
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("YouTube channel checkpoint must be an object")
        if payload.get("schema") != self.schema:
            raise ValueError("Unsupported YouTube channel checkpoint schema")
        if _channel_checkpoint_key(
            payload.get("channel_url")
        ) != _channel_checkpoint_key(channel_url):
            raise ValueError("Checkpoint belongs to a different channel")
        payload["channel_url"] = channel_url
        if not isinstance(payload.get("videos"), dict):
            raise ValueError("Checkpoint videos must be an object")
        payload.setdefault("community_posts", {"status": "pending"})
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def preserve_youtube_channel_inventory(
    channel_url: str,
    videos: list[YouTubeVideo],
    *,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
) -> Any:
    """Preserve the normalized channel inventory used by this workflow run."""

    payload = {
        "schema": "warrigal.youtube-channel-inventory.v1",
        "channel_url": channel_url,
        "video_count": len(videos),
        "videos": [asdict(video) for video in videos],
    }
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    source = Source(
        source_type="youtube_channel_inventory",
        locator=channel_url,
        final_locator=channel_url,
        title=f"YouTube channel inventory: {channel_url}",
        metadata={"video_count": len(videos)},
    )
    repository.save_source(source)
    return AcquisitionService(repository, object_store).acquire_bytes(
        data=data,
        source_id=source.source_id,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        method="youtube_channel_inventory_ytdlp",
        mime_type="application/json",
        original_filename="youtube-channel-inventory.json",
        collection_id=collection_id,
        metadata={"channel_url": channel_url, "video_count": len(videos)},
    )


def _stage_complete(record: dict[str, Any], stage: str) -> bool:
    status = record.get(stage, {}).get("status")
    return status in {"completed", "unavailable"}


def _no_caption_error(exc: Exception) -> bool:
    return (
        isinstance(exc, ValueError)
        and "No JSON3 caption track found" in str(exc)
    )


def run_youtube_channel_workflow(
    channel_url: str,
    *,
    checkpoint_path: str | Path,
    posts_checkpoint_path: str | Path,
    scan_videos: int = 0,
    max_videos: int = 0,
    max_comments: int = 0,
    max_posts: int = 1000,
    max_post_pages: int = 100,
    stages: tuple[str, ...] = ("transcripts", "comments", "posts", "index"),
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    discoverer: Discoverer = discover_channel_videos,
    inventory_preserver: StageCallable = preserve_youtube_channel_inventory,
    transcript_ingestor: StageCallable = ingest_video_transcript,
    comment_preserver: StageCallable = preserve_youtube_comment_snapshot,
    posts_ingestor: StageCallable = ingest_youtube_posts,
    comment_indexer: StageCallable = index_archived_youtube_comments,
) -> YouTubeChannelWorkflowResult:
    """Acquire the next unfinished videos and channel-level post evidence."""

    if not channel_url.strip():
        raise ValueError("channel_url is required")
    supported_stages = {"inventory", "transcripts", "comments", "posts", "index"}
    unknown_stages = set(stages) - supported_stages
    if unknown_stages:
        raise ValueError(f"Unsupported YouTube workflow stages: {sorted(unknown_stages)}")
    if scan_videos < 0 or max_videos < 0:
        raise ValueError("video bounds cannot be negative")
    if max_comments < 0 or max_posts < 1 or max_post_pages < 1:
        raise ValueError("comment bound cannot be negative; post bounds must be at least 1")

    videos = discoverer(
        channel_url,
        max_videos=scan_videos or None,
    )
    inventory = inventory_preserver(
        channel_url,
        videos,
        repository=repository,
        object_store=object_store,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        collection_id=collection_id,
    )

    store = YouTubeChannelCheckpointStore(checkpoint_path)
    checkpoint = store.load(channel_url)
    checkpoint["inventory"] = {
        "object_id": inventory.object_id,
        "acquisition_id": inventory.acquisition_id,
        "sha256": inventory.sha256,
        "discovered_count": len(videos),
    }
    records: dict[str, dict[str, Any]] = checkpoint["videos"]
    video_stages = set(stages) & {"transcripts", "comments"}
    unfinished = [
        video for video in videos
        if any(
            not _stage_complete(
                records.get(video.video_id, {}),
                "transcript" if stage == "transcripts" else "comments",
            )
            for stage in video_stages
        )
    ]
    selected = unfinished[:max_videos] if max_videos else unfinished

    for video in selected:
        record = records.setdefault(
            video.video_id,
            {"title": video.title, "url": video.url},
        )
        record["title"] = video.title
        record["url"] = video.url

        if "transcripts" in stages and not _stage_complete(record, "transcript"):
            previous = record.get("transcript", {})
            attempts = int(previous.get("attempts", 0)) + 1
            try:
                result = transcript_ingestor(
                    video.url,
                    repository=repository,
                    object_store=object_store,
                    job_id=job_id,
                    node_id=node_id,
                    batch_id=batch_id,
                    collection_id=collection_id,
                )
                record["transcript"] = {
                    "status": "completed",
                    "attempts": attempts,
                    "object_id": result.object_id,
                    "acquisition_id": result.acquisition_id,
                    "passage_count": result.passage_count,
                }
            except Exception as exc:
                record["transcript"] = {
                    "status": "unavailable" if _no_caption_error(exc) else "failed",
                    "attempts": attempts,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            store.save(checkpoint)

        if "comments" in stages and not _stage_complete(record, "comments"):
            previous = record.get("comments", {})
            attempts = int(previous.get("attempts", 0)) + 1
            try:
                result = comment_preserver(
                    video.url,
                    max_comments=max_comments or None,
                    repository=repository,
                    object_store=object_store,
                    job_id=job_id,
                    node_id=node_id,
                    batch_id=batch_id,
                    collection_id=collection_id,
                )
                record["comments"] = {
                    "status": "completed",
                    "attempts": attempts,
                    "object_id": result.object_id,
                    "acquisition_id": result.acquisition_id,
                    "collected_count": result.collected_count,
                }
            except Exception as exc:
                record["comments"] = {
                    "status": "failed",
                    "attempts": attempts,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            store.save(checkpoint)

    posts_status = checkpoint.get("community_posts", {}).get("status", "pending")
    if "posts" in stages:
        try:
            posts = posts_ingestor(
                channel_url,
                checkpoint_path=posts_checkpoint_path,
                max_posts=max_posts,
                max_pages=max_post_pages,
                repository=repository,
                object_store=object_store,
                job_id=job_id,
                node_id=node_id,
                batch_id=batch_id,
                collection_id=collection_id,
            )
            checkpoint["community_posts"] = {
                "status": "completed",
                "object_id": posts.object_id,
                "acquisition_id": posts.acquisition_id,
                "collected_count": posts.collected_count,
                "new_count": posts.new_count,
                "deduplicated": getattr(posts, "deduplicated", None),
            }
            posts_status = "completed"
        except Exception as exc:
            checkpoint["community_posts"] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            posts_status = "failed"
        store.save(checkpoint)

    indexed_comment_count = 0
    if "index" in stages:
        index_result = comment_indexer(
            repository=repository,
            object_store=object_store,
            source_urls={video.url for video in videos},
        )
        indexed_comment_count = int(index_result.passages_created)

    items: list[YouTubeChannelWorkflowItem] = []
    selected_ids = {video.video_id for video in selected}
    for video in videos:
        record = records.get(video.video_id, {})
        transcript_status = record.get("transcript", {}).get("status", "pending")
        comments_status = record.get("comments", {}).get("status", "pending")
        items.append(YouTubeChannelWorkflowItem(
            video_id=video.video_id,
            title=video.title,
            url=video.url,
            transcript_status=transcript_status,
            comments_status=comments_status,
            error_count=sum(
                status == "failed"
                for status in (transcript_status, comments_status)
            ),
        ))

    attempted = [item for item in items if item.video_id in selected_ids]
    completed = [
        item for item in attempted
        if (
            "transcripts" not in stages
            or item.transcript_status in {"completed", "unavailable"}
        )
        and ("comments" not in stages or item.comments_status == "completed")
    ]
    return YouTubeChannelWorkflowResult(
        channel_url=channel_url,
        inventory_object_id=inventory.object_id,
        discovered_count=len(videos),
        selected_count=len(selected),
        completed_count=len(completed),
        failed_count=sum(item.error_count > 0 for item in attempted),
        unavailable_transcript_count=sum(
            item.transcript_status == "unavailable" for item in items
        ),
        acquired_transcript_count=sum(
            item.transcript_status == "completed" for item in items
        ),
        comments_collected=sum(
            int(record.get("comments", {}).get("collected_count", 0))
            for record in records.values()
        ),
        community_posts_status=posts_status,
        community_posts_collected=int(
            checkpoint.get("community_posts", {}).get("collected_count", 0)
        ),
        community_posts_new=int(
            checkpoint.get("community_posts", {}).get("new_count", 0)
        ),
        community_posts_deduplicated=(
            checkpoint.get("community_posts", {}).get("deduplicated")
        ),
        indexed_comment_count=indexed_comment_count,
        comment_index_scope=(
            "channel_inventory" if "index" in stages else "not_run"
        ),
        items=tuple(items),
    )
