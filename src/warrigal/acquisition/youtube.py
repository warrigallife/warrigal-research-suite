"""YouTube source discovery for Warrigal."""

from dataclasses import dataclass

import yt_dlp


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    url: str


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
