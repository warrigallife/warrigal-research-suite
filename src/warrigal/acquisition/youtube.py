"""YouTube source discovery and metadata extraction for Warrigal."""

from dataclasses import dataclass
import json

import yt_dlp


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    url: str


@dataclass(frozen=True)
class YouTubeTranscriptSegment:
    start_ms: int
    duration_ms: int | None
    text: str


@dataclass(frozen=True)
class YouTubeTranscriptUnit:
    start_ms: int
    end_ms: int | None
    text: str
    source_segment_start: int
    source_start_char: int
    source_segment_end: int
    source_end_char: int


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

def parse_json3_transcript(data: bytes | str) -> list[YouTubeTranscriptSegment]:
    """Parse YouTube JSON3 captions while preserving raw event structure."""

    if isinstance(data, bytes):
        data = data.decode("utf-8")

    payload = json.loads(data)
    events = payload.get("events") or []
    segments: list[YouTubeTranscriptSegment] = []

    for event in events:
        caption_parts = event.get("segs") or []
        text = "".join(
            str(part.get("utf8", ""))
            for part in caption_parts
        ).strip()

        if not text:
            continue

        start_ms = event.get("tStartMs")
        if start_ms is None:
            continue

        duration_ms = event.get("dDurationMs")

        segments.append(
            YouTubeTranscriptSegment(
                start_ms=int(start_ms),
                duration_ms=(
                    int(duration_ms)
                    if duration_ms is not None
                    else None
                ),
                text=text,
            )
        )

    return segments

def build_transcript_unit(
    segments: list[YouTubeTranscriptSegment],
    start_index: int,
    end_index: int,
) -> YouTubeTranscriptUnit:
    """Build one derived transcript unit from consecutive raw segments."""

    if start_index < 0:
        raise ValueError("start_index must be at least 0")

    if end_index < start_index:
        raise ValueError("end_index must be greater than or equal to start_index")

    if end_index >= len(segments):
        raise IndexError("end_index is outside the transcript")

    selected = segments[start_index : end_index + 1]

    text = " ".join(
        segment.text.strip()
        for segment in selected
        if segment.text.strip()
    )

    first = selected[0]
    last = selected[-1]

    end_ms = (
        last.start_ms + last.duration_ms
        if last.duration_ms is not None
        else None
    )

    return YouTubeTranscriptUnit(
        start_ms=first.start_ms,
        end_ms=end_ms,
        text=text,
        source_segment_start=start_index,
        source_start_char=0,
        source_segment_end=end_index,
        source_end_char=len(last.text),
    )

def build_transcript_sentences(
    segments: list[YouTubeTranscriptSegment],
) -> list[YouTubeTranscriptUnit]:
    """Build punctuation-delimited transcript units from raw caption segments."""

    units: list[YouTubeTranscriptUnit] = []

    parts: list[str] = []
    source_segment_start: int | None = None
    source_start_char: int | None = None

    for segment_index, segment in enumerate(segments):
        text = segment.text

        position = 0

        while position < len(text):
            if source_segment_start is None:
                while position < len(text) and text[position].isspace():
                    position += 1

                if position >= len(text):
                    break

                source_segment_start = segment_index
                source_start_char = position

            boundary_position = None

            for char_index in range(position, len(text)):
                if text[char_index] in ".?!":
                    boundary_position = char_index
                    break

            if boundary_position is None:
                fragment = text[position:].strip()

                if fragment:
                    parts.append(fragment)

                break

            fragment = text[position : boundary_position + 1].strip()

            if fragment:
                parts.append(fragment)

            sentence_text = " ".join(parts).strip()

            if sentence_text:
                end_ms = (
                    segment.start_ms + segment.duration_ms
                    if segment.duration_ms is not None
                    else None
                )

                units.append(
                    YouTubeTranscriptUnit(
                        start_ms=segments[source_segment_start].start_ms,
                        end_ms=end_ms,
                        text=sentence_text,
                        source_segment_start=source_segment_start,
                        source_start_char=source_start_char,
                        source_segment_end=segment_index,
                        source_end_char=boundary_position + 1,
                    )
                )

            parts = []
            source_segment_start = None
            source_start_char = None
            position = boundary_position + 1

    if source_segment_start is not None and parts:
        last_index = len(segments) - 1
        last = segments[last_index]

        units.append(
            YouTubeTranscriptUnit(
                start_ms=segments[source_segment_start].start_ms,
                end_ms=(
                    last.start_ms + last.duration_ms
                    if last.duration_ms is not None
                    else None
                ),
                text=" ".join(parts).strip(),
                source_segment_start=source_segment_start,
                source_start_char=source_start_char,
                source_segment_end=last_index,
                source_end_char=len(last.text),
            )
        )

    return units

