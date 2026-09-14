"""Checkpointed comment acquisition across a bounded YouTube channel view."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from warrigal.acquisition.youtube import YouTubeVideo, discover_channel_videos
from warrigal.acquisition.youtube_comments import (
    YouTubeCommentIngestionResult,
    ingest_youtube_comments,
)
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


VideoDiscoverer = Callable[..., list[YouTubeVideo]]
CommentIngestor = Callable[..., YouTubeCommentIngestionResult]


@dataclass(frozen=True)
class YouTubeCommentCampaignItem:
    video_id: str
    title: str
    url: str
    status: str
    collected_count: int = 0
    matched_count: int = 0
    context_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class YouTubeCommentCampaignResult:
    channel_url: str
    discovered_count: int
    selected_count: int
    completed_count: int
    failed_count: int
    matched_count: int
    context_count: int
    items: tuple[YouTubeCommentCampaignItem, ...]


class YouTubeCommentCheckpointStore:
    """Persist per-video campaign progress outside the evidence archive."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(
        self,
        channel_url: str,
        target_author_id: str,
    ) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("YouTube comment checkpoint must be an object")
        if payload.get("channel_url") != channel_url:
            raise ValueError("Checkpoint belongs to a different channel")
        if payload.get("target_author_id") != target_author_id:
            raise ValueError("Checkpoint belongs to a different target author")
        videos = payload.get("videos", {})
        if not isinstance(videos, dict):
            raise ValueError("Checkpoint videos must be an object")
        return {
            str(video_id): dict(record)
            for video_id, record in videos.items()
            if isinstance(record, dict)
        }

    def save(
        self,
        channel_url: str,
        target_author_id: str,
        videos: dict[str, dict[str, Any]],
    ) -> None:
        payload = {
            "channel_url": channel_url,
            "target_author_id": target_author_id,
            "videos": videos,
        }
        text = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self.path)


def run_youtube_comment_campaign(
    channel_url: str,
    *,
    target_author_id: str,
    target_author_handle: str | None = None,
    checkpoint_path: str | Path,
    scan_videos: int = 100,
    max_videos: int = 5,
    max_comments: int = 1000,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    discoverer: VideoDiscoverer = discover_channel_videos,
    ingestor: CommentIngestor = ingest_youtube_comments,
) -> YouTubeCommentCampaignResult:
    """Process the next bounded group of unfinished channel videos."""

    if not target_author_id:
        raise ValueError("target_author_id is required for channel campaigns")
    if scan_videos < 1 or max_videos < 1 or max_comments < 1:
        raise ValueError("campaign bounds must be at least 1")

    videos = discoverer(channel_url, max_videos=scan_videos)
    checkpoint_store = YouTubeCommentCheckpointStore(checkpoint_path)
    checkpoint = checkpoint_store.load(channel_url, target_author_id)
    unfinished = [
        video
        for video in videos
        if checkpoint.get(video.video_id, {}).get("status") != "completed"
    ]
    never_attempted = [
        video for video in unfinished if video.video_id not in checkpoint
    ]
    failed = [
        video
        for video in unfinished
        if checkpoint.get(video.video_id, {}).get("status") == "failed"
    ]
    selected = (never_attempted + failed)[:max_videos]

    selected_ids = {video.video_id for video in selected}
    items: list[YouTubeCommentCampaignItem] = []
    for video in videos:
        previous = checkpoint.get(video.video_id, {})
        if video.video_id not in selected_ids:
            status = (
                "skipped_checkpoint"
                if previous.get("status") == "completed"
                else "not_selected"
            )
            items.append(
                YouTubeCommentCampaignItem(
                    video_id=video.video_id,
                    title=video.title,
                    url=video.url,
                    status=status,
                    collected_count=int(previous.get("collected_count", 0)),
                    matched_count=int(previous.get("matched_count", 0)),
                    context_count=int(previous.get("context_count", 0)),
                )
            )
            continue

        attempts = int(previous.get("attempts", 0)) + 1
        try:
            result = ingestor(
                video.url,
                target_author_id=target_author_id,
                target_author_handle=target_author_handle,
                max_comments=max_comments,
                repository=repository,
                object_store=object_store,
                job_id=job_id,
                node_id=node_id,
                batch_id=batch_id,
                collection_id=collection_id,
            )
            record = {
                "status": "completed",
                "title": video.title,
                "url": video.url,
                "attempts": attempts,
                "object_id": result.object_id,
                "acquisition_id": result.acquisition_id,
                "collected_count": result.collected_count,
                "matched_count": result.matched_count,
                "context_count": result.context_count,
            }
            item = YouTubeCommentCampaignItem(
                video_id=video.video_id,
                title=video.title,
                url=video.url,
                status="completed",
                collected_count=result.collected_count,
                matched_count=result.matched_count,
                context_count=result.context_count,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            record = {
                "status": "failed",
                "title": video.title,
                "url": video.url,
                "attempts": attempts,
                "error": error,
            }
            item = YouTubeCommentCampaignItem(
                video_id=video.video_id,
                title=video.title,
                url=video.url,
                status="failed",
                error=error,
            )
        checkpoint[video.video_id] = record
        checkpoint_store.save(channel_url, target_author_id, checkpoint)
        items.append(item)

    attempted = [item for item in items if item.video_id in selected_ids]
    return YouTubeCommentCampaignResult(
        channel_url=channel_url,
        discovered_count=len(videos),
        selected_count=len(selected),
        completed_count=sum(item.status == "completed" for item in attempted),
        failed_count=sum(item.status == "failed" for item in attempted),
        matched_count=sum(item.matched_count for item in attempted),
        context_count=sum(item.context_count for item in attempted),
        items=tuple(items),
    )
