"""Acquisition-owned Brave transport driven over the Chrome DevTools Protocol
(CDP), as an alternative to the AppleScript/Apple-Events transport in
``youtube_post_comments.py``.

ARCHITECTURE: the AppleScript transport drives Liam's own, already-running,
already-logged-in personal Brave process. Even with ``activate`` removed and
every created window isolated and closed on every exit path, creating a
window in that same process is still Brave's own window-creation code path,
not Warrigal's -- and that has been reproduced to still raise/focus the
window, which the project's non-interference requirement does not tolerate
as "corrected afterward," only as "never happens."

This module instead launches and drives a second, wholly separate Brave
*process* -- a different executable invocation with its own
``--user-data-dir`` (a dedicated, persistent profile that is never the
personal one) and its own ``--remote-debugging-port`` bound only to
``127.0.0.1``. Nothing here ever touches, reads, or copies the personal
profile's cookies, session tokens, or any other credential -- the dedicated
profile starts empty and must be authenticated once, by hand, by Liam
opening it directly (see the one-time setup steps returned alongside this
module). Because the two Brave processes and profiles are fully separate,
nothing this module does can raise, focus, minimize, or otherwise touch
Liam's own personal Brave window -- not "corrected afterward," never
happening in the first place.

The JavaScript payloads themselves (bootstrap/advance/finalize for comment
collection, and the handle-resolution script) are imported unchanged from
``youtube_post_comments`` and executed via CDP's ``Runtime.evaluate``
instead of AppleScript's ``execute ... javascript`` -- the extraction logic,
author verification, stable-ID resolution, parent/reply relationships,
deduplication, provenance, and checkpoints it feeds are untouched and keep
working exactly as before; only the transport underneath them is new.

This module does not launch a browser or acquire any data on import or at
module load -- a session must be explicitly started (``AcquisitionBrowserSession.start()``
or the context-manager form) and explicitly stopped, mirroring the explicit
setup/cleanup the AppleScript transport already does with its own dedicated
window.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable
from urllib.parse import quote

import requests
import websocket

from warrigal.acquisition.youtube_post_comments import (
    _POST_COMMENTS_ADVANCE_JS,
    _POST_COMMENTS_BOOTSTRAP_JS,
    _POST_COMMENTS_FINALIZE_JS,
    _RESOLVE_HANDLE_JS,
    PostCommentExtractor,
    PostFeedRefresher,
    collect_post_comments_via_browser,
    refresh_post_feed_via_browser,
    resolve_channel_id_via_handle,
)

# Never the acquisition profile -- this is Liam's personal Brave profile
# root. Any configured acquisition profile_dir that resolves inside here is
# refused before any process is launched.
PERSONAL_BRAVE_PROFILE_ROOT = Path.home() / "Library" / "Application Support" / "BraveSoftware"

DEFAULT_BRAVE_EXECUTABLE = Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")

# A stable, documented default so repeated runs reuse the same acquisition
# identity instead of inventing a new profile/port each time -- callers may
# still override either explicitly. This directory is never the personal
# profile (enforced by _assert_not_personal_profile regardless of where the
# caller points it) and starts out empty; it becomes authenticated only
# through the one-time, by-hand login documented alongside this module.
DEFAULT_ACQUISITION_PROFILE_DIR = (
    Path.home() / "Library" / "Application Support" / "Warrigal" / "acquisition-brave-profile"
)
DEFAULT_ACQUISITION_DEBUGGING_PORT = 9222

# The address CDP's debugging endpoint is bound to. Always 127.0.0.1 --
# never 0.0.0.0 or any other interface, so the endpoint is never reachable
# from outside this machine.
_DEBUGGING_ADDRESS = "127.0.0.1"


class EndpointOwnershipError(RuntimeError):
    """Raised when the debugging endpoint this session is about to use, or
    just connected to, cannot be trusted to belong to the process this
    session itself launched."""


def _assert_not_personal_profile(profile_dir: Path) -> None:
    """Refuse to use the personal Brave profile directory, or anything
    inside it, as the acquisition profile -- the only guard standing
    between this module and ever reading a personal cookie or credential."""

    resolved = profile_dir.expanduser().resolve()
    personal = PERSONAL_BRAVE_PROFILE_ROOT.expanduser().resolve()
    if resolved == personal or personal in resolved.parents:
        raise ValueError(
            f"Refusing to use {resolved} as the acquisition browser profile: it is "
            f"the personal Brave profile directory, or inside it ({personal}). The "
            "acquisition profile must be a separate, dedicated directory so personal "
            "cookies/credentials are never read, copied, or shared."
        )


@dataclass
class AcquisitionBrowserConfig:
    """Where the acquisition-owned Brave process lives and how to reach it."""

    profile_dir: Path
    debugging_port: int
    executable: Path = DEFAULT_BRAVE_EXECUTABLE
    command_timeout: float = 30.0
    # Headless by default: for routine, automated collection there must be
    # no window at all, not merely an unfocused one. The one-time manual
    # login this profile needs (see the module docstring) requires a
    # visible window, so that step must explicitly pass headless=False.
    headless: bool = True

    def __post_init__(self) -> None:
        self.profile_dir = Path(self.profile_dir)
        self.executable = Path(self.executable)


def default_acquisition_browser_config(
    *,
    profile_dir: Path | None = None,
    debugging_port: int | None = None,
    executable: Path | None = None,
    headless: bool = True,
) -> AcquisitionBrowserConfig:
    """The stable, documented default configuration -- same profile
    directory and port every time unless a caller overrides them."""

    return AcquisitionBrowserConfig(
        profile_dir=profile_dir or DEFAULT_ACQUISITION_PROFILE_DIR,
        debugging_port=debugging_port or DEFAULT_ACQUISITION_DEBUGGING_PORT,
        executable=executable or DEFAULT_BRAVE_EXECUTABLE,
        headless=headless,
    )


@dataclass
class _Tab:
    id: str
    ws: Any
    next_message_id: int = 0


def _extract_post_id_from_live_url(url: str) -> str:
    """Pure-Python equivalent of the AppleScript transport's
    ``extractPostId`` -- strip query/fragment, trailing slash, and take the
    final path segment."""

    cleaned = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return cleaned.rsplit("/", 1)[-1]


def _post_url_matches_expected(url: str, expected_post_id: str) -> bool:
    """Pure-Python equivalent of the AppleScript transport's
    ``urlMatchesExpectedPost``."""

    if not url.startswith("https://www.youtube.com/post/"):
        return False
    return _extract_post_id_from_live_url(url) == expected_post_id


def _parse_listening_pids(lsof_output: str) -> set[int]:
    """Parse ``lsof -t`` output (one bare PID per line) into a PID set."""

    return {int(line.strip()) for line in lsof_output.splitlines() if line.strip().isdigit()}


def _parse_process_children(ps_output: str) -> dict[int, list[int]]:
    """Parse ``ps -axo pid=,ppid=`` output into a parent-PID -> children map."""

    children: dict[int, list[int]] = {}
    for line in ps_output.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
    return children


def _descendants_of(root_pid: int, children: dict[int, list[int]]) -> set[int]:
    """root_pid plus every PID reachable from it through ``children``."""

    descendants = {root_pid}
    frontier = [root_pid]
    while frontier:
        current = frontier.pop()
        for child in children.get(current, ()):
            if child not in descendants:
                descendants.add(child)
                frontier.append(child)
    return descendants


class AcquisitionBrowserSession:
    """Explicit setup/teardown for the acquisition-owned Brave process.

    ``start()`` launches a dedicated Brave process against the configured
    profile and debugging port, and blocks until the debugging endpoint
    actually answers (bounded by ``launch_timeout``) -- never a blind sleep.
    ``stop()`` closes every tab this session opened and terminates the
    process; it is safe to call even if the session was never started, or
    more than once. Use as a context manager for the common case.
    """

    def __init__(self, config: AcquisitionBrowserConfig):
        self.config = config
        self._process: subprocess.Popen | None = None
        self._open_tabs: dict[str, _Tab] = {}

    def __enter__(self) -> "AcquisitionBrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.stop()
        return False

    @property
    def _base_url(self) -> str:
        return f"http://{_DEBUGGING_ADDRESS}:{self.config.debugging_port}"

    def start(self, *, launch_timeout: float = 15.0) -> None:
        if self._process is not None:
            return

        _assert_not_personal_profile(self.config.profile_dir)
        self.config.profile_dir.mkdir(parents=True, exist_ok=True)
        self._refuse_if_endpoint_already_occupied()

        command = [
            str(self.config.executable),
            f"--user-data-dir={self.config.profile_dir}",
            f"--remote-debugging-port={self.config.debugging_port}",
            f"--remote-debugging-address={_DEBUGGING_ADDRESS}",
            # Chromium rejects incoming CDP WebSocket connections whose
            # Origin header isn't explicitly allow-listed (confirmed live:
            # "Handshake status 403 Forbidden ... Rejected an incoming
            # WebSocket connection from the http://127.0.0.1:<port>
            # origin"). Allow-list exactly the one local origin this
            # client itself connects from -- never "*", which would accept
            # a WebSocket handshake claiming to originate from anywhere.
            f"--remote-allow-origins={self._base_url}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ]
        if self.config.headless:
            command.insert(1, "--headless=new")

        self._process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        deadline = time.monotonic() + launch_timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                exit_code = self._process.returncode
                self._process = None
                raise RuntimeError(
                    f"Acquisition Brave exited immediately (code {exit_code}) before "
                    "its debugging endpoint ever answered"
                )
            try:
                response = requests.get(f"{self._base_url}/json/version", timeout=1)
                response.raise_for_status()
                self._verify_endpoint_ownership()
                return
            except EndpointOwnershipError:
                # Something answered, but ownership could not be confirmed
                # (already exited, or the real listener traced back to a
                # PID outside this session's own process tree) --
                # terminate only this session's own spawned process
                # (self.stop() never touches anything this session did not
                # itself launch) before re-raising the original ownership
                # error unchanged.
                self.stop()
                raise
            except Exception as exc:  # noqa: BLE001 - retried until the deadline
                last_error = exc
                time.sleep(0.25)

        self.stop()
        raise RuntimeError(
            f"Acquisition Brave did not expose its debugging endpoint on "
            f"{_DEBUGGING_ADDRESS}:{self.config.debugging_port} within "
            f"{launch_timeout}s: {last_error}"
        )

    def _refuse_if_endpoint_already_occupied(self) -> None:
        """Pre-flight ownership check: if something already answers on our
        configured port before we have launched anything, refuse to
        proceed rather than risk talking to a pre-existing, unrelated
        process once our own is started alongside or instead of it."""

        try:
            requests.get(f"{self._base_url}/json/version", timeout=1)
        except Exception:  # noqa: BLE001 - good: nothing is there yet
            return
        raise EndpointOwnershipError(
            f"Refusing to start: something is already answering at "
            f"{self._base_url}/json/version before this session launched its own "
            "Brave process. Starting would risk talking to a pre-existing, "
            "unrelated endpoint instead of the one this session owns."
        )

    def _verify_endpoint_ownership(self) -> None:
        """Post-answer ownership check: the endpoint must actually be served
        by the process this session itself launched, or a descendant of it.

        Brave's own CDP /json/version response identifies using the
        underlying Chromium product string (observed live: e.g.
        "Chrome/151.0.7922.137"), never the word "Brave" -- so that field
        cannot be used to prove ownership and is not consulted here. A free
        port before launch, and this session's own process still being
        alive, are both necessary but NOT sufficient on their own: neither
        actually confirms that THIS specific process (or one it spawned) is
        the one the debugging port is bound to right now. This checks that
        directly, by tracing the real listening socket back to a PID and
        confirming that PID is this session's own spawned process or a
        descendant of it.
        """

        if self._process is None or self._process.poll() is not None:
            raise EndpointOwnershipError(
                "Acquisition Brave's debugging endpoint answered, but the process "
                "this session launched is no longer running -- refusing to trust "
                "an endpoint that does not belong to this session's own process."
            )

        listening_pids = self._listening_pids()
        if not listening_pids:
            raise EndpointOwnershipError(
                f"Acquisition Brave's debugging endpoint on port "
                f"{self.config.debugging_port} answered, but no process could be "
                "confirmed as actually listening on it -- refusing to trust an "
                "endpoint whose ownership cannot be verified."
            )

        owned_pids = self._descendant_pids(self._process.pid)
        if not listening_pids & owned_pids:
            raise EndpointOwnershipError(
                f"Acquisition Brave's debugging endpoint on port "
                f"{self.config.debugging_port} is being served by process(es) "
                f"{sorted(listening_pids)}, none of which is this session's own "
                f"spawned process ({self._process.pid}) or a descendant of it -- "
                "refusing to trust an endpoint that does not belong to this session."
            )

    def _listening_pids(self) -> set[int]:
        """PIDs actually holding a LISTEN socket on our debugging port."""

        try:
            result = subprocess.run(
                [
                    "lsof",
                    "-nP",
                    f"-iTCP:{self.config.debugging_port}",
                    "-sTCP:LISTEN",
                    "-t",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:  # noqa: BLE001 - treated as "nothing confirmed listening"
            return set()
        return _parse_listening_pids(result.stdout)

    def _descendant_pids(self, root_pid: int) -> set[int]:
        """root_pid plus every PID descended from it, from the live process
        table -- covers a launcher process that execs or forks into the
        actual browser process rather than becoming it."""

        try:
            result = subprocess.run(
                ["ps", "-axo", "pid=,ppid="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:  # noqa: BLE001 - treated as "no descendants confirmed"
            return {root_pid}
        return _descendants_of(root_pid, _parse_process_children(result.stdout))

    def stop(self) -> None:
        for tab in list(self._open_tabs.values()):
            self.close_tab(tab)

        process, self._process = self._process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def open_tab(self, url: str) -> _Tab:
        if self._process is None:
            raise RuntimeError("Acquisition browser session has not been started")

        response = requests.put(
            f"{self._base_url}/json/new?{quote(url, safe='')}", timeout=10
        )
        response.raise_for_status()
        info = response.json()
        tab_id = info["id"]
        try:
            ws = websocket.create_connection(
                info["webSocketDebuggerUrl"], timeout=self.config.command_timeout
            )
        except Exception:
            # The tab was created (the HTTP call above succeeded) but we
            # could not attach to it -- close it now rather than leaving an
            # orphaned, never-tracked tab behind in the acquisition browser.
            self._close_tab_by_id(tab_id)
            raise

        tab = _Tab(id=tab_id, ws=ws)
        self._open_tabs[tab.id] = tab
        return tab

    def _close_tab_by_id(self, tab_id: str) -> None:
        try:
            requests.get(f"{self._base_url}/json/close/{tab_id}", timeout=10)
        except Exception:  # noqa: BLE001 - cleanup must not raise
            pass

    def close_tab(self, tab: _Tab) -> None:
        try:
            tab.ws.close()
        except Exception:  # noqa: BLE001 - cleanup must not raise
            pass
        self._close_tab_by_id(tab.id)
        self._open_tabs.pop(tab.id, None)

    def evaluate(self, tab: _Tab, expression: str) -> Any:
        tab.next_message_id += 1
        message_id = tab.next_message_id
        tab.ws.send(
            json.dumps(
                {
                    "id": message_id,
                    "method": "Runtime.evaluate",
                    "params": {"expression": expression, "returnByValue": True},
                }
            )
        )
        while True:
            message = json.loads(tab.ws.recv())
            if message.get("id") == message_id:
                break

        result = message.get("result", {})
        if result.get("exceptionDetails"):
            raise RuntimeError(f"JavaScript evaluation failed: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def current_url(self, tab: _Tab) -> str:
        return self.evaluate(tab, "location.href")


def _verify_tab_on_target(
    session: AcquisitionBrowserSession, tab: _Tab, expected_post_id: str, stage_label: str
) -> None:
    current = session.current_url(tab)
    if not _post_url_matches_expected(current, expected_post_id):
        raise RuntimeError(
            f"Brave tab navigated away from the target post ({stage_label}): "
            f"expected post {expected_post_id} but the tab is now at {current}"
        )


def run_cdp_post_comment_collection(
    post_url: str,
    max_rounds: int,
    wall_clock_budget_seconds: int,
    *,
    session: AcquisitionBrowserSession,
) -> str:
    """CDP equivalent of ``run_browser_post_comment_collection`` -- same
    signature, same JavaScript, same tab-identity verification at every
    stage, same round/finalize contract. Only the transport differs."""

    expected_post_id = _extract_post_id_from_live_url(post_url)
    tab = session.open_tab(post_url)
    try:
        time.sleep(6)
        _verify_tab_on_target(session, tab, expected_post_id, "before bootstrap")

        bootstrapped = session.evaluate(tab, _POST_COMMENTS_BOOTSTRAP_JS)
        if bootstrapped != "OK":
            raise RuntimeError(bootstrapped)

        session.evaluate(
            tab, f"window.__wrgWallClockBudgetMs = {wall_clock_budget_seconds * 1000};"
        )

        rounds_used = 0
        round_limit_reached = False
        for round_number in range(1, max_rounds + 1):
            rounds_used = round_number
            _verify_tab_on_target(session, tab, expected_post_id, f"round {round_number}")
            advanced = session.evaluate(tab, _POST_COMMENTS_ADVANCE_JS)
            if advanced == "DONE":
                break
            time.sleep(2)
        else:
            round_limit_reached = True

        if round_limit_reached:
            session.evaluate(tab, "window.__wrgRoundLimitReached = true;")

        _verify_tab_on_target(session, tab, expected_post_id, "before extraction")
        session.evaluate(tab, f"window.__wrgRounds = {rounds_used};")
        return session.evaluate(tab, _POST_COMMENTS_FINALIZE_JS)
    finally:
        session.close_tab(tab)


def run_cdp_handle_resolution(handle_url: str, *, session: AcquisitionBrowserSession) -> str:
    """CDP equivalent of ``run_browser_handle_resolution``."""

    tab = session.open_tab(handle_url)
    try:
        time.sleep(5)
        current = session.current_url(tab)
        if not (
            current.startswith("https://www.youtube.com/")
            or current.startswith("https://youtube.com/")
        ):
            raise RuntimeError(
                f"Brave tab navigated away from YouTube during handle resolution: "
                f"now at {current}"
            )
        return session.evaluate(tab, _RESOLVE_HANDLE_JS)
    finally:
        session.close_tab(tab)


def run_cdp_post_feed_discovery(
    channel_url: str,
    max_scrolls: int,
    delay: float,
    stable_rounds: int,
    *,
    session: AcquisitionBrowserSession,
) -> str:
    """CDP equivalent of ``run_browser_post_feed_discovery``. Returns the
    same newline-joined-snapshots-plus-marker text ``parse_browser_post_feed_payload``
    already parses -- unchanged."""

    tab = session.open_tab(channel_url)
    snapshots: list[str] = []
    stabilized = False
    try:
        time.sleep(6)
        current = session.current_url(tab)
        if not (
            current.startswith("https://www.youtube.com/")
            or current.startswith("https://youtube.com/")
        ):
            raise RuntimeError(
                f"Brave tab navigated away from YouTube during Community-post "
                f"discovery: now at {current}"
            )

        previous_height: str | None = None
        stable_count = 0
        for _ in range(max_scrolls):
            payload = session.evaluate(
                tab,
                "JSON.stringify(Array.from(document.querySelectorAll('a[href*=\"/post/\"]'))"
                ".map(a => a.href))",
            )
            snapshots.append(payload)

            current_height = session.evaluate(
                tab,
                "Math.max(document.body.scrollHeight, "
                "document.documentElement.scrollHeight).toString()",
            )

            if previous_height is not None and current_height == previous_height:
                stable_count += 1
            else:
                stable_count = 0

            if stable_count >= stable_rounds:
                stabilized = True
                break

            previous_height = current_height
            session.evaluate(
                tab,
                "window.scrollTo(0, Math.max(document.body.scrollHeight, "
                "document.documentElement.scrollHeight)); 'scrolled';",
            )
            time.sleep(delay)
    finally:
        session.close_tab(tab)

    marker = "__WRG_STABILIZED__" if stabilized else "__WRG_SCROLL_LIMIT_REACHED__"
    return "\n".join(snapshots) + "\n" + marker


# --------------------------------------------------------------------------
# Wiring: bundles a started session with CDP-backed callables that match
# youtube_post_comments.py's existing injection points (runner=,
# resolve_handle=, extractor=, comment_extractor=, post_feed_refresher=)
# exactly. Nothing about those parameters, their types, or their default
# values in youtube_post_comments.py changes -- a caller (the single-post
# and campaign CLI entry points) supplies these bound callables explicitly
# instead of relying on the AppleScript defaults. Existing tests that pass
# their own mocks into those same parameters are unaffected.
# --------------------------------------------------------------------------


@dataclass
class AcquisitionCdpRunners:
    """Everything a single-post or campaign call needs to run over CDP
    instead of AppleScript, bound to one already-started session."""

    session: AcquisitionBrowserSession
    comment_collection_runner: Callable[[str, int, int], str]
    handle_resolution_runner: Callable[[str], str]
    post_feed_discovery_runner: Callable[[str, int, float, int], str]
    handle_resolver: Callable[[str], str | None]
    comment_extractor: PostCommentExtractor
    post_feed_refresher: PostFeedRefresher


@contextmanager
def acquisition_cdp_runners(config: AcquisitionBrowserConfig | None = None):
    """Explicit setup (start the acquisition session) / explicit cleanup
    (stop it, even on error) around one batch of CDP-backed calls --
    exactly the shape the single-post and campaign CLI entry points need:
    one session for the whole call, not one per post."""

    session = AcquisitionBrowserSession(config or default_acquisition_browser_config())
    session.start()
    try:
        comment_collection_runner = partial(run_cdp_post_comment_collection, session=session)
        handle_resolution_runner = partial(run_cdp_handle_resolution, session=session)
        post_feed_discovery_runner = partial(run_cdp_post_feed_discovery, session=session)
        handle_resolver = partial(resolve_channel_id_via_handle, runner=handle_resolution_runner)
        yield AcquisitionCdpRunners(
            session=session,
            comment_collection_runner=comment_collection_runner,
            handle_resolution_runner=handle_resolution_runner,
            post_feed_discovery_runner=post_feed_discovery_runner,
            handle_resolver=handle_resolver,
            comment_extractor=partial(
                collect_post_comments_via_browser,
                runner=comment_collection_runner,
                resolve_handle=handle_resolver,
            ),
            post_feed_refresher=partial(
                refresh_post_feed_via_browser, runner=post_feed_discovery_runner
            ),
        )
    finally:
        session.stop()
