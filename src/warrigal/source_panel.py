"""Native source-acquisition panel for Warrigal Research Suite.

Install this file as ``src/warrigal/source_panel.py`` in the Warrigal repo.
It intentionally orchestrates the existing command modules rather than
duplicating acquisition logic.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import tkinter as tk
from tkinter import messagebox, ttk

from warrigal.config import CONFIG


ARCHIVE_ROOT = CONFIG.archive_root
RUNTIME_ROOT = CONFIG.runtime_root
PUBLICATION_ROOT = ARCHIVE_ROOT / "COLLECTIONS" / "INSTAGRAM"
WEBSITE_SMALL_FILE_LIMIT_BYTES = 25 * 1024 * 1024


def safe_name(value: str) -> str:
    value = value.strip().rstrip("/")
    if "://" in value:
        parsed = urlparse(value)
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            value = parts[0]
        elif parsed.hostname:
            value = parsed.hostname
    value = value.lstrip("@").lower()
    return re.sub(r"[^a-z0-9._-]+", "-", value).strip("-.")


def instagram_paths(target: str) -> tuple[str, Path, Path]:
    profile = safe_name(target)
    if not profile:
        raise ValueError("Enter an Instagram profile name or profile URL.")
    return (
        profile,
        RUNTIME_ROOT / f"{profile}-instagram-inventory.json",
        RUNTIME_ROOT / f"{profile}-instagram.checkpoint.json",
    )


def build_instagram_commands(
    target: str,
    action: str,
    *,
    delay: float = 3.0,
) -> list[tuple[str, list[str]]]:
    profile, inventory, checkpoint = instagram_paths(target)
    python = sys.executable
    commands: list[tuple[str, list[str]]] = []

    if action in {"Complete workflow", "Discover inventory"}:
        commands.append((
            "Discovering Instagram inventory",
            [
                python,
                "-m",
                "warrigal.instagram_profile_inventory",
                profile,
                "--output",
                str(inventory),
                "--delay",
                str(delay),
            ],
        ))

    if action in {"Complete workflow", "Acquire / resume"}:
        commands.append((
            "Acquiring unfinished Instagram posts",
            [
                python,
                "-m",
                "warrigal.instagram_browser_campaign",
                "--inventory",
                str(inventory),
                "--checkpoint",
                str(checkpoint),
                "--max-posts",
                "0",
                "--delay",
                str(delay),
            ],
        ))

    if action in {"Complete workflow", "Verify"}:
        commands.append((
            "Verifying no Instagram posts remain",
            [
                python,
                "-m",
                "warrigal.instagram_browser_campaign",
                "--inventory",
                str(inventory),
                "--checkpoint",
                str(checkpoint),
                "--max-posts",
                "0",
                "--delay",
                str(delay),
            ],
        ))

    if action in {"Complete workflow", "Publish"}:
        commands.append((
            "Publishing the Instagram collection",
            [
                python,
                "-m",
                "warrigal.publish_instagram_collection",
                "--output-root",
                str(PUBLICATION_ROOT),
                "--profile",
                profile,
            ],
        ))

    return commands


def build_youtube_commands(target: str, action: str) -> list[tuple[str, list[str]]]:
    target = target.strip()
    if not target.startswith(("https://", "http://")):
        raise ValueError(
            "For a new YouTube source, paste its channel or video URL. "
            "Saved channel names can be added after the first URL-based run."
        )

    python = sys.executable
    stage_by_action = {
        "Discover channel inventory": "inventory",
        "Acquire / resume transcripts": "transcripts",
        "Acquire / resume comments": "comments",
        "Acquire / resume Community posts": "posts",
        "Index archived comments": "index",
    }
    if action in stage_by_action or action == "All research layers":
        slug = safe_name(target) or "youtube-channel"
        checkpoint = RUNTIME_ROOT / f"{slug}-youtube-channel.checkpoint.json"
        posts_checkpoint = RUNTIME_ROOT / f"{slug}-youtube-posts.checkpoint.json"
        command = [
            python, "-m", "warrigal.cli", "ingest-youtube-channel", target,
            "--checkpoint", str(checkpoint),
            "--posts-checkpoint", str(posts_checkpoint),
            "--scan-videos", "0",
            "--max-videos", "0",
            "--max-comments", "0",
            "--max-posts", "1000",
            "--max-post-pages", "100",
        ]
        if action in stage_by_action:
            command.extend(["--stage", stage_by_action[action]])
        return [(action, command)]

    if action == "Single-video transcript":
        return [("Acquiring YouTube transcript", [python, "-m", "warrigal.cli", "ingest-youtube", target])]

    raise ValueError("Choose a YouTube workflow action.")


def build_website_commands(target: str, action: str) -> list[tuple[str, list[str]]]:
    target = target.strip()
    if not target.startswith(("https://", "http://")):
        target = "https://" + target
    slug = safe_name(target) or "website"
    manifest = RUNTIME_ROOT / f"{slug}-website-documents.json"
    selected_manifest = RUNTIME_ROOT / f"{slug}-website-documents-selected.json"
    checkpoint = RUNTIME_ROOT / f"{slug}-website-documents.checkpoint.json"
    hostname = (urlparse(target).hostname or slug).removeprefix("www.").lower()
    publication_root = ARCHIVE_ROOT / "COLLECTIONS" / "WEBSITES" / safe_name(hostname)
    commands = {
        "Discover links": (
            "Discovering links without archiving them",
            [sys.executable, "-m", "warrigal.cli", "discover", target],
        ),
        "Inventory documents and preserve website sections": (
            "Building a section-aware, reviewable document inventory",
            [
                sys.executable, "-m", "warrigal.cli",
                "inventory-website-documents", target,
                "--output", str(manifest),
            ],
        ),
        "Review / select inventoried documents": (
            "Opening document selection",
            [
                sys.executable, "-m", "warrigal.website_document_selector",
                str(manifest), "--output", str(selected_manifest),
            ],
        ),
        "Acquire / resume smaller documents (up to 25 MB)": (
            "Acquiring known-size documents up to 25 MB (smallest first)",
            [
                sys.executable, "-m", "warrigal.cli", "acquire-manifest",
                str(manifest), "--checkpoint", str(checkpoint),
                "--max-resources", "10000",
                "--max-resource-bytes", str(WEBSITE_SMALL_FILE_LIMIT_BYTES),
                "--retry-failures", "2",
                "--retry-delay-seconds", "3",
                "--read-timeout", "180",
            ],
        ),
        "Acquire / resume selected smaller documents (up to 25 MB)": (
            "Acquiring selected known-size documents up to 25 MB (smallest first)",
            [
                sys.executable, "-m", "warrigal.cli", "acquire-manifest",
                str(selected_manifest), "--checkpoint", str(checkpoint),
                "--max-resources", "10000",
                "--max-resource-bytes", str(WEBSITE_SMALL_FILE_LIMIT_BYTES),
                "--retry-failures", "2",
                "--retry-delay-seconds", "3",
                "--read-timeout", "180",
            ],
        ),
        "Verify all inventoried documents": (
            "Verifying complete inventory coverage",
            [
                sys.executable, "-m", "warrigal.cli",
                "verify-website-manifest", str(manifest),
                "--checkpoint", str(checkpoint),
            ],
        ),
        "Verify selected documents": (
            "Verifying selected document coverage",
            [
                sys.executable, "-m", "warrigal.cli",
                "verify-website-manifest", str(selected_manifest),
                "--checkpoint", str(checkpoint),
            ],
        ),
        "Publish selected documents": (
            "Publishing selected documents as readable files",
            [
                sys.executable, "-m", "warrigal.publish_manifest_collection",
                str(selected_manifest), "--checkpoint", str(checkpoint),
                "--output-root", str(publication_root),
            ],
        ),
        "Publish all acquired documents": (
            "Publishing all acquired documents as readable files",
            [
                sys.executable, "-m", "warrigal.publish_manifest_collection",
                str(manifest), "--checkpoint", str(checkpoint),
                "--output-root", str(publication_root),
            ],
        ),
        "Acquire this URL only": (
            "Acquiring one website resource",
            [sys.executable, "-m", "warrigal.cli", "acquire", target],
        ),
        "Crawl up to 10 same-site pages": (
            "Crawling up to 10 same-site pages",
            [sys.executable, "-m", "warrigal.cli", "crawl", target],
        ),
        # Retain the earlier action name for callers and saved tests while the
        # panel presents the clearer bounded label above.
        "Crawl website": (
            "Crawling up to 10 same-site pages",
            [sys.executable, "-m", "warrigal.cli", "crawl", target],
        ),
    }
    # Keep the previous label working for tests and older saved instructions.
    commands["Inventory direct PDF / ZIP documents"] = commands[
        "Inventory documents and preserve website sections"
    ]
    if action not in commands:
        raise ValueError("Choose a website action.")
    return [commands[action]]


class SourcePanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Warrigal Source Acquisition")
        self.geometry("900x650")
        self.minsize(760, 540)

        self.source_type = tk.StringVar(value="Instagram")
        self.target = tk.StringVar()
        self.action = tk.StringVar(value="Complete workflow")
        self.delay = tk.StringVar(value="3")
        self.status = tk.StringVar(value="Ready")
        self.process: subprocess.Popen[str] | None = None
        self.events: queue.Queue[tuple[str, str | int]] = queue.Queue()

        self._build_widgets()
        self._source_changed()
        self.after(100, self._drain_events)

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Warrigal Source Acquisition", font=("Helvetica", 22, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Enter one source, choose what Warrigal should do, then start.",
        ).pack(anchor="w", pady=(2, 18))

        form = ttk.Frame(outer)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Source type").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        source_box = ttk.Combobox(
            form,
            textvariable=self.source_type,
            values=("Instagram", "YouTube", "Website"),
            state="readonly",
            width=24,
        )
        source_box.grid(row=0, column=1, sticky="ew", pady=6)
        source_box.bind("<<ComboboxSelected>>", lambda _event: self._source_changed())

        ttk.Label(form, text="Name or URL").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self.target_entry = ttk.Entry(form, textvariable=self.target)
        self.target_entry.grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="Action").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=6)
        self.action_box = ttk.Combobox(form, textvariable=self.action, state="readonly")
        self.action_box.grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="Delay (seconds)").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=6)
        self.delay_entry = ttk.Entry(form, textvariable=self.delay, width=12)
        self.delay_entry.grid(row=3, column=1, sticky="w", pady=6)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(16, 10))
        self.start_button = ttk.Button(buttons, text="Start", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="Stop safely", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(buttons, text="Open Instagram collections", command=self.open_collections).pack(side="right")

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))
        ttk.Label(outer, textvariable=self.status).pack(anchor="w", pady=(0, 8))

        self.log = tk.Text(outer, wrap="word", height=20, font=("Menlo", 11))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

    def _source_changed(self) -> None:
        source = self.source_type.get()
        if source == "Instagram":
            actions = ("Complete workflow", "Discover inventory", "Acquire / resume", "Verify", "Publish")
            self.target_entry.configure()
            self.delay_entry.configure(state="normal")
        elif source == "YouTube":
            actions = (
                "Discover channel inventory",
                "Acquire / resume transcripts",
                "Acquire / resume comments",
                "Acquire / resume Community posts",
                "Index archived comments",
                "All research layers",
                "Single-video transcript",
            )
            self.delay_entry.configure(state="disabled")
        else:
            actions = (
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
            self.delay_entry.configure(state="disabled")
        self.action_box.configure(values=actions)
        self.action.set(actions[0])

    def _commands(self) -> list[tuple[str, list[str]]]:
        source = self.source_type.get()
        if source == "Instagram":
            try:
                delay = float(self.delay.get())
            except ValueError as exc:
                raise ValueError("Delay must be a number.") from exc
            return build_instagram_commands(self.target.get(), self.action.get(), delay=delay)
        if source == "YouTube":
            return build_youtube_commands(self.target.get(), self.action.get())
        return build_website_commands(self.target.get(), self.action.get())

    def start(self) -> None:
        if self.process is not None:
            return
        try:
            commands = self._commands()
        except ValueError as exc:
            messagebox.showerror("Cannot start", str(exc))
            return

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.progress.start(12)
        self.status.set("Starting")
        self._append("\n=== NEW WARRIGAL SOURCE RUN ===\n")
        threading.Thread(target=self._run_commands, args=(commands,), daemon=True).start()

    def _run_commands(self, commands: list[tuple[str, list[str]]]) -> None:
        exit_code = 0
        for label, command in commands:
            self.events.put(("line", f"\n=== {label.upper()} ===\n"))
            self.events.put(("status", label))
            try:
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert self.process.stdout is not None
                for line in self.process.stdout:
                    self.events.put(("line", line))
                exit_code = self.process.wait()
            except Exception as exc:
                self.events.put(("line", f"ERROR: {exc}\n"))
                exit_code = 1
            finally:
                self.process = None

            if exit_code != 0:
                break

        self.events.put(("done", exit_code))

    def stop(self) -> None:
        if self.process is not None:
            self.status.set("Stopping after the current operation")
            self.process.send_signal(2)

    def open_collections(self) -> None:
        PUBLICATION_ROOT.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["open", str(PUBLICATION_ROOT)])

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "line":
                    self._append(str(value))
                elif kind == "status":
                    self.status.set(str(value))
                elif kind == "done":
                    code = int(value)
                    self.progress.stop()
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.set("Complete" if code == 0 else f"Stopped or failed (exit {code})")
        except queue.Empty:
            pass
        self.after(100, self._drain_events)


def main() -> int:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    SourcePanel().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
