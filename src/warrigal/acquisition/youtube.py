"""YouTube source discovery and metadata extraction for Warrigal."""

from dataclasses import dataclass

import yt_dlp


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    url: str


@dataclass(frozen=True)
class YouTubeVideoMetadata:
    video_id: str
    title: str
    channel: str | None
    channel_id: str | None
    upload_date: str | None
    duration: int | None
    url: str
    description: str | None


def discover_channel_videos(
    channel_url: str,
    *,
    max_videos: int | None = None,
) -> list[YouTubeVideo]:
    """Discover public videos from a YouTube channel URL."""

    options = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
    }

    if max_videos is not None:
        if max_videos < 1:
            raise ValueError("max_videos must be at least 1")
        options["playlistend"] = max_videos

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    entries = info.get("entries") or []
    videos: list[YouTubeVideo] = []

    for entry in entries:
        if not entry:
            continue

        video_id = entry.get("id")
        title = entry.get("title")

        if not video_id or not title:
            continue

        videos.append(
            YouTubeVideo(
                video_id=str(video_id),
                title=str(title),
                url=f"https://www.youtube.com/watch?v={video_id}",
            )
        )

    return videos


def extract_video_metadata(video_url: str) -> YouTubeVideoMetadata:
    """Extract metadata for a public YouTube video without downloading media."""

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(video_url, download=False)

    video_id = info.get("id")
    title = info.get("title")

    if not video_id:
        raise ValueError("YouTube video metadata did not contain a video ID")
    if not title:
        raise ValueError("YouTube video metadata did not contain a title")

    duration = info.get("duration")

    return YouTubeVideoMetadata(
        video_id=str(video_id),
        title=str(title),
        channel=str(info["channel"]) if info.get("channel") is not None else None,
        channel_id=(
            str(info["channel_id"]) if info.get("channel_id") is not None else None
        ),
        upload_date=(
            str(info["upload_date"]) if info.get("upload_date") is not None else None
        ),
        duration=int(duration) if duration is not None else None,
        url=str(
            info.get("webpage_url")
            or f"https://www.youtube.com/watch?v={video_id}"
        ),
        description=(
            str(info["description"]) if info.get("description") is not None else None
        ),
    )
