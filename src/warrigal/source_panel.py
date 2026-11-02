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

from warrigal import online_search
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

# Bounded initial page size and preview length for the Archive Search
# compact results view. These are presentation-only constants; they do not
# affect how many results the backend computes or ranks.
ARCHIVE_SEARCH_PAGE_SIZE = 20
ARCHIVE_SEARCH_PREVIEW_CHARS = 220

# Online Search has a single action (it only calls the Brave Search API
# and displays results - there is no multi-step workflow to choose
# between). Defined here rather than in `warrigal.workflows` because
# Online Search is deliberately kept out of that module's
# `actions_for`/`build_workflow_plan` machinery - see
# `warrigal.online_search` module docstring for why.
ONLINE_SEARCH_ACTIONS = ("Search",)

# Maps the exact field labels already printed by `warrigal.cli search`
# (see `run_search` in src/warrigal/cli.py) to compact dict keys. This lets
# the panel render the existing structured SearchResult/Passage data
# instead of dumping the CLI's raw report text, without changing or
# duplicating anything the backend computes.
_ARCHIVE_RESULT_FIELD_KEYS = {
    "SCORE": "score",
    "COVERAGE": "coverage",
    "MATCHED": "matched",
    "EXACT": "exact",
    "FAMILY": "family",
    "TERM FREQUENCY": "term_frequency",
    "TERM SPAN": "term_span",
    "TITLE COVERAGE": "title_coverage",
    "TITLE MATCHED": "title_matched",
    "TITLE EXACT": "title_exact",
    "TITLE FAMILY": "title_family",
    "TITLE": "title",
    "SOURCE": "source",
    "EVIDENCE GROUP": "evidence_group",
    "OBJECT": "object_id",
    "ACQUISITION": "acquisition_id",
    "METHOD": "method",
    "EVIDENCE": "text",
}


def parse_archive_search_results(output: str) -> list[dict[str, str]]:
    """Parse the existing ``warrigal.cli search`` plain-text report into
    one dict per result, keyed by the fields it already prints.

    This performs no searching, ranking, or matching of its own - it only
    extracts the structured fields that ``run_search`` (src/warrigal/cli.py)
    already emits for each ``SearchResult``/``Passage``, so the GUI can
    render a compact view instead of inserting the raw report text as-is.
    Unrecognized lines (including the ``=== WARRIGAL SEARCH ===`` header,
    ``QUERY:``, and ``RESULTS:``) are ignored.
    """

    results: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if current:
                results.append(current)
                current = {}
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        field = _ARCHIVE_RESULT_FIELD_KEYS.get(key.strip())
        if field is None:
            continue
        current[field] = value.strip()

    if current:
        results.append(current)

    return results


def _truncate_preview(text: str, limit: int = ARCHIVE_SEARCH_PREVIEW_CHARS) -> str:
    """Collapse whitespace and bound preview length; never dump the full passage."""

    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "..."


def format_archive_search_compact(
    results: list[dict[str, str]],
    start: int,
    count: int,
) -> str:
    """Render a compact title / preview / source view for one page of results.

    Deliberately excludes ranking and diagnostic fields (score, coverage,
    matched terms, term frequency, etc.) - see
    ``format_archive_search_diagnostics`` for those, kept in a separate view.
    """

    lines: list[str] = []
    for offset, result in enumerate(
        results[start : start + count], start=start + 1
    ):
        title = result.get("title") or "(untitled)"
        source = result.get("source") or "(no source recorded)"
        preview = _truncate_preview(result.get("text", ""))
        lines.append(f"{offset}. {title}")
        lines.append(f"    {preview}")
        lines.append(f"    Source: {source}")
        lines.append("")
    return "\n".join(lines)


def format_archive_search_diagnostics(
    results: list[dict[str, str]],
    start: int,
    count: int,
) -> str:
    """Render ranking/diagnostic fields for one page of results.

    Kept entirely separate from ``format_archive_search_compact`` so
    score/coverage/matched-term information never appears mixed into the
    compact title/preview/source list.
    """

    lines: list[str] = []
    for offset, result in enumerate(
        results[start : start + count], start=start + 1
    ):
        lines.append(
            f"[{offset}] score={result.get('score', '')} "
            f"coverage={result.get('coverage', '')} "
            f"matched={result.get('matched', '')} "
            f"exact={result.get('exact', '')} "
            f"family={result.get('family', '')} "
            f"term_span={result.get('term_span', '')} "
            f"title_coverage={result.get('title_coverage', '')} "
            f"object={result.get('object_id', '')} "
            f"acquisition={result.get('acquisition_id', '')} "
            f"method={result.get('method', '')}"
        )
    return "\n".join(lines)


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


def build_archive_search_commands(target: str, action: str) -> list[tuple[str, list[str]]]:
    return build_workflow_plan("Archive Search", target, action).panel_commands()


def select_online_search_result(
    results: list[online_search.OnlineSearchResult],
    index: int,
) -> online_search.OnlineSearchResult:
    """Validate and return the chosen 1-based Online Search result.

    Pure validation only - raises ``ValueError`` with a user-facing message
    on an out-of-range index, the same pattern already used by
    `SourcePanel._youtube_limit`. Does not perform any acquisition.
    """
    if not (1 <= index <= len(results)):
        if not results:
            raise ValueError("No results to acquire yet - run a search first.")
        raise ValueError(
            f"Choose a result number between 1 and {len(results)}."
        )
    return results[index - 1]


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

        # Archive Search compact-results state. `_archive_search_mode` is
        # fixed at the start of a run so in-flight behavior for other
        # source types is never affected by a later combobox change.
        self._archive_search_mode = False
        self._archive_results: list[dict[str, str]] = []
        self._archive_shown = 0
        self.diagnostics_visible = tk.BooleanVar(value=False)

        # Online Search compact-results state - entirely separate from the
        # Archive Search state above, per their own variables, widgets, and
        # formatting functions, so Archive Search's behavior is unaffected.
        self._online_results: list[online_search.OnlineSearchResult] = []
        self._online_shown = 0
        # Defaults to the configured provider (env var / local TOML /
        # built-in "searxng" default - see `online_search.resolve_online_search_provider`);
        # the combobox below lets the user override it per run without
        # touching config files.
        self.online_provider = tk.StringVar(
            value=online_search.resolve_online_search_provider()
        )

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
            values=(
                "Instagram",
                "YouTube",
                "Website",
                "Local Documents",
                "Archive Search",
                "Online Search",
            ),
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

        # Archive Search compact-results controls. Packed before `self.log`
        # (which expands to fill remaining space) so both stay visible;
        # shown only while "Archive Search" is the selected source.
        self.archive_controls = ttk.Frame(outer)
        self.show_more_button = ttk.Button(
            self.archive_controls,
            text="Show more results",
            command=self._show_more_archive_results,
            state="disabled",
        )
        self.show_more_button.pack(side="left")
        ttk.Button(
            self.archive_controls,
            text="Show diagnostics",
            command=self._toggle_archive_diagnostics,
        ).pack(side="left", padx=(8, 0))
        self.archive_results_summary = ttk.Label(self.archive_controls, text="")
        self.archive_results_summary.pack(side="left", padx=(12, 0))

        self.diagnostics_frame = ttk.LabelFrame(
            self.archive_controls,
            text="Diagnostics (score, coverage, matched terms) - separate from the results above",
        )
        self.diagnostics_log = tk.Text(
            self.diagnostics_frame, wrap="word", height=8, font=("Menlo", 10)
        )
        self.diagnostics_log.pack(fill="both", expand=True)
        self.diagnostics_log.configure(state="disabled")

        self.archive_controls.pack(fill="x", pady=(0, 8))

        # Online Search compact-results controls - a separate frame, button,
        # and summary label from Archive Search's above, shown only while
        # "Online Search" is the selected source. Results still render into
        # the shared `self.log` text area below, the same as every other
        # source type.
        self.online_controls = ttk.Frame(outer)
        self.online_show_more_button = ttk.Button(
            self.online_controls,
            text="Show more results",
            command=self._show_more_online_results,
            state="disabled",
        )
        self.online_show_more_button.pack(side="left")
        self.online_results_summary = ttk.Label(self.online_controls, text="")
        self.online_results_summary.pack(side="left", padx=(12, 0))
        # Bridges a selected Online Search result into the existing,
        # already-indexed Website "Acquire this URL only" action (see
        # `_acquire_selected_online_result`) - no new acquisition logic,
        # just re-pointing the panel at the one that already exists.
        ttk.Label(self.online_controls, text="Acquire result #:").pack(
            side="left", padx=(20, 4)
        )
        self.online_acquire_index = tk.StringVar(value="1")
        self.online_acquire_entry = ttk.Entry(
            self.online_controls, textvariable=self.online_acquire_index, width=4
        )
        self.online_acquire_entry.pack(side="left")
        self.online_acquire_button = ttk.Button(
            self.online_controls,
            text="Acquire",
            command=self._acquire_selected_online_result,
            state="disabled",
        )
        self.online_acquire_button.pack(side="left", padx=(6, 0))
        self.online_controls.pack(fill="x", pady=(0, 8))

        # Online Search provider selector - lets the user pick "brave" or
        # "tavily" (each requires its own configured API key) instead of
        # the account-free "searxng" default, without touching config
        # files. Shown only while "Online Search" is the selected source
        # (see `_source_changed`), same visibility pattern as
        # `youtube_limits` and `browse_frame` above.
        self.online_provider_row = ttk.Frame(form)
        ttk.Label(self.online_provider_row, text="Provider:").pack(side="left", padx=(0, 8))
        self.online_provider_box = ttk.Combobox(
            self.online_provider_row,
            textvariable=self.online_provider,
            values=online_search.ONLINE_SEARCH_PROVIDERS,
            state="readonly",
            width=10,
        )
        self.online_provider_box.pack(side="left")
        ttk.Label(
            self.online_provider_row,
            text=(
                "searxng = no account needed (default); "
                "brave/tavily = each requires its own configured API key"
            ),
            foreground="#666666",
        ).pack(side="left", padx=(10, 0))
        self.online_provider_row.grid(row=6, column=1, sticky="w", pady=6)

        self.log = tk.Text(outer, wrap="word", height=20, font=("Menlo", 11))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

    def _source_changed(self) -> None:
        source = self.source_type.get()
        # Online Search has a single, fixed action and is deliberately kept
        # out of `warrigal.workflows.actions_for` - see
        # `ONLINE_SEARCH_ACTIONS` above.
        actions = ONLINE_SEARCH_ACTIONS if source == "Online Search" else actions_for(source)
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
        if source == "Archive Search":
            self.archive_controls.pack(fill="x", pady=(0, 8), before=self.log)
        else:
            self.archive_controls.pack_forget()
        if source == "Online Search":
            self.online_controls.pack(fill="x", pady=(0, 8), before=self.log)
            self.online_provider_row.grid()
        else:
            self.online_controls.pack_forget()
            self.online_provider_row.grid_remove()
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
        if source == "Archive Search":
            return build_archive_search_commands(self.target.get(), self.action.get())
        return build_website_commands(self.target.get(), self.action.get())

    def start(self) -> None:
        if self.process is not None:
            return
        if self.source_type.get() == "Online Search":
            self._start_online_search()
            return
        try:
            commands = self._commands()
        except ValueError as exc:
            messagebox.showerror("Cannot start", str(exc))
            return

        self._archive_search_mode = self.source_type.get() == "Archive Search"
        self._archive_results = []
        self._archive_shown = 0
        self.show_more_button.configure(state="disabled")
        self.archive_results_summary.configure(text="")
        self.diagnostics_visible.set(False)
        self.diagnostics_frame.pack_forget()
        self.diagnostics_log.configure(state="normal")
        self.diagnostics_log.delete("1.0", "end")
        self.diagnostics_log.configure(state="disabled")

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
                if self._archive_search_mode:
                    # Buffer the complete report instead of streaming it
                    # line-by-line, so it can be parsed into a compact
                    # display once the (single, one-shot) search command
                    # finishes. Other source types are unaffected - they
                    # keep streaming raw lines exactly as before.
                    output = self.process.stdout.read()
                    exit_code = self.process.wait()
                    self.events.put(("archive_results", output))
                else:
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

    def _start_online_search(self) -> None:
        """Run Online Search directly (a single Brave Search API call),
        bypassing the subprocess/command-plan path entirely - there is no
        acquisition command to run and nothing for `_commands()` to build.
        """

        query = self.target.get().strip()
        if not query:
            messagebox.showerror("Cannot start", "Enter a search query.")
            return

        self._online_results = []
        self._online_shown = 0
        self.online_show_more_button.configure(state="disabled")
        self.online_acquire_button.configure(state="disabled")
        self.online_results_summary.configure(text="")

        self.start_button.configure(state="disabled")
        # A single HTTP call completes quickly and is not meaningfully
        # cancellable mid-flight, unlike the multi-step subprocess
        # workflows below - so "Stop safely" stays disabled for this run.
        self.stop_button.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Searching")
        # The combobox is readonly and pre-populated from
        # `ONLINE_SEARCH_PROVIDERS`, so it always holds a valid value;
        # the fallback below only guards the (untested-by-design) case
        # of an empty StringVar.
        provider = self.online_provider.get().strip().lower() or online_search.DEFAULT_ONLINE_SEARCH_PROVIDER
        self._append("\n=== NEW WARRIGAL SOURCE RUN ===\n")
        self._append(f"\n=== ONLINE SEARCH ({provider}) ===\n")
        threading.Thread(
            target=self._run_online_search, args=(query, provider), daemon=True
        ).start()

    def _run_online_search(self, query: str, provider: str) -> None:
        try:
            results = online_search.search_online(query, provider=provider)
        except (
            online_search.OnlineSearchSetupError,
            online_search.OnlineSearchRequestError,
        ) as exc:
            self.events.put(("online_error", str(exc)))
            self.events.put(("online_done", False))
            return
        except Exception as exc:  # defensive: never let a raw traceback surface
            self.events.put(("online_error", f"Online Search failed: {exc}"))
            self.events.put(("online_done", False))
            return
        self.events.put(("online_results", results))
        self.events.put(("online_done", True))

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
                elif kind == "archive_results":
                    self._archive_results = parse_archive_search_results(str(value))
                    self._archive_shown = 0
                    self.archive_results_summary.configure(
                        text=f"{len(self._archive_results)} result(s) found"
                    )
                    self._show_more_archive_results()
                elif kind == "online_results":
                    self._online_results = list(value)
                    self._online_shown = 0
                    self.online_results_summary.configure(
                        text=f"{len(self._online_results)} result(s) found"
                    )
                    self.online_acquire_button.configure(
                        state="normal" if self._online_results else "disabled"
                    )
                    self._show_more_online_results()
                elif kind == "online_error":
                    # Shown in the shared log - the GUI's own result area -
                    # consistent with how other sources report errors, and
                    # never just a console message.
                    self._append(str(value) + "\n")
                    self.online_results_summary.configure(text="No results")
                elif kind == "online_done":
                    ok = bool(value)
                    self.progress.stop()
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.set("Complete" if ok else "Online Search failed")
                elif kind == "done":
                    code = int(value)
                    self.progress.stop()
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.status.set("Complete" if code == 0 else f"Stopped or failed (exit {code})")
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _show_more_archive_results(self) -> None:
        """Reveal the next bounded page of Archive Search results.

        Keeps score/coverage/matched-term diagnostics out of this compact
        view entirely - see `_toggle_archive_diagnostics`.
        """

        remaining = len(self._archive_results) - self._archive_shown
        if remaining <= 0:
            self.show_more_button.configure(state="disabled")
            return

        page_size = min(ARCHIVE_SEARCH_PAGE_SIZE, remaining)
        compact = format_archive_search_compact(
            self._archive_results, self._archive_shown, page_size
        )
        self._append(compact)
        self._archive_shown += page_size

        if self._archive_shown >= len(self._archive_results):
            self.show_more_button.configure(state="disabled")
        else:
            self.show_more_button.configure(state="normal")

        if self.diagnostics_visible.get():
            self._refresh_archive_diagnostics()

    def _show_more_online_results(self) -> None:
        """Reveal the next bounded page of Online Search results.

        Pages over the already-fetched, in-memory result list only - this
        never triggers another Brave Search API call. Kept entirely
        separate from `_show_more_archive_results` (own state, own
        button, own formatting function), so Archive Search is unaffected.
        """

        remaining = len(self._online_results) - self._online_shown
        if remaining <= 0:
            self.online_show_more_button.configure(state="disabled")
            return

        page_size = min(online_search.ONLINE_SEARCH_PAGE_SIZE, remaining)
        compact = online_search.format_online_search_compact(
            self._online_results, self._online_shown, page_size
        )
        self._append(compact)
        self._online_shown += page_size

        if self._online_shown >= len(self._online_results):
            self.online_show_more_button.configure(state="disabled")
        else:
            self.online_show_more_button.configure(state="normal")

    def _acquire_selected_online_result(self) -> None:
        """Acquire one Online Search result through the existing Website
        "Acquire this URL only" action - the same, already-indexed
        single-URL acquisition path any manually pasted Website URL uses
        (`run_acquire` in `warrigal.cli`). Adds no new acquisition logic;
        it only re-points the panel at the action that already exists,
        exactly as choosing "Website" and pasting the URL by hand would.
        """

        try:
            index = int(self.online_acquire_index.get())
        except ValueError:
            messagebox.showerror(
                "Cannot acquire", "Enter the result number shown above."
            )
            return

        try:
            selected = select_online_search_result(self._online_results, index)
        except ValueError as exc:
            messagebox.showerror("Cannot acquire", str(exc))
            return

        self.source_type.set("Website")
        self._source_changed()
        self.target.set(selected.url)
        self.action.set("Acquire this URL only")
        self.start()

    def _toggle_archive_diagnostics(self) -> None:
        """Show or hide the separate diagnostics panel (never mixed into the
        compact results above)."""

        showing = not self.diagnostics_visible.get()
        self.diagnostics_visible.set(showing)
        if showing:
            self.diagnostics_frame.pack(fill="both", expand=True, pady=(8, 0))
            self._refresh_archive_diagnostics()
        else:
            self.diagnostics_frame.pack_forget()

    def _refresh_archive_diagnostics(self) -> None:
        text = format_archive_search_diagnostics(
            self._archive_results, 0, self._archive_shown
        )
        self.diagnostics_log.configure(state="normal")
        self.diagnostics_log.delete("1.0", "end")
        self.diagnostics_log.insert("end", text)
        self.diagnostics_log.configure(state="disabled")


def main() -> int:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    SourcePanel().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
