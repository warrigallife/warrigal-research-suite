"""Shared, side-effect-free workflow plans for Warrigal interfaces."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from warrigal.config import CONFIG, WarrigalConfig


WEBSITE_SMALL_FILE_LIMIT_BYTES = 25 * 1024 * 1024

INSTAGRAM_ACTIONS = (
    "Complete workflow", "Discover inventory", "Acquire / resume", "Verify", "Publish",
)
YOUTUBE_ACTIONS = (
    "Discover channel inventory",
    "Acquire / resume transcripts",
    "Acquire / resume comments",
    "Acquire / resume Community posts",
    "Index archived comments",
    "All research layers",
    "Single-video available caption",
    "Single-video media + Whisper transcript",
)

YOUTUBE_ACTION_HELP = {
    "Discover channel inventory": "List the channel's videos without acquiring transcripts, comments, posts, or media.",
    "Acquire / resume transcripts": "Acquire available YouTube captions for unfinished videos. This does not download video or audio files.",
    "Acquire / resume comments": "Preserve comments for unfinished videos, using the comments-per-video limit.",
    "Acquire / resume Community posts": "Preserve Community posts, using the Community-post limit.",
    "Index archived comments": "Make this channel's already preserved comments searchable. No network acquisition is performed.",
    "All research layers": "Run inventory, available captions, comments, Community posts, and channel-scoped comment indexing. Video/audio media is not included.",
    "Single-video available caption": "Acquire the caption supplied by YouTube for one video URL. No media file is downloaded.",
    "Single-video media + Whisper transcript": "Download and archive one video's media, then transcribe it with the configured local Whisper model.",
}
WEBSITE_ACTIONS = (
    "Discover links",
    "Inventory documents and preserve website sections",
    "Review / select inventoried documents",
    "Acquire / resume selected smaller documents (up to 25 MB)",
    "Acquire / resume smaller documents (up to 25 MB)",
    "Verify selected documents",
    "Verify all inventoried documents",
    "Publish selected documents",
    "Publish all acquired documents",
    "Acquire this URL only",
    "Crawl up to 10 same-site pages",
)


@dataclass(frozen=True)
class WorkflowStep:
    label: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowPlan:
    source_type: str
    target: str
    action: str
    steps: tuple[WorkflowStep, ...]

    def panel_commands(self) -> list[tuple[str, list[str]]]:
        return [(step.label, list(step.command)) for step in self.steps]


def safe_name(value: str) -> str:
    value = value.strip().rstrip("/")
    if "://" in value:
        parsed = urlparse(value)
        parts = [part for part in parsed.path.split("/") if part]
        value = parts[0] if parts else (parsed.hostname or value)
    value = value.lstrip("@").lower()
    return re.sub(r"[^a-z0-9._-]+", "-", value).strip("-.")


def actions_for(source_type: str) -> tuple[str, ...]:
    try:
        return {
            "Instagram": INSTAGRAM_ACTIONS,
            "YouTube": YOUTUBE_ACTIONS,
            "Website": WEBSITE_ACTIONS,
        }[source_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported source type: {source_type}") from exc


def _step(label: str, *command: str) -> WorkflowStep:
    return WorkflowStep(label=label, command=tuple(command))


def _instagram_plan(target: str, action: str, delay: float, config: WarrigalConfig) -> WorkflowPlan:
    profile = safe_name(target)
    if not profile:
        raise ValueError("Enter an Instagram profile name or profile URL.")
    inventory = config.runtime_root / f"{profile}-instagram-inventory.json"
    checkpoint = config.runtime_root / f"{profile}-instagram.checkpoint.json"
    output = config.archive_root / "COLLECTIONS" / "INSTAGRAM"
    steps: list[WorkflowStep] = []
    if action in {"Complete workflow", "Discover inventory"}:
        steps.append(_step("Discovering Instagram inventory", sys.executable, "-m", "warrigal.instagram_profile_inventory", profile, "--output", str(inventory), "--delay", str(delay)))
    if action in {"Complete workflow", "Acquire / resume"}:
        steps.append(_step("Acquiring unfinished Instagram posts", sys.executable, "-m", "warrigal.instagram_browser_campaign", "--inventory", str(inventory), "--checkpoint", str(checkpoint), "--max-posts", "0", "--delay", str(delay)))
    if action in {"Complete workflow", "Verify"}:
        steps.append(_step("Verifying no Instagram posts remain", sys.executable, "-m", "warrigal.instagram_browser_campaign", "--inventory", str(inventory), "--checkpoint", str(checkpoint), "--max-posts", "0", "--delay", str(delay)))
    if action in {"Complete workflow", "Publish"}:
        steps.append(_step("Publishing the Instagram collection", sys.executable, "-m", "warrigal.publish_instagram_collection", "--output-root", str(output), "--profile", profile))
    if action not in INSTAGRAM_ACTIONS:
        raise ValueError("Choose an Instagram workflow action.")
    return WorkflowPlan("Instagram", profile, action, tuple(steps))


def _youtube_plan(
    target: str,
    action: str,
    config: WarrigalConfig,
    *,
    max_videos: int = 0,
    max_comments: int = 0,
    max_posts: int = 1000,
) -> WorkflowPlan:
    target = target.strip()
    if not target.startswith(("https://", "http://")):
        raise ValueError("For a new YouTube source, paste its channel or video URL.")
    if max_videos < 0 or max_comments < 0 or max_posts < 1:
        raise ValueError(
            "YouTube limits must be zero or greater; Community posts must be at least 1."
        )
    stage_by_action = {
        "Discover channel inventory": "inventory",
        "Acquire / resume transcripts": "transcripts",
        "Acquire / resume comments": "comments",
        "Acquire / resume Community posts": "posts",
        "Index archived comments": "index",
    }
    if action in stage_by_action or action == "All research layers":
        slug = safe_name(target) or "youtube-channel"
        command = [sys.executable, "-m", "warrigal.cli", "ingest-youtube-channel", target, "--checkpoint", str(config.runtime_root / f"{slug}-youtube-channel.checkpoint.json"), "--posts-checkpoint", str(config.runtime_root / f"{slug}-youtube-posts.checkpoint.json"), "--scan-videos", "0", "--max-videos", str(max_videos), "--max-comments", str(max_comments), "--max-posts", str(max_posts), "--max-post-pages", "100"]
        if action in stage_by_action:
            command.extend(["--stage", stage_by_action[action]])
        return WorkflowPlan("YouTube", target, action, (_step(action, *command),))
    if action in {"Single-video transcript", "Single-video available caption"}:
        return WorkflowPlan("YouTube", target, action, (_step("Acquiring YouTube transcript", sys.executable, "-m", "warrigal.cli", "ingest-youtube", target),))
    if action == "Single-video media + Whisper transcript":
        return WorkflowPlan(
            "YouTube", target, action,
            (_step(
                "Downloading, archiving, and transcribing YouTube media",
                sys.executable, "-m", "warrigal.cli", "ingest-youtube-media", target,
            ),),
        )
    raise ValueError("Choose a YouTube workflow action.")


def _website_plan(target: str, action: str, config: WarrigalConfig) -> WorkflowPlan:
    target = target.strip()
    if not target.startswith(("https://", "http://")):
        target = "https://" + target
    slug = safe_name(target) or "website"
    manifest = config.runtime_root / f"{slug}-website-documents.json"
    selected = config.runtime_root / f"{slug}-website-documents-selected.json"
    checkpoint = config.runtime_root / f"{slug}-website-documents.checkpoint.json"
    hostname = (urlparse(target).hostname or slug).removeprefix("www.").lower()
    publication = config.archive_root / "COLLECTIONS" / "WEBSITES" / safe_name(hostname)
    commands = {
        "Discover links": _step("Discovering links without archiving them", sys.executable, "-m", "warrigal.cli", "discover", target),
        "Inventory documents and preserve website sections": _step("Building a section-aware, reviewable document inventory", sys.executable, "-m", "warrigal.cli", "inventory-website-documents", target, "--output", str(manifest)),
        "Review / select inventoried documents": _step("Opening document selection", sys.executable, "-m", "warrigal.website_document_selector", str(manifest), "--output", str(selected)),
        "Acquire / resume smaller documents (up to 25 MB)": _step("Acquiring known-size documents up to 25 MB (smallest first)", sys.executable, "-m", "warrigal.cli", "acquire-manifest", str(manifest), "--checkpoint", str(checkpoint), "--max-resources", "10000", "--max-resource-bytes", str(WEBSITE_SMALL_FILE_LIMIT_BYTES), "--retry-failures", "2", "--retry-delay-seconds", "3", "--read-timeout", "180"),
        "Acquire / resume selected smaller documents (up to 25 MB)": _step("Acquiring selected known-size documents up to 25 MB (smallest first)", sys.executable, "-m", "warrigal.cli", "acquire-manifest", str(selected), "--checkpoint", str(checkpoint), "--max-resources", "10000", "--max-resource-bytes", str(WEBSITE_SMALL_FILE_LIMIT_BYTES), "--retry-failures", "2", "--retry-delay-seconds", "3", "--read-timeout", "180"),
        "Verify all inventoried documents": _step("Verifying complete inventory coverage", sys.executable, "-m", "warrigal.cli", "verify-website-manifest", str(manifest), "--checkpoint", str(checkpoint)),
        "Verify selected documents": _step("Verifying selected document coverage", sys.executable, "-m", "warrigal.cli", "verify-website-manifest", str(selected), "--checkpoint", str(checkpoint)),
        "Publish selected documents": _step("Publishing selected documents as readable files", sys.executable, "-m", "warrigal.publish_manifest_collection", str(selected), "--checkpoint", str(checkpoint), "--output-root", str(publication)),
        "Publish all acquired documents": _step("Publishing all acquired documents as readable files", sys.executable, "-m", "warrigal.publish_manifest_collection", str(manifest), "--checkpoint", str(checkpoint), "--output-root", str(publication)),
        "Acquire this URL only": _step("Acquiring one website resource", sys.executable, "-m", "warrigal.cli", "acquire", target),
        "Crawl up to 10 same-site pages": _step("Crawling up to 10 same-site pages", sys.executable, "-m", "warrigal.cli", "crawl", target),
        "Crawl website": _step("Crawling up to 10 same-site pages", sys.executable, "-m", "warrigal.cli", "crawl", target),
    }
    commands["Inventory direct PDF / ZIP documents"] = commands["Inventory documents and preserve website sections"]
    if action not in commands:
        raise ValueError("Choose a website action.")
    return WorkflowPlan("Website", target, action, (commands[action],))


def build_workflow_plan(
    source_type: str,
    target: str,
    action: str,
    *,
    delay: float = 3.0,
    config: WarrigalConfig = CONFIG,
    youtube_max_videos: int = 0,
    youtube_max_comments: int = 0,
    youtube_max_posts: int = 1000,
) -> WorkflowPlan:
    """Build a deterministic plan without starting processes or touching data."""
    if source_type == "Instagram":
        return _instagram_plan(target, action, delay, config)
    if source_type == "YouTube":
        return _youtube_plan(
            target,
            action,
            config,
            max_videos=youtube_max_videos,
            max_comments=youtube_max_comments,
            max_posts=youtube_max_posts,
        )
    if source_type == "Website":
        return _website_plan(target, action, config)
    raise ValueError(f"Unsupported source type: {source_type}")
