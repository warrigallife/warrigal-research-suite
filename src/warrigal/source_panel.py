"""Native source-acquisition panel for Warrigal Research Suite.

Install this file as ``src/warrigal/source_panel.py`` in the Warrigal repo.
It intentionally orchestrates the existing command modules rather than
duplicating acquisition logic.
"""

from __future__ import annotations

import queue
import subprocess
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from warrigal.config import CONFIG
from warrigal.workflows import (
    YOUTUBE_ACTION_HELP,
    actions_for,
    build_workflow_plan,
    safe_name,
)


ARCHIVE_ROOT = CONFIG.archive_root
RUNTIME_ROOT = CONFIG.runtime_root
PUBLICATION_ROOT = ARCHIVE_ROOT / "COLLECTIONS" / "INSTAGRAM"
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
    return build_workflow_plan(
        "Instagram", target, action, delay=delay
    ).panel_commands()


def build_youtube_commands(
    target: str,
    action: str,
    *,
    max_videos: int = 0,
    max_comments: int = 0,
    max_posts: int = 1000,
) -> list[tuple[str, list[str]]]:
    return build_workflow_plan(
        "YouTube",
        target,
        action,
        youtube_max_videos=max_videos,
        youtube_max_comments=max_comments,
        youtube_max_posts=max_posts,
    ).panel_commands()


def build_website_commands(target: str, action: str) -> list[tuple[str, list[str]]]:
    return build_workflow_plan("Website", target, action).panel_commands()


def build_local_document_commands(target: str, action: str) -> list[tuple[str, list[str]]]:
    return build_workflow_plan("Local Documents", target, action).panel_commands()


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
        self.youtube_max_videos = tk.StringVar(value="0")
        self.youtube_max_comments = tk.StringVar(value="0")
        self.youtube_max_posts = tk.StringVar(value="1000")
        self.action_help = tk.StringVar()
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
            values=("Instagram", "YouTube", "Website", "Local Documents"),
            state="readonly",
            width=24,
        )
        source_box.grid(row=0, column=1, sticky="ew", pady=6)
        source_box.bind("<<ComboboxSelected>>", lambda _event: self._source_changed())

        ttk.Label(form, text="Name or URL").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self.target_entry = ttk.Entry(form, textvariable=self.target)
        self.target_entry.grid(row=1, column=1, sticky="ew", pady=6)

        self.browse_frame = ttk.Frame(form)
        self.browse_frame.grid(row=1, column=2, sticky="w", padx=(8, 0), pady=6)
        ttk.Button(
            self.browse_frame, text="Choose file…", command=self._choose_file
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            self.browse_frame, text="Choose folder…", command=self._choose_folder
        ).pack(side="left")

        ttk.Label(form, text="Action").grid(row=2, column=0, sticky="w", padx=(0, 12), pady=6)
        self.action_box = ttk.Combobox(form, textvariable=self.action, state="readonly")
        self.action_box.grid(row=2, column=1, sticky="ew", pady=6)
        self.action_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._action_changed()
        )

        self.action_help_label = ttk.Label(
            form,
            textvariable=self.action_help,
            wraplength=700,
            foreground="#666666",
        )
        self.action_help_label.grid(row=3, column=1, sticky="w", pady=(0, 6))

        ttk.Label(form, text="Delay (seconds)").grid(row=4, column=0, sticky="w", padx=(0, 12), pady=6)
        self.delay_entry = ttk.Entry(form, textvariable=self.delay, width=12)
        self.delay_entry.grid(row=4, column=1, sticky="w", pady=6)

        self.youtube_limits = ttk.Frame(form)
        self.youtube_limits.grid(row=5, column=1, sticky="w", pady=6)
        for column, (label, variable) in enumerate((
            ("Videos this run (0 = all)", self.youtube_max_videos),
            ("Comments per video (0 = all)", self.youtube_max_comments),
            ("Community posts (maximum)", self.youtube_max_posts),
        )):
            group = ttk.Frame(self.youtube_limits)
            group.grid(row=0, column=column, sticky="w", padx=(0, 18))
            ttk.Label(group, text=label).pack(anchor="w")
            ttk.Entry(group, textvariable=variable, width=10).pack(anchor="w")

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
        actions = actions_for(source)
        self.delay_entry.configure(
            state="normal" if source == "Instagram" else "disabled"
        )
        self.action_box.configure(values=actions)
        self.action.set(actions[0])
        if source == "YouTube":
            self.youtube_limits.grid()
        else:
            self.youtube_limits.grid_remove()
        if source == "Local Documents":
            self.browse_frame.grid()
        else:
            self.browse_frame.grid_remove()
        self._action_changed()

    def _action_changed(self) -> None:
        if self.source_type.get() == "YouTube":
            self.action_help.set(YOUTUBE_ACTION_HELP.get(self.action.get(), ""))
        else:
            self.action_help.set("")

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.target.set(path)

    def _choose_folder(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.target.set(path)

    def _youtube_limit(self, value: str, label: str, *, minimum: int = 0) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{label} must be a whole number.") from exc
        if parsed < minimum:
            raise ValueError(f"{label} must be {minimum} or greater.")
        return parsed

    def _commands(self) -> list[tuple[str, list[str]]]:
        source = self.source_type.get()
        if source == "Instagram":
            try:
                delay = float(self.delay.get())
            except ValueError as exc:
                raise ValueError("Delay must be a number.") from exc
            return build_instagram_commands(self.target.get(), self.action.get(), delay=delay)
        if source == "YouTube":
            return build_youtube_commands(
                self.target.get(),
                self.action.get(),
                max_videos=self._youtube_limit(
                    self.youtube_max_videos.get(), "Videos this run"
                ),
                max_comments=self._youtube_limit(
                    self.youtube_max_comments.get(), "Comments per video"
                ),
                max_posts=self._youtube_limit(
                    self.youtube_max_posts.get(),
                    "Community posts",
                    minimum=1,
                ),
            )
        if source == "Local Documents":
            return build_local_document_commands(self.target.get(), self.action.get())
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
