"""Focused tests for the Online Search (Brave, SearXNG, Tavily) adapters.

No live network calls are made anywhere in this file: every HTTP call is
replaced with an injected fake (`unittest.mock.Mock`), and every fixture
response is a hand-built dict shaped like each provider's published API
documentation - never a response captured from, or verified against, a
real call.

`FAKE_BRAVE_API_KEY` and `FAKE_TAVILY_API_KEY` are test-only placeholder
values. Neither is ever a real credential, and the tests below
specifically assert they never appear in any string this module produces
(setup message, error messages, parsed results, or the compact display
text).
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import Mock

from warrigal.config import CONFIG, DEFAULT_SEARXNG_INSTANCE_URL
from warrigal.online_search import (
    BRAVE_API_KEY_SETUP_MESSAGE,
    BRAVE_SEARCH_ENDPOINT,
    DEFAULT_ONLINE_SEARCH_PROVIDER,
    ONLINE_SEARCH_PAGE_SIZE,
    ONLINE_SEARCH_PROVIDERS,
    TAVILY_API_KEY_SETUP_MESSAGE,
    TAVILY_SEARCH_ENDPOINT,
    OnlineSearchRequestError,
    OnlineSearchResult,
    OnlineSearchSetupError,
    format_online_search_compact,
    parse_brave_response,
    parse_searxng_response,
    parse_tavily_response,
    require_brave_api_key,
    require_tavily_api_key,
    resolve_brave_api_key,
    resolve_online_search_provider,
    resolve_searxng_instance_url,
    resolve_tavily_api_key,
    search_brave,
    search_online,
    search_searxng,
    search_tavily,
)


FAKE_BRAVE_API_KEY = "test-only-fake-brave-key-do-not-use-1234567890"
FAKE_TAVILY_API_KEY = "test-only-fake-tavily-key-do-not-use-1234567890"


def _config_with_key(key: str | None):
    return replace(CONFIG, brave_api_key=key)


def _config_with_tavily_key(key: str | None):
    return replace(CONFIG, tavily_api_key=key)


def _config_with_search_settings(
    *, instance_url: str | None = None, provider: str | None = None
):
    kwargs = {}
    if instance_url is not None:
        kwargs["searxng_instance_url"] = instance_url
    if provider is not None:
        kwargs["online_search_provider"] = provider
    return replace(CONFIG, **kwargs)


def _searxng_response_fixture(entries: list[dict]) -> dict:
    """A fixture shaped like SearXNG's documented JSON API response: a
    top-level `results` list of {title, url, content, ...}. Reasoned
    from SearXNG's documented JSON API shape, the same disclosed
    limitation as the Brave fixture above - the live verification
    attempted for this task did not receive a usable JSON response from
    either public instance tried (one returned an anti-bot page, the
    other was rate-limited), so this shape is not independently
    confirmed against a live call. See the project report for the exact
    live-verification outcome."""

    return {
        "query": "test query",
        "number_of_results": len(entries),
        "results": entries,
    }


def _brave_response_fixture(entries: list[dict]) -> dict:
    """A fixture shaped like Brave's Web Search API response: a top-level
    `web.results` list of {title, url, description, ...}. Reasoned from
    Brave's published API documentation - not captured from, or verified
    against, a live call (see the module docstring above and the task
    report for this disclosed limitation)."""

    return {
        "query": {"original": "test query"},
        "type": "search",
        "web": {
            "type": "search",
            "results": entries,
        },
    }


def _tavily_response_fixture(entries: list[dict]) -> dict:
    """A fixture shaped like Tavily's published Search API response: a
    top-level `results` list of {title, url, content, score, ...}.
    Reasoned from Tavily's published API documentation, the same
    disclosed limitation as the Brave/SearXNG fixtures above - not
    captured from, or verified against, a live call unless a Tavily key
    was configured when this provider was added (see the task report)."""

    return {
        "query": "test query",
        "results": entries,
    }


class BraveApiKeyResolutionTests(unittest.TestCase):
    """`resolve_brave_api_key`/`require_brave_api_key` just read whatever
    `WarrigalConfig.brave_api_key` already resolved to. The env-var-over-
    TOML precedence itself is covered in tests/test_config.py, at the
    layer that actually implements it."""

    def test_resolve_returns_the_configured_key(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        self.assertEqual(resolve_brave_api_key(config), FAKE_BRAVE_API_KEY)

    def test_resolve_returns_none_when_absent(self):
        config = _config_with_key(None)
        self.assertIsNone(resolve_brave_api_key(config))

    def test_require_returns_the_key_when_present(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        self.assertEqual(require_brave_api_key(config), FAKE_BRAVE_API_KEY)

    def test_require_raises_setup_error_naming_both_options_when_absent(self):
        config = _config_with_key(None)
        with self.assertRaises(OnlineSearchSetupError) as ctx:
            require_brave_api_key(config)
        message = str(ctx.exception)
        self.assertEqual(message, BRAVE_API_KEY_SETUP_MESSAGE)
        self.assertIn("[search]", message)
        self.assertIn("brave_api_key", message)
        self.assertIn("WARRIGAL_BRAVE_API_KEY", message)
        # No pricing/quota numbers belong in this message - out of scope
        # and unverified; only a generic pointer to sign up.
        self.assertIn("Brave Search API", message)


class TavilyApiKeyResolutionTests(unittest.TestCase):
    """`resolve_tavily_api_key`/`require_tavily_api_key` just read
    whatever `WarrigalConfig.tavily_api_key` already resolved to. The
    env-var-over-TOML precedence itself is covered in
    tests/test_config.py, at the layer that actually implements it."""

    def test_resolve_returns_the_configured_key(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        self.assertEqual(resolve_tavily_api_key(config), FAKE_TAVILY_API_KEY)

    def test_resolve_returns_none_when_absent(self):
        config = _config_with_tavily_key(None)
        self.assertIsNone(resolve_tavily_api_key(config))

    def test_require_returns_the_key_when_present(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        self.assertEqual(require_tavily_api_key(config), FAKE_TAVILY_API_KEY)

    def test_require_raises_setup_error_naming_both_options_when_absent(self):
        config = _config_with_tavily_key(None)
        with self.assertRaises(OnlineSearchSetupError) as ctx:
            require_tavily_api_key(config)
        message = str(ctx.exception)
        self.assertEqual(message, TAVILY_API_KEY_SETUP_MESSAGE)
        self.assertIn("[search]", message)
        self.assertIn("tavily_api_key", message)
        self.assertIn("WARRIGAL_TAVILY_API_KEY", message)
        self.assertIn("Tavily", message)


class CredentialNeverLeakedTests(unittest.TestCase):
    """The configured key must never appear in any produced output
    string: not the setup message, not request-error messages, not the
    request itself outside its header, and not parsed/formatted results."""

    def test_setup_message_never_contains_the_fake_key(self):
        self.assertNotIn(FAKE_BRAVE_API_KEY, BRAVE_API_KEY_SETUP_MESSAGE)

    def test_key_is_sent_only_as_a_header_never_in_params_or_url(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        response = Mock(status_code=200)
        response.json.return_value = _brave_response_fixture([])
        get = Mock(return_value=response)
        search_brave("radionics", config=config, get=get)
        args, kwargs = get.call_args
        self.assertEqual(args[0], BRAVE_SEARCH_ENDPOINT)
        self.assertEqual(kwargs["headers"]["X-Subscription-Token"], FAKE_BRAVE_API_KEY)
        self.assertNotIn(FAKE_BRAVE_API_KEY, str(kwargs.get("params", {})))
        self.assertNotIn(FAKE_BRAVE_API_KEY, args[0])

    def test_http_failure_status_error_message_never_contains_the_key(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        response = Mock(status_code=500)
        get = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_brave("radionics", config=config, get=get)
        self.assertNotIn(FAKE_BRAVE_API_KEY, str(ctx.exception))

    def test_unauthorized_status_error_message_never_contains_the_key(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        response = Mock(status_code=401)
        get = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_brave("radionics", config=config, get=get)
        message = str(ctx.exception)
        self.assertIn("401", message)
        self.assertNotIn(FAKE_BRAVE_API_KEY, message)

    def test_network_failure_error_message_never_contains_the_key(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)

        def _raise(*_args, **_kwargs):
            raise ConnectionError(f"could not reach host (token={FAKE_BRAVE_API_KEY})")

        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_brave("radionics", config=config, get=_raise)
        self.assertNotIn(FAKE_BRAVE_API_KEY, str(ctx.exception))

    def test_unparseable_json_error_message_never_contains_the_key(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        response = Mock(status_code=200)
        response.json.side_effect = ValueError(f"bad json near {FAKE_BRAVE_API_KEY}")
        get = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_brave("radionics", config=config, get=get)
        self.assertNotIn(FAKE_BRAVE_API_KEY, str(ctx.exception))

    def test_parsed_and_formatted_results_never_echo_the_key(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        payload = _brave_response_fixture(
            [{"title": "Example", "url": "https://example.test", "description": "A snippet."}]
        )
        response = Mock(status_code=200)
        response.json.return_value = payload
        get = Mock(return_value=response)
        results = search_brave("radionics", config=config, get=get)
        compact = format_online_search_compact(results, 0, len(results))
        self.assertNotIn(FAKE_BRAVE_API_KEY, compact)
        for result in results:
            self.assertNotIn(FAKE_BRAVE_API_KEY, result.title)
            self.assertNotIn(FAKE_BRAVE_API_KEY, result.url)
            self.assertNotIn(FAKE_BRAVE_API_KEY, result.snippet)

    def test_tavily_setup_message_never_contains_the_fake_key(self):
        self.assertNotIn(FAKE_TAVILY_API_KEY, TAVILY_API_KEY_SETUP_MESSAGE)

    def test_tavily_key_is_sent_only_as_a_header_never_in_params_body_or_url(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        response = Mock(status_code=200)
        response.json.return_value = _tavily_response_fixture([])
        post = Mock(return_value=response)
        search_tavily("radionics", config=config, post=post)
        args, kwargs = post.call_args
        self.assertEqual(args[0], TAVILY_SEARCH_ENDPOINT)
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {FAKE_TAVILY_API_KEY}")
        self.assertNotIn(FAKE_TAVILY_API_KEY, str(kwargs.get("json", {})))
        self.assertNotIn(FAKE_TAVILY_API_KEY, args[0])

    def test_tavily_http_failure_status_error_message_never_contains_the_key(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        response = Mock(status_code=500)
        post = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_tavily("radionics", config=config, post=post)
        self.assertNotIn(FAKE_TAVILY_API_KEY, str(ctx.exception))

    def test_tavily_unauthorized_status_error_message_never_contains_the_key(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        response = Mock(status_code=401)
        post = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_tavily("radionics", config=config, post=post)
        message = str(ctx.exception)
        self.assertIn("401", message)
        self.assertNotIn(FAKE_TAVILY_API_KEY, message)

    def test_tavily_network_failure_error_message_never_contains_the_key(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)

        def _raise(*_args, **_kwargs):
            raise ConnectionError(f"could not reach host (token={FAKE_TAVILY_API_KEY})")

        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_tavily("radionics", config=config, post=_raise)
        self.assertNotIn(FAKE_TAVILY_API_KEY, str(ctx.exception))

    def test_tavily_unparseable_json_error_message_never_contains_the_key(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        response = Mock(status_code=200)
        response.json.side_effect = ValueError(f"bad json near {FAKE_TAVILY_API_KEY}")
        post = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_tavily("radionics", config=config, post=post)
        self.assertNotIn(FAKE_TAVILY_API_KEY, str(ctx.exception))

    def test_tavily_parsed_and_formatted_results_never_echo_the_key(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        payload = _tavily_response_fixture(
            [{"title": "Example", "url": "https://example.test", "content": "A snippet.", "score": 0.9}]
        )
        response = Mock(status_code=200)
        response.json.return_value = payload
        post = Mock(return_value=response)
        results = search_tavily("radionics", config=config, post=post)
        compact = format_online_search_compact(results, 0, len(results))
        self.assertNotIn(FAKE_TAVILY_API_KEY, compact)
        for result in results:
            self.assertNotIn(FAKE_TAVILY_API_KEY, result.title)
            self.assertNotIn(FAKE_TAVILY_API_KEY, result.url)
            self.assertNotIn(FAKE_TAVILY_API_KEY, result.snippet)


class ParseBraveResponseTests(unittest.TestCase):
    def test_parses_title_url_and_snippet_from_a_realistic_fixture(self):
        payload = _brave_response_fixture(
            [
                {
                    "title": "Radionic Devices Overview",
                    "url": "https://example.test/radionics.html",
                    "description": "Radionic devices have been described in historical texts.",
                    "profile": {"name": "example.test", "url": "https://example.test"},
                    "age": "2024-01-01T00:00:00",
                    "language": "en",
                }
            ]
        )
        results = parse_brave_response(payload)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.title, "Radionic Devices Overview")
        self.assertEqual(result.url, "https://example.test/radionics.html")
        self.assertEqual(
            result.snippet,
            "Radionic devices have been described in historical texts.",
        )

    def test_missing_web_results_section_yields_empty_list(self):
        self.assertEqual(parse_brave_response({"query": {"original": "x"}}), [])

    def test_non_dict_payload_yields_empty_list(self):
        self.assertEqual(parse_brave_response("not a dict"), [])

    def test_missing_fields_in_a_result_use_placeholders_without_raising(self):
        results = parse_brave_response(_brave_response_fixture([{}]))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "(untitled)")
        self.assertEqual(results[0].url, "")
        self.assertEqual(results[0].snippet, "")

    def test_non_dict_entries_in_results_list_are_skipped(self):
        results = parse_brave_response(_brave_response_fixture(["not-a-dict", 123, None]))
        self.assertEqual(results, [])

    def test_multiple_results_are_parsed_in_order(self):
        payload = _brave_response_fixture(
            [
                {"title": "First", "url": "https://example.test/1", "description": "one"},
                {"title": "Second", "url": "https://example.test/2", "description": "two"},
            ]
        )
        results = parse_brave_response(payload)
        self.assertEqual([r.title for r in results], ["First", "Second"])


class BoundingAndTruncationTests(unittest.TestCase):
    def test_long_description_is_truncated_with_ellipsis(self):
        long_description = "word " * 200
        results = parse_brave_response(
            _brave_response_fixture(
                [{"title": "Long", "url": "https://example.test", "description": long_description}]
            )
        )
        self.assertTrue(results[0].snippet.endswith("..."))
        self.assertLess(len(results[0].snippet), len(long_description))

    def test_compact_view_shows_title_url_and_snippet(self):
        results = [
            OnlineSearchResult(
                title="Example", url="https://example.test", snippet="A short snippet."
            )
        ]
        compact = format_online_search_compact(results, 0, 1)
        self.assertIn("Example", compact)
        self.assertIn("https://example.test", compact)
        self.assertIn("A short snippet.", compact)

    def test_initial_page_is_bounded_to_page_size(self):
        results = [
            OnlineSearchResult(
                title=f"Result {i}", url=f"https://example.test/{i}", snippet="snippet"
            )
            for i in range(1, ONLINE_SEARCH_PAGE_SIZE + 5)
        ]
        first_page = format_online_search_compact(results, 0, ONLINE_SEARCH_PAGE_SIZE)
        for i in range(1, ONLINE_SEARCH_PAGE_SIZE + 1):
            self.assertIn(f"Result {i}", first_page)
        for i in range(ONLINE_SEARCH_PAGE_SIZE + 1, ONLINE_SEARCH_PAGE_SIZE + 5):
            self.assertNotIn(f"Result {i}", first_page)

    def test_show_more_reveals_results_beyond_the_initial_page(self):
        results = [
            OnlineSearchResult(
                title=f"Result {i}", url=f"https://example.test/{i}", snippet="snippet"
            )
            for i in range(1, ONLINE_SEARCH_PAGE_SIZE + 5)
        ]
        second_page = format_online_search_compact(
            results, ONLINE_SEARCH_PAGE_SIZE, ONLINE_SEARCH_PAGE_SIZE
        )
        self.assertIn(f"Result {ONLINE_SEARCH_PAGE_SIZE + 1}", second_page)
        self.assertNotIn("Result 1\n", second_page)


class SearchBraveRequestTests(unittest.TestCase):
    def test_raises_setup_error_and_never_calls_out_when_no_key_configured(self):
        config = _config_with_key(None)
        get = Mock()
        with self.assertRaises(OnlineSearchSetupError):
            search_brave("radionics", config=config, get=get)
        get.assert_not_called()

    def test_rejects_empty_query_before_any_request(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        get = Mock()
        with self.assertRaises(ValueError):
            search_brave("   ", config=config, get=get)
        get.assert_not_called()

    def test_successful_call_hits_the_expected_endpoint_and_parses_results(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        payload = _brave_response_fixture(
            [{"title": "Example", "url": "https://example.test", "description": "A snippet."}]
        )
        response = Mock(status_code=200)
        response.json.return_value = payload
        get = Mock(return_value=response)
        results = search_brave("radionics", config=config, get=get)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Example")
        args, kwargs = get.call_args
        self.assertEqual(args[0], BRAVE_SEARCH_ENDPOINT)
        self.assertEqual(kwargs["params"]["q"], "radionics")

    def test_non_200_status_raises_request_error(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        response = Mock(status_code=500)
        get = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError):
            search_brave("radionics", config=config, get=get)

    def test_unparseable_json_raises_request_error(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("bad json")
        get = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError):
            search_brave("radionics", config=config, get=get)

    def test_transport_exception_is_wrapped_as_request_error(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)

        def _raise(*_args, **_kwargs):
            raise ConnectionError("network unreachable")

        with self.assertRaises(OnlineSearchRequestError):
            search_brave("radionics", config=config, get=_raise)


class SearxngConfigResolutionTests(unittest.TestCase):
    """`resolve_searxng_instance_url`/`resolve_online_search_provider`
    just read whatever `WarrigalConfig` already resolved (env-var-over-
    TOML precedence is covered at the layer that implements it, in
    tests/test_config.py)."""

    def test_resolve_instance_url_returns_the_configured_value(self):
        config = _config_with_search_settings(instance_url="https://custom.test")
        self.assertEqual(resolve_searxng_instance_url(config), "https://custom.test")

    def test_resolve_instance_url_defaults_to_the_builtin_public_instance(self):
        config = _config_with_search_settings(instance_url=DEFAULT_SEARXNG_INSTANCE_URL)
        self.assertEqual(resolve_searxng_instance_url(config), DEFAULT_SEARXNG_INSTANCE_URL)

    def test_resolve_provider_returns_the_configured_value(self):
        config = _config_with_search_settings(provider="brave")
        self.assertEqual(resolve_online_search_provider(config), "brave")

    def test_resolve_provider_defaults_to_searxng(self):
        config = _config_with_search_settings(provider="searxng")
        self.assertEqual(resolve_online_search_provider(config), "searxng")
        self.assertEqual(resolve_online_search_provider(config), DEFAULT_ONLINE_SEARCH_PROVIDER)

    def test_resolve_provider_falls_back_to_searxng_for_an_unrecognized_value(self):
        config = _config_with_search_settings(provider="not-a-real-provider")
        self.assertEqual(resolve_online_search_provider(config), "searxng")

    def test_resolve_provider_is_case_insensitive(self):
        config = _config_with_search_settings(provider="BRAVE")
        self.assertEqual(resolve_online_search_provider(config), "brave")

    def test_providers_tuple_contains_exactly_searxng_brave_and_tavily(self):
        self.assertEqual(ONLINE_SEARCH_PROVIDERS, ("searxng", "brave", "tavily"))


class ParseSearxngResponseTests(unittest.TestCase):
    def test_parses_title_url_and_snippet_from_a_realistic_fixture(self):
        payload = _searxng_response_fixture(
            [
                {
                    "title": "Radionic Devices Overview",
                    "url": "https://example.test/radionics.html",
                    "content": "Radionic devices have been described in historical texts.",
                    "engine": "duckduckgo",
                    "category": "general",
                }
            ]
        )
        results = parse_searxng_response(payload)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.title, "Radionic Devices Overview")
        self.assertEqual(result.url, "https://example.test/radionics.html")
        self.assertEqual(
            result.snippet,
            "Radionic devices have been described in historical texts.",
        )

    def test_missing_results_key_yields_empty_list(self):
        self.assertEqual(parse_searxng_response({"query": "x"}), [])

    def test_non_dict_payload_yields_empty_list(self):
        self.assertEqual(parse_searxng_response("not a dict"), [])

    def test_missing_fields_in_a_result_use_placeholders_without_raising(self):
        results = parse_searxng_response(_searxng_response_fixture([{}]))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "(untitled)")
        self.assertEqual(results[0].url, "")
        self.assertEqual(results[0].snippet, "")

    def test_non_dict_entries_in_results_list_are_skipped(self):
        results = parse_searxng_response(_searxng_response_fixture(["not-a-dict", 123, None]))
        self.assertEqual(results, [])

    def test_multiple_results_are_parsed_in_order(self):
        payload = _searxng_response_fixture(
            [
                {"title": "First", "url": "https://example.test/1", "content": "one"},
                {"title": "Second", "url": "https://example.test/2", "content": "two"},
            ]
        )
        results = parse_searxng_response(payload)
        self.assertEqual([r.title for r in results], ["First", "Second"])

    def test_long_content_is_truncated_with_ellipsis(self):
        long_content = "word " * 200
        results = parse_searxng_response(
            _searxng_response_fixture(
                [{"title": "Long", "url": "https://example.test", "content": long_content}]
            )
        )
        self.assertTrue(results[0].snippet.endswith("..."))
        self.assertLess(len(results[0].snippet), len(long_content))

    # format_online_search_compact is already exercised against Brave
    # results in BoundingAndTruncationTests above; since it only reads
    # the shared OnlineSearchResult shape, confirming SearXNG-sourced
    # results render through the exact same formatter (not a
    # SearXNG-specific copy) is the point of this test.
    def test_searxng_results_render_through_the_shared_compact_formatter(self):
        results = parse_searxng_response(
            _searxng_response_fixture(
                [{"title": "Example", "url": "https://example.test", "content": "A short snippet."}]
            )
        )
        compact = format_online_search_compact(results, 0, len(results))
        self.assertIn("Example", compact)
        self.assertIn("https://example.test", compact)
        self.assertIn("A short snippet.", compact)


class SearchSearxngRequestTests(unittest.TestCase):
    def test_rejects_empty_query_before_any_request(self):
        get = Mock()
        with self.assertRaises(ValueError):
            search_searxng("   ", get=get)
        get.assert_not_called()

    def test_no_api_key_or_setup_is_required(self):
        """Unlike `search_brave`, a missing/absent API key must never
        block this path - there is no key to configure."""

        config = _config_with_key(None)
        response = Mock(status_code=200)
        response.json.return_value = _searxng_response_fixture([])
        get = Mock(return_value=response)
        results = search_searxng("radionics", config=config, get=get)
        self.assertEqual(results, [])
        get.assert_called_once()

    def test_successful_call_hits_the_configured_instances_search_endpoint(self):
        config = _config_with_search_settings(instance_url="https://custom.test")
        payload = _searxng_response_fixture(
            [{"title": "Example", "url": "https://example.test", "content": "A snippet."}]
        )
        response = Mock(status_code=200)
        response.json.return_value = payload
        get = Mock(return_value=response)
        results = search_searxng("radionics", config=config, get=get)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Example")
        args, kwargs = get.call_args
        self.assertEqual(args[0], "https://custom.test/search")
        self.assertEqual(kwargs["params"]["q"], "radionics")
        self.assertEqual(kwargs["params"]["format"], "json")

    def test_explicit_instance_url_argument_overrides_configured_default(self):
        config = _config_with_search_settings(instance_url="https://configured.test")
        response = Mock(status_code=200)
        response.json.return_value = _searxng_response_fixture([])
        get = Mock(return_value=response)
        search_searxng("radionics", instance_url="https://explicit.test", config=config, get=get)
        args, _kwargs = get.call_args
        self.assertEqual(args[0], "https://explicit.test/search")

    def test_trailing_slash_on_instance_url_does_not_produce_a_double_slash(self):
        response = Mock(status_code=200)
        response.json.return_value = _searxng_response_fixture([])
        get = Mock(return_value=response)
        search_searxng("radionics", instance_url="https://custom.test/", get=get)
        args, _kwargs = get.call_args
        self.assertEqual(args[0], "https://custom.test/search")

    def test_non_200_status_raises_request_error_naming_the_instance(self):
        response = Mock(status_code=429)
        get = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_searxng("radionics", instance_url="https://blocked.test", get=get)
        self.assertIn("429", str(ctx.exception))
        self.assertIn("https://blocked.test", str(ctx.exception))

    def test_html_response_with_200_status_raises_request_error_not_a_crash(self):
        """Reproduces the real failure mode observed during live
        verification: an anti-bot/verification page served with HTTP 200
        instead of JSON. Must degrade to a plain error, never a raw
        traceback reaching the GUI."""

        response = Mock(status_code=200)
        response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
        get = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError) as ctx:
            search_searxng("radionics", instance_url="https://searx.be", get=get)
        self.assertIn("could not be parsed as JSON", str(ctx.exception))

    def test_transport_exception_is_wrapped_as_request_error(self):
        def _raise(*_args, **_kwargs):
            raise ConnectionError("network unreachable")

        with self.assertRaises(OnlineSearchRequestError):
            search_searxng("radionics", instance_url="https://unreachable.test", get=_raise)

    def test_results_are_bounded_by_count(self):
        entries = [
            {"title": f"Result {i}", "url": f"https://example.test/{i}", "content": "x"}
            for i in range(30)
        ]
        response = Mock(status_code=200)
        response.json.return_value = _searxng_response_fixture(entries)
        get = Mock(return_value=response)
        results = search_searxng("radionics", get=get, count=5)
        self.assertEqual(len(results), 5)


class ParseTavilyResponseTests(unittest.TestCase):
    def test_parses_title_url_and_snippet_from_a_realistic_fixture(self):
        payload = _tavily_response_fixture(
            [
                {
                    "title": "Radionic Devices Overview",
                    "url": "https://example.test/radionics.html",
                    "content": "Radionic devices have been described in historical texts.",
                    "score": 0.87,
                }
            ]
        )
        results = parse_tavily_response(payload)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.title, "Radionic Devices Overview")
        self.assertEqual(result.url, "https://example.test/radionics.html")
        self.assertEqual(
            result.snippet,
            "Radionic devices have been described in historical texts.",
        )

    def test_missing_results_key_yields_empty_list(self):
        self.assertEqual(parse_tavily_response({"query": "x"}), [])

    def test_non_dict_payload_yields_empty_list(self):
        self.assertEqual(parse_tavily_response("not a dict"), [])

    def test_missing_fields_in_a_result_use_placeholders_without_raising(self):
        results = parse_tavily_response(_tavily_response_fixture([{}]))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "(untitled)")
        self.assertEqual(results[0].url, "")
        self.assertEqual(results[0].snippet, "")

    def test_non_dict_entries_in_results_list_are_skipped(self):
        results = parse_tavily_response(_tavily_response_fixture(["not-a-dict", 123, None]))
        self.assertEqual(results, [])

    def test_multiple_results_are_parsed_in_order(self):
        payload = _tavily_response_fixture(
            [
                {"title": "First", "url": "https://example.test/1", "content": "one"},
                {"title": "Second", "url": "https://example.test/2", "content": "two"},
            ]
        )
        results = parse_tavily_response(payload)
        self.assertEqual([r.title for r in results], ["First", "Second"])

    def test_long_content_is_truncated_with_ellipsis(self):
        long_content = "word " * 200
        results = parse_tavily_response(
            _tavily_response_fixture(
                [{"title": "Long", "url": "https://example.test", "content": long_content}]
            )
        )
        self.assertTrue(results[0].snippet.endswith("..."))
        self.assertLess(len(results[0].snippet), len(long_content))

    # format_online_search_compact is already exercised against Brave and
    # SearXNG results above; since it only reads the shared
    # OnlineSearchResult shape, confirming Tavily-sourced results render
    # through the exact same formatter (not a Tavily-specific copy) is
    # the point of this test.
    def test_tavily_results_render_through_the_shared_compact_formatter(self):
        results = parse_tavily_response(
            _tavily_response_fixture(
                [{"title": "Example", "url": "https://example.test", "content": "A short snippet."}]
            )
        )
        compact = format_online_search_compact(results, 0, len(results))
        self.assertIn("Example", compact)
        self.assertIn("https://example.test", compact)
        self.assertIn("A short snippet.", compact)


class SearchTavilyRequestTests(unittest.TestCase):
    def test_raises_setup_error_and_never_calls_out_when_no_key_configured(self):
        config = _config_with_tavily_key(None)
        post = Mock()
        with self.assertRaises(OnlineSearchSetupError):
            search_tavily("radionics", config=config, post=post)
        post.assert_not_called()

    def test_rejects_empty_query_before_any_request(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        post = Mock()
        with self.assertRaises(ValueError):
            search_tavily("   ", config=config, post=post)
        post.assert_not_called()

    def test_successful_call_hits_the_expected_endpoint_and_parses_results(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        payload = _tavily_response_fixture(
            [{"title": "Example", "url": "https://example.test", "content": "A snippet."}]
        )
        response = Mock(status_code=200)
        response.json.return_value = payload
        post = Mock(return_value=response)
        results = search_tavily("radionics", config=config, post=post)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Example")
        args, kwargs = post.call_args
        self.assertEqual(args[0], TAVILY_SEARCH_ENDPOINT)
        self.assertEqual(kwargs["json"], {"query": "radionics"})

    def test_non_200_status_raises_request_error(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        response = Mock(status_code=500)
        post = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError):
            search_tavily("radionics", config=config, post=post)

    def test_unparseable_json_raises_request_error(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("bad json")
        post = Mock(return_value=response)
        with self.assertRaises(OnlineSearchRequestError):
            search_tavily("radionics", config=config, post=post)

    def test_transport_exception_is_wrapped_as_request_error(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)

        def _raise(*_args, **_kwargs):
            raise ConnectionError("network unreachable")

        with self.assertRaises(OnlineSearchRequestError):
            search_tavily("radionics", config=config, post=_raise)

    def test_results_are_bounded_by_count(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        entries = [
            {"title": f"Result {i}", "url": f"https://example.test/{i}", "content": "x"}
            for i in range(30)
        ]
        response = Mock(status_code=200)
        response.json.return_value = _tavily_response_fixture(entries)
        post = Mock(return_value=response)
        results = search_tavily("radionics", config=config, post=post, count=5)
        self.assertEqual(len(results), 5)


class SearchOnlineDispatchTests(unittest.TestCase):
    """`search_online` is the single entry point the GUI calls; confirms
    it dispatches to the right provider without altering either
    provider function's own behavior."""

    def test_default_provider_is_searxng_and_requires_no_api_key(self):
        config = _config_with_search_settings(provider="searxng", instance_url="https://custom.test")
        response = Mock(status_code=200)
        response.json.return_value = _searxng_response_fixture([])
        get = Mock(return_value=response)
        search_online("radionics", config=config, get=get)
        args, _kwargs = get.call_args
        self.assertEqual(args[0], "https://custom.test/search")

    def test_explicit_provider_argument_overrides_the_configured_default(self):
        config = _config_with_search_settings(provider="searxng")
        response = Mock(status_code=200)
        response.json.return_value = _brave_response_fixture([])
        get = Mock(return_value=response)
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        search_online("radionics", provider="brave", config=config, get=get)
        args, _kwargs = get.call_args
        self.assertEqual(args[0], BRAVE_SEARCH_ENDPOINT)

    def test_provider_argument_is_case_insensitive(self):
        config = _config_with_key(FAKE_BRAVE_API_KEY)
        response = Mock(status_code=200)
        response.json.return_value = _brave_response_fixture([])
        get = Mock(return_value=response)
        search_online("radionics", provider="BRAVE", config=config, get=get)
        args, _kwargs = get.call_args
        self.assertEqual(args[0], BRAVE_SEARCH_ENDPOINT)

    def test_unrecognized_provider_argument_falls_back_to_searxng(self):
        config = _config_with_search_settings(instance_url="https://custom.test")
        response = Mock(status_code=200)
        response.json.return_value = _searxng_response_fixture([])
        get = Mock(return_value=response)
        search_online("radionics", provider="not-a-real-provider", config=config, get=get)
        args, _kwargs = get.call_args
        self.assertEqual(args[0], "https://custom.test/search")

    def test_brave_setup_error_still_raised_when_brave_selected_without_a_key(self):
        config = _config_with_key(None)
        get = Mock()
        with self.assertRaises(OnlineSearchSetupError):
            search_online("radionics", provider="brave", config=config, get=get)
        get.assert_not_called()

    def test_tavily_provider_argument_dispatches_to_search_tavily(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        response = Mock(status_code=200)
        response.json.return_value = _tavily_response_fixture([])
        post = Mock(return_value=response)
        search_online("radionics", provider="tavily", config=config, post=post)
        args, _kwargs = post.call_args
        self.assertEqual(args[0], TAVILY_SEARCH_ENDPOINT)

    def test_tavily_provider_argument_is_case_insensitive(self):
        config = _config_with_tavily_key(FAKE_TAVILY_API_KEY)
        response = Mock(status_code=200)
        response.json.return_value = _tavily_response_fixture([])
        post = Mock(return_value=response)
        search_online("radionics", provider="TAVILY", config=config, post=post)
        args, _kwargs = post.call_args
        self.assertEqual(args[0], TAVILY_SEARCH_ENDPOINT)

    def test_tavily_setup_error_still_raised_when_tavily_selected_without_a_key(self):
        config = _config_with_tavily_key(None)
        post = Mock()
        with self.assertRaises(OnlineSearchSetupError):
            search_online("radionics", provider="tavily", config=config, post=post)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
