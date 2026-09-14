"""Bounded preservation and indexing of public YouTube Community posts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from warrigal.acquisition.service import AcquisitionService
from warrigal.models import Passage, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


PostExtractor = Callable[[str, int, int], Mapping[str, Any]]


@dataclass(frozen=True)
class YouTubePost:
    post_id: str
    text: str
    author: str | None
    author_id: str | None
    author_url: str | None
    published_text: str | None
    like_count: str | None
    reply_count: str | None
    attachments: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class YouTubePostIngestionResult:
    channel_id: str
    channel_title: str
    object_id: str
    acquisition_id: str
    sha256: str
    collected_count: int
    new_count: int
    indexed_count: int
    deduplicated: bool


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    if isinstance(value.get("simpleText"), str):
        return value["simpleText"]
    runs = value.get("runs")
    if isinstance(runs, list):
        parts = [
            str(run.get("text"))
            for run in runs
            if isinstance(run, Mapping) and run.get("text") is not None
        ]
        return "".join(parts) or None
    return None


def _walk(value: Any) -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(child, Mapping):
                yield str(key), child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _scalar_values(value: Any, wanted_key: str) -> list[str]:
    values: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == wanted_key and isinstance(child, str):
                values.append(child)
            values.extend(_scalar_values(child, wanted_key))
    elif isinstance(value, list):
        for child in value:
            values.extend(_scalar_values(child, wanted_key))
    return values


def _first_mapping(value: Any, wanted_key: str) -> Mapping[str, Any] | None:
    for key, child in _walk(value):
        if key == wanted_key:
            return child
    return None


def _renderer_attachments(renderer: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    attachment = renderer.get("backstageAttachment")
    if not isinstance(attachment, Mapping):
        return ()
    results: list[dict[str, Any]] = []
    for kind, payload in attachment.items():
        if not isinstance(payload, Mapping):
            continue
        urls = set(_scalar_values(payload, "url"))
        record: dict[str, Any] = {"type": str(kind)}
        for key in ("videoId", "playlistId", "title"):
            if payload.get(key) is not None:
                record[key] = payload[key]
        if urls:
            record["urls"] = sorted(urls)
        results.append(record)
    return tuple(results)


def parse_youtube_posts(payload: Mapping[str, Any]) -> list[YouTubePost]:
    """Extract stable post evidence from YouTube renderer JSON."""

    posts: list[YouTubePost] = []
    seen: set[str] = set()
    for key, renderer in _walk(payload):
        if key not in {"backstagePostRenderer", "postRenderer"}:
            continue
        post_id = renderer.get("postId") or renderer.get("id")
        text = _text(renderer.get("contentText")) or _text(renderer.get("content"))
        if post_id is None or text is None or str(post_id) in seen:
            continue
        author_endpoint = renderer.get("authorEndpoint")
        if not isinstance(author_endpoint, Mapping):
            author_endpoint = {}
        browse = author_endpoint.get("browseEndpoint")
        if not isinstance(browse, Mapping):
            browse = _first_mapping(renderer.get("authorText"), "browseEndpoint") or {}
        canonical = browse.get("canonicalBaseUrl")
        author_url = (
            urljoin("https://www.youtube.com", str(canonical))
            if canonical
            else None
        )
        posts.append(
            YouTubePost(
                post_id=str(post_id),
                text=text,
                author=_text(renderer.get("authorText")),
                author_id=str(browse["browseId"]) if browse.get("browseId") else None,
                author_url=author_url,
                published_text=_text(renderer.get("publishedTimeText")),
                like_count=_text(renderer.get("voteCount")),
                reply_count=(
                    _text(renderer.get("replyCount"))
                    or _text(renderer.get("replyCountText"))
                ),
                attachments=_renderer_attachments(renderer),
            )
        )
        seen.add(str(post_id))
    return posts


def _balanced_json_after(html: str, marker: str) -> Mapping[str, Any] | None:
    start = html.find(marker)
    if start < 0:
        return None
    start = html.find("{", start + len(marker))
    if start < 0:
        return None
    depth = 0
    quoted = escaped = False
    for index in range(start, len(html)):
        char = html[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(html[start:index + 1])
                return value if isinstance(value, Mapping) else None
    return None


def _continuation_token(payload: Mapping[str, Any]) -> str | None:
    for key, value in _walk(payload):
        if key == "continuationCommand" and value.get("token"):
            return str(value["token"])
        if key == "nextContinuationData" and value.get("continuation"):
            return str(value["continuation"])
    return None


def _channel_identity(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    for key, renderer in _walk(payload):
        if key == "channelMetadataRenderer":
            channel_id = renderer.get("externalId")
            title = renderer.get("title")
            return (
                str(channel_id) if channel_id else None,
                str(title) if title else None,
            )
    return None, None


def extract_youtube_posts(
    channel_url: str,
    max_posts: int,
    max_pages: int,
) -> Mapping[str, Any]:
    """Fetch bounded public Community-post renderer pages without media."""

    if max_posts < 1 or max_pages < 1:
        raise ValueError("post extraction bounds must be at least 1")
    posts_url = channel_url.rstrip("/")
    if not posts_url.endswith("/posts"):
        posts_url += "/posts"
    request = Request(posts_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=60) as response:
        html = response.read().decode("utf-8")
        final_url = response.geturl()
    initial = _balanced_json_after(html, "ytInitialData")
    config = _balanced_json_after(html, "ytcfg.set") or {}
    if initial is None:
        raise ValueError("YouTube posts page lacks ytInitialData")

    pages: list[Mapping[str, Any]] = [initial]
    posts = parse_youtube_posts(initial)
    continuation = _continuation_token(initial)
    api_key = config.get("INNERTUBE_API_KEY")
    client_version = config.get("INNERTUBE_CLIENT_VERSION")
    visitor_data = config.get("VISITOR_DATA")
    while continuation and len(pages) < max_pages and len(posts) < max_posts:
        if not api_key or not client_version:
            break
        body = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": client_version,
                    "visitorData": visitor_data,
                }
            },
            "continuation": continuation,
        }
        browse_request = Request(
            f"https://www.youtube.com/youtubei/v1/browse?key={api_key}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        with urlopen(browse_request, timeout=60) as response:
            page = json.loads(response.read().decode("utf-8"))
        if not isinstance(page, Mapping):
            break
        pages.append(page)
        posts = parse_youtube_posts({"pages": pages})
        continuation = _continuation_token(page)

    extracted_channel_id, extracted_channel_title = _channel_identity(initial)
    channel_id = str(config.get("CHANNEL_ID") or extracted_channel_id or "unknown")
    return {
        "channel_url": final_url,
        "channel_id": channel_id,
        "channel_title": str(
            config.get("CHANNEL_NAME") or extracted_channel_title or channel_id
        ),
        "posts": [asdict(post) for post in posts[:max_posts]],
        "pages_fetched": len(pages),
        "raw_pages": pages,
    }


class YouTubePostCheckpointStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self, channel_url: str) -> set[str]:
        if not self.path.exists():
            return set()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("channel_url") != channel_url:
            raise ValueError("Post checkpoint belongs to a different channel")
        return {str(value) for value in payload.get("post_ids", [])}

    def save(self, channel_url: str, post_ids: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        payload = {
            "channel_url": channel_url,
            "post_ids": sorted(post_ids),
        }
        temporary.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def ingest_youtube_posts(
    channel_url: str,
    *,
    checkpoint_path: str | Path,
    max_posts: int,
    max_pages: int,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    extractor: PostExtractor = extract_youtube_posts,
) -> YouTubePostIngestionResult:
    """Preserve a raw post snapshot and index previously unseen post text."""

    info = extractor(channel_url, max_posts, max_pages)
    posts = [
        YouTubePost(**raw)
        for raw in info.get("posts", [])
        if isinstance(raw, dict)
    ]
    channel_id = str(info.get("channel_id") or "")
    channel_title = str(info.get("channel_title") or "")
    final_url = str(info.get("channel_url") or channel_url)
    if not channel_id or not channel_title:
        raise ValueError("YouTube post snapshot lacks channel identity")
    snapshot = {
        "schema": "warrigal.youtube-posts.v1",
        **dict(info),
        "posts": [asdict(post) for post in posts],
    }
    data = (
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    source = Source(
        source_type="youtube_posts",
        locator=channel_url,
        final_locator=final_url,
        title=f"Posts: {channel_title}",
        metadata={"channel_id": channel_id},
    )
    repository.save_source(source)
    acquisition = AcquisitionService(repository, object_store).acquire_bytes(
        data=data, source_id=source.source_id, job_id=job_id, node_id=node_id,
        batch_id=batch_id, method="youtube_posts_web", mime_type="application/json",
        original_filename=f"{channel_id}.posts.json", collection_id=collection_id,
        metadata={
            "channel_id": channel_id,
            "channel_url": final_url,
            "collected_count": len(posts),
        },
    )
    checkpoint = YouTubePostCheckpointStore(checkpoint_path)
    completed = checkpoint.load(channel_url)
    new_posts = [post for post in posts if post.post_id not in completed]
    existing_rows = repository.get_passages_for_object(acquisition.object_id)
    next_index = max(
        (int(row["passage_index"]) + 1 for row in existing_rows),
        default=0,
    )
    indexed = 0
    for post in new_posts:
        repository.save_passage(Passage(
            object_id=acquisition.object_id, acquisition_id=acquisition.acquisition_id,
            passage_index=next_index, text=post.text,
            source_url=f"https://www.youtube.com/post/{post.post_id}",
            source_title=channel_title,
            metadata={
                **asdict(post),
                "channel_id": channel_id,
                "content_type": "youtube_community_post",
                "evidence_status": "explicit_source",
            },
        ))
        completed.add(post.post_id)
        checkpoint.save(channel_url, completed)
        next_index += 1
        indexed += 1
    return YouTubePostIngestionResult(
        channel_id=channel_id,
        channel_title=channel_title,
        object_id=acquisition.object_id,
        acquisition_id=acquisition.acquisition_id, sha256=acquisition.sha256,
        collected_count=len(posts), new_count=len(new_posts), indexed_count=indexed,
        deduplicated=acquisition.deduplicated,
    )
