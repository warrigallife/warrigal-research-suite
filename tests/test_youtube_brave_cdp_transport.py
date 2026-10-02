"""Focused tests for the acquisition-owned Brave/CDP transport.

None of these tests launch a real browser or touch the network -- every
subprocess, HTTP, and WebSocket call is mocked. They exercise: the
personal-profile guard, the localhost-only launch command, explicit
setup/cleanup (including the launch-timeout and terminate/kill paths), the
CDP request/response framing, and the three high-level runner functions'
control flow (round-limit, early DONE, tab-always-closed, and the
feed-discovery stabilization contract) against a hand-written fake session
double -- not a real browser.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from warrigal.acquisition.youtube_brave_cdp_transport import (
    DEFAULT_ACQUISITION_DEBUGGING_PORT,
    DEFAULT_ACQUISITION_PROFILE_DIR,
    DEFAULT_BRAVE_EXECUTABLE,
    PERSONAL_BRAVE_PROFILE_ROOT,
    AcquisitionBrowserConfig,
    AcquisitionBrowserSession,
    AcquisitionCdpRunners,
    EndpointOwnershipError,
    _assert_not_personal_profile,
    _descendants_of,
    _extract_post_id_from_live_url,
    _parse_listening_pids,
    _parse_process_children,
    _post_url_matches_expected,
    acquisition_cdp_runners,
    default_acquisition_browser_config,
    run_cdp_handle_resolution,
    run_cdp_post_comment_collection,
    run_cdp_post_feed_discovery,
)
from warrigal.acquisition.youtube_post_comments import (
    collect_post_comments_via_browser,
    refresh_post_feed_via_browser,
    resolve_channel_id_via_handle,
)
from warrigal.acquisition.youtube_post_comments import (
    _POST_COMMENTS_ADVANCE_JS,
    _POST_COMMENTS_BOOTSTRAP_JS,
    _POST_COMMENTS_FINALIZE_JS,
    _RESOLVE_HANDLE_JS,
)


class PersonalProfileGuardTests(unittest.TestCase):
    def test_rejects_the_personal_profile_root_itself(self):
        with self.assertRaises(ValueError):
            _assert_not_personal_profile(PERSONAL_BRAVE_PROFILE_ROOT)

    def test_rejects_a_path_nested_inside_the_personal_profile(self):
        with self.assertRaises(ValueError):
            _assert_not_personal_profile(PERSONAL_BRAVE_PROFILE_ROOT / "Default")

    def test_accepts_a_wholly_separate_directory(self):
        _assert_not_personal_profile(Path("/tmp/warrigal-acquisition-brave-profile"))  # no raise


class PostIdMatchingTests(unittest.TestCase):
    """Pure-Python equivalent of the AppleScript tab-targeting tests --
    same scenarios, no osascript required."""

    def test_extracts_post_id_with_trailing_slash(self):
        self.assertEqual(
            _extract_post_id_from_live_url("https://www.youtube.com/post/Ugkx3yv-ABC/"),
            "Ugkx3yv-ABC",
        )

    def test_extracts_post_id_with_query_string(self):
        self.assertEqual(
            _extract_post_id_from_live_url("https://www.youtube.com/post/Ugkx-W8-XYZ?foo=bar"),
            "Ugkx-W8-XYZ",
        )

    def test_extracts_post_id_with_fragment(self):
        self.assertEqual(
            _extract_post_id_from_live_url("https://www.youtube.com/post/Ugkx-W8-XYZ#reply"),
            "Ugkx-W8-XYZ",
        )

    def test_matches_same_post(self):
        self.assertTrue(_post_url_matches_expected("https://www.youtube.com/post/ABC", "ABC"))

    def test_rejects_different_post(self):
        self.assertFalse(_post_url_matches_expected("https://www.youtube.com/post/XYZ", "ABC"))

    def test_rejects_channel_feed_url(self):
        self.assertFalse(_post_url_matches_expected("https://www.youtube.com/@TFJ7/posts", "ABC"))

    def test_rejects_unrelated_watch_url(self):
        self.assertFalse(
            _post_url_matches_expected("https://www.youtube.com/watch?v=someVideoId", "ABC")
        )


class ListeningPidParsingTests(unittest.TestCase):
    def test_parses_bare_pid_lines(self):
        self.assertEqual(_parse_listening_pids("4242\n5555\n"), {4242, 5555})

    def test_ignores_blank_and_non_numeric_lines(self):
        self.assertEqual(_parse_listening_pids("\n4242\n\nnot-a-pid\n"), {4242})

    def test_empty_output_is_an_empty_set(self):
        self.assertEqual(_parse_listening_pids(""), set())


class ProcessTreeParsingTests(unittest.TestCase):
    def test_parses_pid_ppid_pairs_into_a_children_map(self):
        children = _parse_process_children("1 0\n4242 1\n5555 4242\n6666 1\n")
        self.assertEqual(sorted(children[1]), [4242, 6666])
        self.assertEqual(children[4242], [5555])

    def test_ignores_malformed_lines(self):
        children = _parse_process_children("4242 1\nnot a valid line at all\n5555 4242\n")
        self.assertEqual(children[1], [4242])
        self.assertEqual(children[4242], [5555])

    def test_descendants_of_includes_root_and_every_level(self):
        children = {1: [4242], 4242: [5555, 6666], 5555: [7777]}
        self.assertEqual(_descendants_of(4242, children), {4242, 5555, 6666, 7777})

    def test_descendants_of_a_leaf_is_just_itself(self):
        self.assertEqual(_descendants_of(9999, {}), {9999})


def _session_with_fake_process() -> AcquisitionBrowserSession:
    """A session already marked 'started' without actually starting one."""

    session = AcquisitionBrowserSession(
        AcquisitionBrowserConfig(profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9999)
    )
    session._process = MagicMock()
    return session


def _ownership_confirmed(session: AcquisitionBrowserSession, pid: int):
    """Patches _listening_pids/_descendant_pids on one session instance so
    the real listener is found to be exactly the spawned PID -- used by
    tests that need start() to actually succeed, without shelling out to
    real lsof/ps."""

    return patch.multiple(
        session,
        _listening_pids=MagicMock(return_value={pid}),
        _descendant_pids=MagicMock(return_value={pid}),
    )


class SessionLaunchTests(unittest.TestCase):
    def test_refuses_personal_profile_before_launching_anything(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(profile_dir=PERSONAL_BRAVE_PROFILE_ROOT, debugging_port=9999)
        )
        with patch("subprocess.Popen") as popen:
            with self.assertRaises(ValueError):
                session.start()
            popen.assert_not_called()

    def test_launch_command_is_localhost_only_and_uses_the_dedicated_profile(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status.return_value = None
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        fake_process.pid = 4242
        with patch("subprocess.Popen", return_value=fake_process) as popen, patch(
            "requests.get", side_effect=[ConnectionError("not up yet"), fake_response]
        ) as get, _ownership_confirmed(session, 4242):
            session.start()

        command = popen.call_args[0][0]
        self.assertIn("--remote-debugging-address=127.0.0.1", command)
        self.assertNotIn("--remote-debugging-address=0.0.0.0", command)
        self.assertIn("--user-data-dir=/tmp/warrigal-acquisition-brave", command)
        self.assertIn("--remote-debugging-port=9222", command)
        get.assert_called_with("http://127.0.0.1:9222/json/version", timeout=1)

    def test_launch_command_allow_lists_exactly_its_own_origin_never_a_wildcard(self):
        # Regression check for a live-confirmed failure: Chromium rejects
        # the CDP WebSocket handshake with 403 Forbidden unless the
        # client's own origin is explicitly allow-listed. This must be the
        # exact http://127.0.0.1:<port> origin this session itself uses --
        # never "*", which would accept a handshake claiming to originate
        # from anywhere.
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status.return_value = None
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        fake_process.pid = 4242
        with patch("subprocess.Popen", return_value=fake_process) as popen, patch(
            "requests.get", side_effect=[ConnectionError("not up yet"), fake_response]
        ), _ownership_confirmed(session, 4242):
            session.start()

        command = popen.call_args[0][0]
        self.assertIn("--remote-allow-origins=http://127.0.0.1:9222", command)
        self.assertNotIn("--remote-allow-origins=*", command)

    def test_start_is_idempotent(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status.return_value = None
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        fake_process.pid = 4242
        with patch("subprocess.Popen", return_value=fake_process) as popen, patch(
            "requests.get", side_effect=[ConnectionError("not up yet"), fake_response]
        ), _ownership_confirmed(session, 4242):
            session.start()
            session.start()
        self.assertEqual(popen.call_count, 1)

    def test_launch_timeout_raises_and_tears_down(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        with patch("subprocess.Popen", return_value=fake_process), patch(
            "requests.get", side_effect=ConnectionError("not up yet")
        ):
            with self.assertRaises(RuntimeError):
                session.start(launch_timeout=0.3)
        fake_process.terminate.assert_called_once()

    def test_headless_flag_is_included_by_default(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status.return_value = None
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        fake_process.pid = 4242
        with patch("subprocess.Popen", return_value=fake_process) as popen, patch(
            "requests.get", side_effect=[ConnectionError("not up yet"), fake_response]
        ), _ownership_confirmed(session, 4242):
            session.start()
        self.assertIn("--headless=new", popen.call_args[0][0])

    def test_headless_flag_is_omitted_when_disabled_for_the_one_time_login(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"),
                debugging_port=9222,
                headless=False,
            )
        )
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status.return_value = None
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        fake_process.pid = 4242
        with patch("subprocess.Popen", return_value=fake_process) as popen, patch(
            "requests.get", side_effect=[ConnectionError("not up yet"), fake_response]
        ), _ownership_confirmed(session, 4242):
            session.start()
        self.assertNotIn("--headless=new", popen.call_args[0][0])


class EndpointOwnershipTests(unittest.TestCase):
    def test_refuses_to_start_if_something_already_answers_before_launch(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status.return_value = None
        with patch("subprocess.Popen") as popen, patch("requests.get", return_value=fake_response):
            with self.assertRaises(EndpointOwnershipError):
                session.start()
        popen.assert_not_called()

    def test_refuses_to_trust_an_endpoint_whose_listener_is_not_this_sessions_process_or_a_descendant(
        self,
    ):
        # Live-observed root cause this replaces: Brave's own CDP
        # /json/version response identifies as "Chrome/151.0.7922.137",
        # never "Brave" -- so the brand string can never prove ownership.
        # Ownership is instead proven (or refused) by tracing the actual
        # listening socket's PID back to this session's own process tree.
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status.return_value = None
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        fake_process.pid = 4242
        with patch("subprocess.Popen", return_value=fake_process), patch(
            "requests.get", side_effect=[ConnectionError("not up yet"), fake_response]
        ), patch.multiple(
            session,
            _listening_pids=MagicMock(return_value={9999}),
            _descendant_pids=MagicMock(return_value={4242}),
        ):
            with self.assertRaises(EndpointOwnershipError) as raised:
                session.start()

        self.assertIn("9999", str(raised.exception))
        self.assertIn("4242", str(raised.exception))
        # Cleanup is preserved: only the process this session itself
        # spawned is terminated before the error propagates -- the
        # unrelated process actually holding the port (9999) is never
        # touched, and nothing is left running.
        fake_process.terminate.assert_called_once()
        fake_process.wait.assert_called_once_with(timeout=5)
        self.assertIsNone(session._process)

    def test_refuses_to_trust_an_endpoint_when_no_listener_can_be_confirmed(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status.return_value = None
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        fake_process.pid = 4242
        with patch("subprocess.Popen", return_value=fake_process), patch(
            "requests.get", side_effect=[ConnectionError("not up yet"), fake_response]
        ), patch.multiple(
            session,
            _listening_pids=MagicMock(return_value=set()),
            _descendant_pids=MagicMock(return_value={4242}),
        ):
            with self.assertRaises(EndpointOwnershipError):
                session.start()
        fake_process.terminate.assert_called_once()
        self.assertIsNone(session._process)

    def test_accepts_a_listener_that_is_a_descendant_of_the_spawned_process(self):
        # The spawned PID (a launcher) is not itself the listener -- a
        # descendant PID (the real browser process it exec'd/forked into)
        # is -- and that must still be accepted as this session's own.
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status.return_value = None
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        fake_process.pid = 4242
        with patch("subprocess.Popen", return_value=fake_process), patch(
            "requests.get", side_effect=[ConnectionError("not up yet"), fake_response]
        ), patch.multiple(
            session,
            _listening_pids=MagicMock(return_value={5555}),
            _descendant_pids=MagicMock(return_value={4242, 5555}),
        ):
            session.start()  # must not raise
        self.assertIsNotNone(session._process)

    def test_fails_fast_if_the_process_exits_before_answering(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_process = MagicMock()
        fake_process.poll.return_value = 1
        fake_process.returncode = 1
        with patch("subprocess.Popen", return_value=fake_process), patch(
            "requests.get", side_effect=ConnectionError("not up yet")
        ) as get:
            with self.assertRaises(RuntimeError):
                session.start(launch_timeout=5.0)
        # Must fail immediately on noticing the process has already exited,
        # not by exhausting the whole launch_timeout retrying it.
        self.assertEqual(get.call_count, 1)


class OwnershipHelperSubprocessTests(unittest.TestCase):
    """The thin subprocess-calling layer under _verify_endpoint_ownership --
    separate from the pure parsing tested above."""

    def test_listening_pids_runs_lsof_scoped_to_the_configured_port(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_result = MagicMock(stdout="4242\n")
        with patch("subprocess.run", return_value=fake_result) as run:
            self.assertEqual(session._listening_pids(), {4242})
        args = run.call_args[0][0]
        self.assertEqual(args[0], "lsof")
        self.assertIn("-iTCP:9222", args)
        self.assertIn("-sTCP:LISTEN", args)

    def test_listening_pids_is_empty_if_lsof_itself_fails(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        with patch("subprocess.run", side_effect=OSError("lsof not found")):
            self.assertEqual(session._listening_pids(), set())

    def test_descendant_pids_runs_ps_and_walks_the_tree(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        fake_result = MagicMock(stdout="4242 1\n5555 4242\n9999 1\n")
        with patch("subprocess.run", return_value=fake_result) as run:
            self.assertEqual(session._descendant_pids(4242), {4242, 5555})
        args = run.call_args[0][0]
        self.assertEqual(args[0], "ps")

    def test_descendant_pids_falls_back_to_just_the_root_if_ps_fails(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        with patch("subprocess.run", side_effect=OSError("ps not found")):
            self.assertEqual(session._descendant_pids(4242), {4242})


class StableDefaultConfigTests(unittest.TestCase):
    def test_default_config_uses_the_documented_stable_profile_and_port(self):
        config = default_acquisition_browser_config()
        self.assertEqual(config.profile_dir, DEFAULT_ACQUISITION_PROFILE_DIR)
        self.assertEqual(config.debugging_port, DEFAULT_ACQUISITION_DEBUGGING_PORT)
        self.assertEqual(config.executable, DEFAULT_BRAVE_EXECUTABLE)
        self.assertTrue(config.headless)

    def test_default_config_is_stable_across_repeated_calls(self):
        self.assertEqual(default_acquisition_browser_config(), default_acquisition_browser_config())

    def test_default_config_is_never_the_personal_profile(self):
        _assert_not_personal_profile(default_acquisition_browser_config().profile_dir)

    def test_default_config_accepts_overrides(self):
        config = default_acquisition_browser_config(debugging_port=1234, headless=False)
        self.assertEqual(config.debugging_port, 1234)
        self.assertFalse(config.headless)
        self.assertEqual(config.profile_dir, DEFAULT_ACQUISITION_PROFILE_DIR)


class SessionStopTests(unittest.TestCase):
    def test_stop_is_safe_when_never_started(self):
        session = AcquisitionBrowserSession(
            AcquisitionBrowserConfig(
                profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
            )
        )
        session.stop()  # must not raise

    def test_stop_terminates_then_waits(self):
        session = _session_with_fake_process()
        fake_process = session._process
        fake_process.wait.return_value = 0
        session.stop()
        fake_process.terminate.assert_called_once()
        fake_process.wait.assert_called_once_with(timeout=5)
        fake_process.kill.assert_not_called()

    def test_stop_kills_if_terminate_does_not_finish_in_time(self):
        session = _session_with_fake_process()
        fake_process = session._process
        fake_process.wait.side_effect = [subprocess.TimeoutExpired(cmd="brave", timeout=5), 0]
        session.stop()
        fake_process.kill.assert_called_once()
        self.assertEqual(fake_process.wait.call_count, 2)

    def test_stop_closes_every_open_tab_first(self):
        session = _session_with_fake_process()
        with patch.object(session, "close_tab") as close_tab:
            session._open_tabs = {"A": object(), "B": object()}
            session.stop()
        self.assertEqual(close_tab.call_count, 2)


class FakeWebSocket:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.sent: list[dict] = []
        self.closed = False

    def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    def recv(self) -> str:
        return json.dumps(self._responses.pop(0))

    def close(self) -> None:
        self.closed = True


class TabWireProtocolTests(unittest.TestCase):
    def _open_tab_with(self, ws: FakeWebSocket):
        session = _session_with_fake_process()
        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "id": "TAB1",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9999/devtools/page/TAB1",
        }
        with patch("requests.put", return_value=fake_response), patch(
            "websocket.create_connection", return_value=ws
        ):
            tab = session.open_tab("https://example.com")
        return session, tab

    def test_evaluate_correlates_matching_message_id(self):
        ws = FakeWebSocket([{"id": 1, "result": {"result": {"value": "OK"}}}])
        session, tab = self._open_tab_with(ws)
        self.assertEqual(session.evaluate(tab, "1+1"), "OK")
        self.assertEqual(ws.sent[0]["method"], "Runtime.evaluate")

    def test_evaluate_skips_interleaved_non_matching_messages(self):
        ws = FakeWebSocket(
            [
                {"id": 999, "result": {"result": {"value": "ignore me"}}},
                {"method": "Page.loadEventFired"},
                {"id": 1, "result": {"result": {"value": "real answer"}}},
            ]
        )
        session, tab = self._open_tab_with(ws)
        self.assertEqual(session.evaluate(tab, "x"), "real answer")

    def test_evaluate_raises_on_exception_details(self):
        ws = FakeWebSocket(
            [{"id": 1, "result": {"result": {}, "exceptionDetails": {"text": "boom"}}}]
        )
        session, tab = self._open_tab_with(ws)
        with self.assertRaises(RuntimeError):
            session.evaluate(tab, "throw new Error('boom')")

    def test_close_tab_closes_socket_and_calls_close_endpoint_and_forgets_the_tab(self):
        ws = FakeWebSocket([])
        session, tab = self._open_tab_with(ws)
        with patch("requests.get") as get:
            session.close_tab(tab)
        self.assertTrue(ws.closed)
        get.assert_called_once_with("http://127.0.0.1:9999/json/close/TAB1", timeout=10)
        self.assertNotIn("TAB1", session._open_tabs)

    def test_open_tab_closes_the_newly_created_tab_if_the_websocket_connection_fails(self):
        session = _session_with_fake_process()
        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "id": "TAB1",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9999/devtools/page/TAB1",
        }
        with patch("requests.put", return_value=fake_response), patch(
            "websocket.create_connection", side_effect=ConnectionRefusedError("refused")
        ), patch("requests.get") as get:
            with self.assertRaises(ConnectionRefusedError):
                session.open_tab("https://example.com")
        get.assert_called_once_with("http://127.0.0.1:9999/json/close/TAB1", timeout=10)
        self.assertNotIn("TAB1", session._open_tabs)


class FakeSession:
    """A hand-written double for the three high-level runner functions --
    not a real AcquisitionBrowserSession, so each scenario can script exact
    evaluate()/current_url() sequences without any network or process."""

    def __init__(self, *, urls=None, advances=None, bootstrap="OK", finalize="{}"):
        self._urls = list(urls) if urls is not None else []
        self._advances = list(advances) if advances is not None else []
        self._bootstrap = bootstrap
        self._finalize = finalize
        self.opened: list[str] = []
        self.closed: list[object] = []
        self.calls: list[str] = []

    def open_tab(self, url: str):
        self.opened.append(url)
        return object()

    def close_tab(self, tab) -> None:
        self.closed.append(tab)

    def current_url(self, tab) -> str:
        return self._urls.pop(0) if self._urls else self.opened[-1]

    def evaluate(self, tab, expression: str):
        self.calls.append(expression)
        if expression == _POST_COMMENTS_BOOTSTRAP_JS:
            return self._bootstrap
        if expression == _POST_COMMENTS_ADVANCE_JS:
            return self._advances.pop(0)
        if expression == _POST_COMMENTS_FINALIZE_JS:
            return self._finalize
        if expression == _RESOLVE_HANDLE_JS:
            return "UCresolved0000000000"
        return None


class PostCommentCollectionRunnerTests(unittest.TestCase):
    @patch("time.sleep", lambda *_: None)
    def test_advance_done_stops_before_round_limit(self):
        session = FakeSession(
            urls=["https://www.youtube.com/post/P1"] * 3,
            advances=["DONE"],
            finalize='{"comments": []}',
        )
        result = run_cdp_post_comment_collection(
            "https://www.youtube.com/post/P1", 10, 60, session=session
        )
        self.assertEqual(result, '{"comments": []}')
        self.assertNotIn("window.__wrgRoundLimitReached = true;", session.calls)
        self.assertEqual(len(session.closed), 1)

    @patch("time.sleep", lambda *_: None)
    def test_round_limit_reached_is_flagged_when_loop_is_exhausted(self):
        session = FakeSession(
            urls=["https://www.youtube.com/post/P1"] * 5,
            advances=["CONTINUE", "CONTINUE"],
            finalize="{}",
        )
        run_cdp_post_comment_collection("https://www.youtube.com/post/P1", 2, 60, session=session)
        self.assertIn("window.__wrgRoundLimitReached = true;", session.calls)

    @patch("time.sleep", lambda *_: None)
    def test_tab_is_closed_even_when_bootstrap_fails(self):
        session = FakeSession(
            urls=["https://www.youtube.com/post/P1"], bootstrap="SelectorError: boom"
        )
        with self.assertRaises(RuntimeError):
            run_cdp_post_comment_collection(
                "https://www.youtube.com/post/P1", 10, 60, session=session
            )
        self.assertEqual(len(session.closed), 1)

    @patch("time.sleep", lambda *_: None)
    def test_tab_is_closed_when_the_tab_navigates_away(self):
        session = FakeSession(urls=["https://www.youtube.com/watch?v=unrelated"])
        with self.assertRaises(RuntimeError):
            run_cdp_post_comment_collection(
                "https://www.youtube.com/post/P1", 10, 60, session=session
            )
        self.assertEqual(len(session.closed), 1)
        self.assertEqual(session.opened, ["https://www.youtube.com/post/P1"])


class HandleResolutionRunnerTests(unittest.TestCase):
    @patch("time.sleep", lambda *_: None)
    def test_returns_resolved_channel_id_on_success(self):
        session = FakeSession(urls=["https://www.youtube.com/@TFJ7"])
        result = run_cdp_handle_resolution("https://www.youtube.com/@TFJ7", session=session)
        self.assertEqual(result, "UCresolved0000000000")
        self.assertEqual(len(session.closed), 1)

    @patch("time.sleep", lambda *_: None)
    def test_raises_and_still_closes_tab_when_navigated_away(self):
        session = FakeSession(urls=["https://example.com/not-youtube"])
        with self.assertRaises(RuntimeError):
            run_cdp_handle_resolution("https://www.youtube.com/@TFJ7", session=session)
        self.assertEqual(len(session.closed), 1)


class PostFeedDiscoveryRunnerTests(unittest.TestCase):
    class _FeedFakeSession(FakeSession):
        def __init__(self, *, heights, href="https://www.youtube.com/@TFJ7/posts"):
            super().__init__(urls=[href])
            self._href = href
            self._heights = list(heights)

        def current_url(self, tab) -> str:
            return self._href

        def evaluate(self, tab, expression: str):
            self.calls.append(expression)
            if "querySelectorAll" in expression and "post" in expression:
                return "[]"
            if "scrollHeight" in expression and "toString" in expression:
                return self._heights.pop(0)
            return None

    @patch("time.sleep", lambda *_: None)
    def test_stabilizes_when_height_repeats_for_stable_rounds(self):
        session = self._FeedFakeSession(heights=["100", "200", "200", "200"])
        result = run_cdp_post_feed_discovery(
            "https://www.youtube.com/@TFJ7/posts", max_scrolls=10, delay=0, stable_rounds=2,
            session=session,
        )
        self.assertTrue(result.endswith("__WRG_STABILIZED__"))
        self.assertEqual(len(session.closed), 1)

    @patch("time.sleep", lambda *_: None)
    def test_reports_scroll_limit_reached_when_height_never_settles(self):
        session = self._FeedFakeSession(heights=["100", "200", "300", "400"])
        result = run_cdp_post_feed_discovery(
            "https://www.youtube.com/@TFJ7/posts", max_scrolls=4, delay=0, stable_rounds=10,
            session=session,
        )
        self.assertTrue(result.endswith("__WRG_SCROLL_LIMIT_REACHED__"))

    @patch("time.sleep", lambda *_: None)
    def test_raises_when_tab_is_not_on_youtube(self):
        session = self._FeedFakeSession(heights=[], href="https://example.com/elsewhere")
        with self.assertRaises(RuntimeError):
            run_cdp_post_feed_discovery(
                "https://www.youtube.com/@TFJ7/posts", max_scrolls=4, delay=0, stable_rounds=2,
                session=session,
            )
        self.assertEqual(len(session.closed), 1)


class AcquisitionCdpRunnersTests(unittest.TestCase):
    """Verifies the wiring bundle used by the single-post and campaign CLI
    entry points -- explicit session setup/cleanup, and that the yielded
    callables are bound through youtube_post_comments.py's own existing
    injection points (runner=/resolve_handle=) rather than any new ones."""

    @staticmethod
    def _config() -> AcquisitionBrowserConfig:
        return AcquisitionBrowserConfig(
            profile_dir=Path("/tmp/warrigal-acquisition-brave"), debugging_port=9222
        )

    def test_starts_and_stops_the_session_around_the_yielded_runners(self):
        with patch.object(AcquisitionBrowserSession, "start") as start, patch.object(
            AcquisitionBrowserSession, "stop"
        ) as stop:
            with acquisition_cdp_runners(self._config()) as cdp:
                self.assertIsInstance(cdp, AcquisitionCdpRunners)
                stop.assert_not_called()
            start.assert_called_once()
            stop.assert_called_once()

    def test_stops_the_session_even_if_the_body_raises(self):
        with patch.object(AcquisitionBrowserSession, "start"), patch.object(
            AcquisitionBrowserSession, "stop"
        ) as stop:
            with self.assertRaises(ValueError):
                with acquisition_cdp_runners(self._config()):
                    raise ValueError("boom")
            stop.assert_called_once()

    def test_yielded_callables_are_bound_through_the_existing_injection_points(self):
        with patch.object(AcquisitionBrowserSession, "start"), patch.object(
            AcquisitionBrowserSession, "stop"
        ):
            with acquisition_cdp_runners(self._config()) as cdp:
                self.assertIs(cdp.comment_extractor.func, collect_post_comments_via_browser)
                self.assertIs(
                    cdp.comment_extractor.keywords["runner"], cdp.comment_collection_runner
                )
                self.assertIs(cdp.comment_extractor.keywords["resolve_handle"], cdp.handle_resolver)

                self.assertIs(cdp.handle_resolver.func, resolve_channel_id_via_handle)
                self.assertIs(cdp.handle_resolver.keywords["runner"], cdp.handle_resolution_runner)

                self.assertIs(cdp.post_feed_refresher.func, refresh_post_feed_via_browser)
                self.assertIs(
                    cdp.post_feed_refresher.keywords["runner"], cdp.post_feed_discovery_runner
                )

                self.assertIs(cdp.comment_collection_runner.func, run_cdp_post_comment_collection)
                self.assertIs(cdp.comment_collection_runner.keywords["session"], cdp.session)

                self.assertIs(cdp.handle_resolution_runner.func, run_cdp_handle_resolution)
                self.assertIs(cdp.handle_resolution_runner.keywords["session"], cdp.session)

                self.assertIs(cdp.post_feed_discovery_runner.func, run_cdp_post_feed_discovery)
                self.assertIs(cdp.post_feed_discovery_runner.keywords["session"], cdp.session)

    def test_uses_the_stable_default_config_when_none_is_supplied(self):
        with patch.object(AcquisitionBrowserSession, "start"), patch.object(
            AcquisitionBrowserSession, "stop"
        ):
            with acquisition_cdp_runners() as cdp:
                self.assertEqual(cdp.session.config.profile_dir, DEFAULT_ACQUISITION_PROFILE_DIR)
                self.assertEqual(
                    cdp.session.config.debugging_port, DEFAULT_ACQUISITION_DEBUGGING_PORT
                )


if __name__ == "__main__":
    unittest.main()
