"""YouTube source discovery and metadata extraction for Warrigal."""

from dataclasses import dataclass
import json
import re

import yt_dlp

from warrigal.acquisition.service import AcquisitionService
from warrigal.models import Passage
from warrigal.models import Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


@dataclass(frozen=True)
class YouTubeDescriptionReference:
    url: str
    index: int
    start_char: int
    end_char: int


def extract_description_references(
    description: str | None,
) -> list[YouTubeDescriptionReference]:
    """Extract structured HTTP(S) references from a YouTube description."""

    if not description:
        return []

    return [
        YouTubeDescriptionReference(
            url=match.group(0),
            index=index,
            start_char=match.start(),
            end_char=match.end(),
        )
        for index, match in enumerate(
            re.finditer(r"https?://[^\s<>]+", description)
        )
    ]


def extract_description_urls(
    description: str | None,
) -> list[str]:
    """Extract explicit HTTP(S) URLs from a YouTube description in source order."""

    return [
        reference.url
        for reference in extract_description_references(description)
    ]


@dataclass(frozen=True)
class YouTubeIngestionResult:
    video_id: str
    object_id: str
    acquisition_id: str
    sha256: str
    passage_count: int
    deduplicated: bool


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    url: str


@dataclass(frozen=True)
class YouTubeChannelIdentity:
    channel_id: str
    title: str
    canonical_url: str


def resolve_youtube_channel(source_url: str) -> YouTubeChannelIdentity:
    """Resolve a channel, handle, or video URL to stable channel identity."""
    if not source_url.strip():
        raise ValueError("YouTube source URL is required")
    options = {
        "extract_flat": True, "quiet": True, "no_warnings": True,
        "skip_download": True, "playlistend": 1,
        "js_runtimes": {"deno": {}},
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(source_url, download=False)
    except Exception as exc:
        raise ValueError(
            f"YouTube could not resolve channel identity for {source_url}: {exc}"
        ) from exc
    if not isinstance(info, dict):
        raise ValueError(f"YouTube returned no channel information for {source_url}")
    channel_id = str(info.get("channel_id") or "")
    title = str(info.get("channel") or info.get("channel_title") or "")
    if not channel_id and str(info.get("_type") or "") in {"playlist", "channel"}:
        channel_id = str(info.get("id") or "")
        title = title or str(info.get("title") or "")
    if not channel_id:
        entries = info.get("entries") or []
        first = next((entry for entry in entries if isinstance(entry, dict)), {})
        channel_id = str(first.get("channel_id") or "")
        title = title or str(first.get("channel") or "")
    if not channel_id:
        raise ValueError(f"YouTube source did not expose a stable channel ID: {source_url}")
    return YouTubeChannelIdentity(
        channel_id=channel_id,
        title=title or channel_id,
        canonical_url=f"https://www.youtube.com/channel/{channel_id}/videos",
    )


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
        "js_runtimes": {"deno": {}},
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
        "js_runtimes": {"deno": {}},
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


def acquire_json3_transcript(
    video_url: str,
    language: str = "en-orig",
) -> bytes:
    """Acquire a public YouTube JSON3 caption track without downloading media."""

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [language],
        "subtitlesformat": "json3",
        "js_runtimes": {"deno": {}},
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(video_url, download=False)

    subtitles = info.get("subtitles") or {}
    automatic_captions = info.get("automatic_captions") or {}

    tracks = subtitles.get(language) or automatic_captions.get(language) or []

    json3_track = next(
        (
            track
            for track in tracks
            if track.get("ext") == "json3" and track.get("url")
        ),
        None,
    )

    if json3_track is None:
        raise ValueError(
            f"No JSON3 caption track found for language {language!r}"
        )

    request = yt_dlp.networking.Request(str(json3_track["url"]))

    with yt_dlp.YoutubeDL(
        {
            "quiet": True,
            "no_warnings": True,
        }
    ) as ydl:
        response = ydl.urlopen(request)
        return response.read()

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




def ingest_video_transcript(
    video_url: str,
    *,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str | None = None,
    language: str = "en-orig",
) -> YouTubeIngestionResult:
    """Acquire, preserve, derive, and persist a YouTube transcript."""

    metadata = extract_video_metadata(video_url)
    description_references = extract_description_references(
        metadata.description
    )
    description_urls = [
        reference.url
        for reference in description_references
    ]

    data = acquire_json3_transcript(
        metadata.url,
        language=language,
    )

    source = Source(
        source_type="youtube",
        locator=video_url,
        final_locator=metadata.url,
        title=metadata.title,
        metadata={
            "video_id": metadata.video_id,
            "channel": metadata.channel,
            "channel_id": metadata.channel_id,
            "upload_date": metadata.upload_date,
            "duration": metadata.duration,
            "description": metadata.description,
            "description_urls": description_urls,
            "description_references": [
                {
                    "url": reference.url,
                    "index": reference.index,
                    "start_char": reference.start_char,
                    "end_char": reference.end_char,
                }
                for reference in description_references
            ],
            "caption_language": language,
            "caption_format": "json3",
        },
    )
    repository.save_source(source)

    service = AcquisitionService(
        repository=repository,
        object_store=object_store,
    )

    acquisition = service.acquire_bytes(
        data=data,
        source_id=source.source_id,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        method="youtube_caption_json3",
        mime_type="application/json",
        original_filename=f"{metadata.video_id}.{language}.json3",
        collection_id=collection_id,
        metadata={
            "video_id": metadata.video_id,
            "video_url": metadata.url,
            "caption_language": language,
            "caption_format": "json3",
        },
    )

    if repository.object_has_passages(acquisition.object_id):
        return YouTubeIngestionResult(
            video_id=metadata.video_id,
            object_id=acquisition.object_id,
            acquisition_id=acquisition.acquisition_id,
            sha256=acquisition.sha256,
            passage_count=0,
            deduplicated=True,
        )

    segments = parse_json3_transcript(data)
    units = build_transcript_sentences(segments)

    passages = transcript_units_to_passages(
        units=units,
        object_id=acquisition.object_id,
        acquisition_id=acquisition.acquisition_id,
        source_url=metadata.url,
        source_title=metadata.title,
    )

    for passage in passages:
        repository.save_passage(passage)

    return YouTubeIngestionResult(
        video_id=metadata.video_id,
        object_id=acquisition.object_id,
        acquisition_id=acquisition.acquisition_id,
        sha256=acquisition.sha256,
        passage_count=len(passages),
        deduplicated=acquisition.deduplicated,
    )

def build_video_transcript_passages(
    video_url: str,
    object_id: str,
    acquisition_id: str,
    source_title: str | None,
    *,
    language: str = "en-orig",
) -> list[Passage]:
    """Acquire and reconstruct a YouTube transcript as Warrigal passages."""

    data = acquire_json3_transcript(
        video_url,
        language=language,
    )
    segments = parse_json3_transcript(data)
    units = build_transcript_sentences(segments)

    return transcript_units_to_passages(
        units=units,
        object_id=object_id,
        acquisition_id=acquisition_id,
        source_url=video_url,
        source_title=source_title,
    )

def transcript_units_to_passages(
    units: list[YouTubeTranscriptUnit],
    object_id: str,
    acquisition_id: str,
    source_url: str,
    source_title: str | None,
) -> list[Passage]:
    """Convert derived YouTube transcript units into searchable passages."""

    return [
        Passage(
            object_id=object_id,
            acquisition_id=acquisition_id,
            passage_index=index,
            text=unit.text,
            source_url=source_url,
            source_title=source_title,
            metadata={
                "start_ms": unit.start_ms,
                "end_ms": unit.end_ms,
                "source_segment_start": unit.source_segment_start,
                "source_start_char": unit.source_start_char,
                "source_segment_end": unit.source_segment_end,
                "source_end_char": unit.source_end_char,
            },
        )
        for index, unit in enumerate(units)
    ]
