"""Discover Instagram post URLs through logged-in Brave."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


APPLESCRIPT = r"""
on run argv
    set profileURL to item 1 of argv
    set maximumScrolls to (item 2 of argv) as integer
    set pauseSeconds to (item 3 of argv) as real
    set stableLimit to (item 4 of argv) as integer
    set snapshots to {}
    set previousHeight to -1
    set stableRounds to 0

    tell application "Brave Browser"
        activate

        set targetWindow to make new window
        set targetTab to active tab of targetWindow
        set URL of targetTab to profileURL
        delay 6

        repeat with roundNumber from 1 to maximumScrolls
            set payload to execute targetTab javascript "
                JSON.stringify(
                    Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => /instagram\\.com\\/(?:[^/]+\\/)?(?:p|reel|tv)\\/[A-Za-z0-9_-]+/.test(h))
                )
            "
            set end of snapshots to payload

            set currentHeight to execute targetTab javascript "
                Math.max(
                    document.body.scrollHeight,
                    document.documentElement.scrollHeight
                ).toString()
            "

            if currentHeight is previousHeight then
                set stableRounds to stableRounds + 1
            else
                set stableRounds to 0
            end if

            if stableRounds is greater than or equal to stableLimit then
                exit repeat
            end if

            set previousHeight to currentHeight

            execute targetTab javascript "
                window.scrollTo(
                    0,
                    Math.max(
                        document.body.scrollHeight,
                        document.documentElement.scrollHeight
                    )
                );
                'scrolled';
            "

            delay pauseSeconds
        end repeat
    end tell

    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set joinedSnapshots to snapshots as text
    set AppleScript's text item delimiters to oldDelimiters

    return joinedSnapshots
end run
"""


def normalize_profile_url(value: str) -> tuple[str, str]:
    """Return a normalized profile URL and username."""

    raw = value.strip()

    if "://" not in raw:
        raw = "https://www.instagram.com/" + raw.lstrip("@/")

    parsed = urlparse(raw)
    host = parsed.netloc.lower().split(":")[0]

    if host not in {"instagram.com", "www.instagram.com"}:
        raise ValueError("Expected an instagram.com profile URL.")

    parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    if len(parts) != 1:
        raise ValueError(
            "Expected one Instagram profile username, not a post URL."
        )

    username = parts[0].lstrip("@")

    if not username:
        raise ValueError("Instagram username is empty.")

    return (
        f"https://www.instagram.com/{username}/",
        username,
    )


def normalize_post_url(
    value: str,
    *,
    profile_username: str,
) -> str | None:
    """Normalize a discovered Instagram post URL."""

    parsed = urlparse(value.strip())
    host = parsed.netloc.lower().split(":")[0]

    if host not in {"instagram.com", "www.instagram.com"}:
        return None

    parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    marker_position = None

    for position, part in enumerate(parts):
        if part in {"p", "reel", "tv"}:
            marker_position = position
            break

    if marker_position is None:
        return None

    if marker_position + 1 >= len(parts):
        return None

    marker = parts[marker_position]
    shortcode = parts[marker_position + 1]

    if not shortcode:
        return None

    return (
        "https://www.instagram.com/"
        f"{profile_username}/{marker}/{shortcode}/"
    )


def parse_browser_snapshots(
    output: str,
    *,
    profile_username: str,
) -> list[str]:
    """Merge URL arrays captured across browser scroll rounds."""

    discovered: list[str] = []
    seen: set[str] = set()

    for line in output.splitlines():
        line = line.strip()

        if not line:
            continue

        try:
            values = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(values, list):
            continue

        for value in values:
            if not isinstance(value, str):
                continue

            normalized = normalize_post_url(
                value,
                profile_username=profile_username,
            )

            if normalized and normalized not in seen:
                seen.add(normalized)
                discovered.append(normalized)

    return discovered


def run_browser_discovery(
    profile_url: str,
    *,
    max_scrolls: int,
    delay: float,
    stable_rounds: int,
) -> str:
    """Run logged-in Brave discovery and return snapshot lines."""

    timeout = int(max_scrolls * (delay + 1.0) + 120)

    process = subprocess.run(
        [
            "osascript",
            "-",
            profile_url,
            str(max_scrolls),
            str(delay),
            str(stable_rounds),
        ],
        input=APPLESCRIPT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )

    if process.returncode:
        message = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(
            "Instagram browser discovery failed: " + message
        )

    return process.stdout


def load_existing_inventory(path: Path) -> dict:
    """Load an existing inventory so discovery is safely repeatable."""

    if not path.is_file():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("Existing inventory is not a JSON object.")

    return payload


def save_inventory(path: Path, payload: dict) -> None:
    """Atomically save an Instagram profile inventory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def discover_profile_inventory(
    profile: str,
    *,
    output: Path,
    max_scrolls: int = 500,
    delay: float = 1.5,
    stable_rounds: int = 12,
    runner=run_browser_discovery,
) -> dict:
    """Discover, merge and save post URLs for one profile."""

    if max_scrolls <= 0:
        raise ValueError("max_scrolls must be positive.")

    if delay < 0:
        raise ValueError("delay cannot be negative.")

    if stable_rounds <= 0:
        raise ValueError("stable_rounds must be positive.")

    profile_url, username = normalize_profile_url(profile)
    browser_output = runner(
        profile_url,
        max_scrolls=max_scrolls,
        delay=delay,
        stable_rounds=stable_rounds,
    )
    discovered = parse_browser_snapshots(
        browser_output,
        profile_username=username,
    )

    existing = load_existing_inventory(output)
    existing_urls = existing.get("post_urls", [])

    if not isinstance(existing_urls, list):
        raise ValueError(
            "Existing inventory post_urls is not a list."
        )

    merged: list[str] = []
    seen: set[str] = set()

    for value in [*existing_urls, *discovered]:
        normalized = normalize_post_url(
            value,
            profile_username=username,
        )

        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(normalized)

    if not merged:
        raise RuntimeError(
            "No Instagram posts were discovered. Confirm Brave is "
            "logged in, the profile is visible, and JavaScript from "
            "Apple Events is enabled."
        )

    payload = {
        "version": 1,
        "profile_username": username,
        "profile_url": profile_url,
        "post_urls": merged,
        "post_count": len(merged),
        "discovered_this_run": len(discovered),
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    save_inventory(output, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover Instagram post URLs through logged-in Brave."
        )
    )
    parser.add_argument("profile")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-scrolls", type=int, default=500)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--stable-rounds", type=int, default=12)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = discover_profile_inventory(
        args.profile,
        output=args.output.expanduser(),
        max_scrolls=args.max_scrolls,
        delay=args.delay,
        stable_rounds=args.stable_rounds,
    )

    print("=== INSTAGRAM PROFILE INVENTORY COMPLETE ===")
    print("PROFILE:", result["profile_username"])
    print("URL:", result["profile_url"])
    print("DISCOVERED THIS RUN:", result["discovered_this_run"])
    print("TOTAL UNIQUE POSTS:", result["post_count"])
    print("OUTPUT:", args.output.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
