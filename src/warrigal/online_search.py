"""Online Search source for the Warrigal Research Suite.

Three providers are supported, all producing the same
`OnlineSearchResult` shape so `format_online_search_compact` and the GUI
wiring work identically regardless of which one answered the query:

    - SearXNG (`search_searxng`) - the DEFAULT. Account-free: no API key,
      no sign-up, no payment detail of any kind. Calls a configured
      SearXNG instance's documented JSON API
      (`<instance_url>/search?q=...&format=json`).
    - Brave (`search_brave`) - OPTIONAL, preserved exactly as before.
      Requires a configured Brave Search API key. Still fully usable; it
      is simply no longer the default.
    - Tavily (`search_tavily`) - OPTIONAL, same shape as Brave. Requires
      a configured Tavily API key. POSTs to Tavily's documented search
      endpoint (`https://api.tavily.com/search`) with the key in an
      `Authorization: Bearer` header and a JSON body of `{"query": ...}`.

`search_online` is the single dispatch entry point the GUI calls; it
resolves which provider to use (explicit argument, else the configured
default - see `resolve_online_search_provider`) and delegates to
`search_searxng`, `search_brave`, or `search_tavily` unchanged. All three
provider functions also remain independently callable/testable.

Scope, deliberately narrow, for all three providers:
    - This module ONLY calls a search API and formats the results
      (title / URL / snippet) for display.
    - It never downloads, acquires, or indexes anything, and never writes
      to the object store, the database, or any acquisition/checkpoint
      path. A single call to `search_brave`/`search_searxng`/
      `search_tavily` performs exactly one HTTP request and returns
      in-memory results - nothing is persisted.
    - It is intentionally isolated from `warrigal.acquisition` and from
      `warrigal.workflows`'s `build_workflow_plan`/`_*_plan` machinery:
      Online Search has no acquisition side effects to orchestrate, so it
      does not need that subprocess-based plan mechanism.

Credential handling (Brave and Tavily only - SearXNG needs none):
    - The Brave API key is read via `warrigal.config.WarrigalConfig`
      (environment variable `WARRIGAL_BRAVE_API_KEY` first, then the
      `[search].brave_api_key` value from `warrigal.local.toml`).
    - The Tavily API key follows the identical precedence
      (`WARRIGAL_TAVILY_API_KEY` first, then `[search].tavily_api_key`).
    - The Brave key is sent only in the `X-Subscription-Token` request
      header, never in the URL or query parameters. The Tavily key is
      sent only in the `Authorization: Bearer` request header, never in
      the URL, query parameters, or JSON body.
    - Neither key's value is ever included in any message this module
      raises, logs, or returns - see `BRAVE_API_KEY_SETUP_MESSAGE` and
      `TAVILY_API_KEY_SETUP_MESSAGE`, which are fixed strings naming only
      the two configuration *options* for each provider, and the error
      classes below, whose messages are fixed/templated strings that
      never interpolate either key itself.

SearXNG instance configuration follows the identical env-var-first,
local-file-fallback precedence pattern: environment variable
`WARRIGAL_SEARXNG_URL` first, then `[search].searxng_instance_url` in
`warrigal.local.toml`, then the built-in default public instance
(`warrigal.config.DEFAULT_SEARXNG_INSTANCE_URL`, currently
`https://searx.be`). The provider itself follows the same pattern:
`WARRIGAL_ONLINE_SEARCH_PROVIDER` env var, then `[search].provider` in
`warrigal.local.toml`, then the built-in default (`"searxng"`).

Disclosed limitation: the response parsing in `parse_brave_response`
below is shaped from Brave's published Web Search API documentation,
reasoned about rather than confirmed against a live call - no network
request was made while building or testing the Brave path. If Brave's
actual response differs in field names or nesting, parsing may need
adjustment; unrecognized or missing fields are handled by substituting
placeholders rather than raising, so a shape mismatch degrades to empty
results rather than crashing.

Disclosed limitation (SearXNG): `parse_searxng_response` is likewise
shaped from SearXNG's documented JSON API, not confirmed against a live
call - a live verification was attempted while building this module
against two public instances (`https://searx.be`, then one alternative,
`https://priv.au`); neither returned a usable JSON response (the first
served an anti-bot/verification page with HTTP 200, the second returned
HTTP 429 rate-limited). Both failure modes were confirmed to be handled
by `search_searxng` without crashing (see `OnlineSearchRequestError`
below and the project report for the exact observed output). If a
reachable instance's real response differs from the documented shape
assumed here, parsing may need adjustment.

Disclosed limitation (Tavily): `parse_tavily_response` is shaped from
Tavily's published Search API documentation (`results[].{title, url,
content, score, ...}`), reasoned about rather than confirmed against a
live call at the time this provider was added - see the task report for
whether a live check was possible (it depends on a Tavily API key being
configured). Unrecognized or missing fields are handled the same way as
the other two providers: by substituting placeholders rather than
raising, so a shape mismatch degrades to empty results rather than
crashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import requests

from warrigal.config import CONFIG, WarrigalConfig


BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"

# The three supported Online Search providers. "searxng" is account-free
# and is the default; "brave" and "tavily" are optional and each require
# their own configured API key (see `require_brave_api_key` /
# `require_tavily_api_key`).
ONLINE_SEARCH_PROVIDERS = ("searxng", "brave", "tavily")
DEFAULT_ONLINE_SEARCH_PROVIDER = "searxng"

# A single search call requests up to this many results; the "show more"
# interaction in the source panel pages over that already-fetched list
# client-side (see `format_online_search_compact`) rather than issuing
# another API call. This mirrors the Archive Search compact-results
# convention (`source_panel.ARCHIVE_SEARCH_PAGE_SIZE` /
# `ARCHIVE_SEARCH_PREVIEW_CHARS`), which also fetches its full result set
# in one call and paginates over it in memory.
ONLINE_SEARCH_RESULT_COUNT = 20
ONLINE_SEARCH_PAGE_SIZE = 10
ONLINE_SEARCH_PREVIEW_CHARS = 220

BRAVE_API_KEY_SETUP_MESSAGE = (
    "Online Search needs a Brave Search API key before it can run. "
    "Set one of the following, then try again:\n"
    "  1. warrigal.local.toml -> [search] section -> brave_api_key = \"...\"\n"
    "  2. Environment variable WARRIGAL_BRAVE_API_KEY\n"
    "Sign up at Brave Search API to get a key."
)

TAVILY_API_KEY_SETUP_MESSAGE = (
    "Online Search needs a Tavily API key before it can run. "
    "Set one of the following, then try again:\n"
    "  1. warrigal.local.toml -> [search] section -> tavily_api_key = \"...\"\n"
    "  2. Environment variable WARRIGAL_TAVILY_API_KEY\n"
    "Sign up at Tavily to get a key."
)


class OnlineSearchSetupError(RuntimeError):
    """No API key is configured for the selected credentialed provider
    (Brave or Tavily). Always carries the fixed
    `BRAVE_API_KEY_SETUP_MESSAGE` or `TAVILY_API_KEY_SETUP_MESSAGE` -
    never a credential value."""


class OnlineSearchRequestError(RuntimeError):
    """The search provider's API call itself failed (network error,
    non-200 response, or a response that could not be parsed as JSON).
    Messages are fixed/templated strings that never include an API
    key."""


@dataclass(frozen=True)
class OnlineSearchResult:
    title: str
    url: str
    snippet: str


def resolve_brave_api_key(config: WarrigalConfig | None = None) -> str | None:
    """Return the configured Brave API key, or None if neither the
    environment variable nor the local TOML value is set."""

    config = config or CONFIG
    return config.brave_api_key


def require_brave_api_key(config: WarrigalConfig | None = None) -> str:
    """Return the configured Brave API key, or raise
    `OnlineSearchSetupError` with the fixed setup message if neither
    configuration option is present."""

    api_key = resolve_brave_api_key(config)
    if not api_key:
        raise OnlineSearchSetupError(BRAVE_API_KEY_SETUP_MESSAGE)
    return api_key


def resolve_tavily_api_key(config: WarrigalConfig | None = None) -> str | None:
    """Return the configured Tavily API key, or None if neither the
    environment variable nor the local TOML value is set."""

    config = config or CONFIG
    return config.tavily_api_key


def require_tavily_api_key(config: WarrigalConfig | None = None) -> str:
    """Return the configured Tavily API key, or raise
    `OnlineSearchSetupError` with the fixed setup message if neither
    configuration option is present."""

    api_key = resolve_tavily_api_key(config)
    if not api_key:
        raise OnlineSearchSetupError(TAVILY_API_KEY_SETUP_MESSAGE)
    return api_key


def resolve_searxng_instance_url(config: WarrigalConfig | None = None) -> str:
    """Return the configured SearXNG instance base URL (env var, then
    local TOML, then the built-in public-instance default - see
    `warrigal.config.load_config`). Always returns a usable value; no
    setup is required for this account-free path."""

    config = config or CONFIG
    return config.searxng_instance_url


def resolve_online_search_provider(config: WarrigalConfig | None = None) -> str:
    """Return the configured default Online Search provider
    (`"searxng"`, `"brave"`, or `"tavily"`), normalized to lowercase. Falls back to
    `DEFAULT_ONLINE_SEARCH_PROVIDER` ("searxng") for any unrecognized or
    empty value, so a typo in config never silently disables Online
    Search or forces the credentialed path."""

    config = config or CONFIG
    provider = str(config.online_search_provider or "").strip().lower()
    return provider if provider in ONLINE_SEARCH_PROVIDERS else DEFAULT_ONLINE_SEARCH_PROVIDER


def _truncate_snippet(text: str, limit: int = ONLINE_SEARCH_PREVIEW_CHARS) -> str:
    """Collapse whitespace and bound snippet length, mirroring
    `source_panel._truncate_preview`; never dump an unbounded snippet."""

    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "..."


def parse_brave_response(payload: object) -> list[OnlineSearchResult]:
    """Parse a Brave Web Search API JSON response into compact result
    rows (title / URL / snippet).

    Only reads `web.results[].{title,url,description}`; any other
    section of the response (news, videos, infobox, FAQ, discussions,
    etc.) is ignored - Online Search shows web results only. Missing or
    malformed fields are tolerated by substituting placeholders rather
    than raising, so an unexpected response shape degrades to an empty
    or partial list instead of crashing the search.
    """

    web = payload.get("web") if isinstance(payload, dict) else None
    raw_results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(raw_results, list):
        return []

    results: list[OnlineSearchResult] = []
    for entry in raw_results:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "(untitled)")
        url = str(entry.get("url") or "")
        snippet = _truncate_snippet(str(entry.get("description") or ""))
        results.append(OnlineSearchResult(title=title, url=url, snippet=snippet))
    return results


def search_brave(
    query: str,
    *,
    config: WarrigalConfig | None = None,
    get: Callable[..., "requests.Response"] = requests.get,
    count: int = ONLINE_SEARCH_RESULT_COUNT,
    timeout: float = 10.0,
) -> list[OnlineSearchResult]:
    """Call the Brave Search API for `query` and return parsed, bounded
    results.

    This performs exactly one HTTP GET and nothing else: no download, no
    acquisition, no indexing, no write to the object store, database, or
    any checkpoint path. `get` defaults to `requests.get` but can be
    swapped (e.g. in tests) to avoid any real network call.

    Raises:
        ValueError: `query` is empty.
        OnlineSearchSetupError: no Brave API key is configured.
        OnlineSearchRequestError: the HTTP call failed, returned a
            non-200 status, or returned a body that could not be parsed
            as JSON.
    """

    if not query or not query.strip():
        raise ValueError("Enter a search query.")

    api_key = require_brave_api_key(config)

    try:
        response = get(
            BRAVE_SEARCH_ENDPOINT,
            headers={
                "Accept": "application/json",
                # The key travels only in this header, never in the URL
                # or query parameters, so it cannot end up in request
                # logs or error messages that mention the request URL.
                "X-Subscription-Token": api_key,
            },
            params={"q": query, "count": count},
            timeout=timeout,
        )
    except Exception as exc:
        raise OnlineSearchRequestError(
            "Online Search request failed. Check your network connection and try again."
        ) from exc

    if response.status_code in (401, 403):
        raise OnlineSearchRequestError(
            f"Online Search request was rejected (status {response.status_code}). "
            "The configured Brave API key may be invalid or revoked."
        )
    if response.status_code != 200:
        raise OnlineSearchRequestError(
            f"Online Search request failed with status {response.status_code}."
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise OnlineSearchRequestError(
            "Online Search received a response that could not be parsed as JSON."
        ) from exc

    return parse_brave_response(payload)


def parse_searxng_response(payload: object) -> list[OnlineSearchResult]:
    """Parse a SearXNG JSON API response
    (`<instance_url>/search?q=...&format=json`) into the same compact
    result rows `parse_brave_response` produces.

    Only reads the top-level `results[].{title,url,content}` array -
    SearXNG's documented JSON API shape. Missing or malformed fields are
    tolerated by substituting placeholders rather than raising, matching
    `parse_brave_response`'s tolerance, so an unexpected response shape
    degrades to an empty or partial list instead of crashing the search.
    """

    raw_results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw_results, list):
        return []

    results: list[OnlineSearchResult] = []
    for entry in raw_results:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "(untitled)")
        url = str(entry.get("url") or "")
        snippet = _truncate_snippet(str(entry.get("content") or ""))
        results.append(OnlineSearchResult(title=title, url=url, snippet=snippet))
    return results


def search_searxng(
    query: str,
    *,
    instance_url: str | None = None,
    config: WarrigalConfig | None = None,
    get: Callable[..., "requests.Response"] = requests.get,
    count: int = ONLINE_SEARCH_RESULT_COUNT,
    timeout: float = 10.0,
) -> list[OnlineSearchResult]:
    """Call a SearXNG instance's documented JSON API for `query` and
    return parsed, bounded results. Account-free: no API key, sign-up, or
    payment detail of any kind is needed - this is the DEFAULT Online
    Search path.

    This performs exactly one HTTP GET and nothing else: no download, no
    acquisition, no indexing, no write to the object store, database, or
    any checkpoint path. `get` defaults to `requests.get` but can be
    swapped (e.g. in tests) to avoid any real network call.

    `instance_url` overrides the configured instance for this call only;
    when omitted, `resolve_searxng_instance_url` is used (env var, then
    local TOML, then the built-in public-instance default).

    Raises:
        ValueError: `query` is empty.
        OnlineSearchRequestError: the HTTP call failed, returned a
            non-200 status, or returned a body that could not be parsed
            as JSON. The configured instance URL is named in the
            message (it is not a credential) to make a misconfigured or
            unreachable instance easy to diagnose.
    """

    if not query or not query.strip():
        raise ValueError("Enter a search query.")

    resolved_instance = (instance_url or resolve_searxng_instance_url(config)).rstrip("/")

    try:
        response = get(
            f"{resolved_instance}/search",
            headers={"Accept": "application/json"},
            params={"q": query, "format": "json"},
            timeout=timeout,
        )
    except Exception as exc:
        raise OnlineSearchRequestError(
            f"Online Search request to {resolved_instance} failed. Check your "
            "network connection, or the configured SearXNG instance URL, and try again."
        ) from exc

    if response.status_code != 200:
        raise OnlineSearchRequestError(
            f"Online Search request to {resolved_instance} failed with status "
            f"{response.status_code}."
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise OnlineSearchRequestError(
            f"Online Search received a response from {resolved_instance} that "
            "could not be parsed as JSON."
        ) from exc

    return parse_searxng_response(payload)[:count]


def parse_tavily_response(payload: object) -> list[OnlineSearchResult]:
    """Parse a Tavily Search API JSON response into the same compact
    result rows `parse_brave_response`/`parse_searxng_response` produce.

    Only reads the top-level `results[].{title,url,content}` array -
    Tavily's documented Search API shape. Missing or malformed fields
    are tolerated by substituting placeholders rather than raising,
    matching the other two providers' tolerance, so an unexpected
    response shape degrades to an empty or partial list instead of
    crashing the search.
    """

    raw_results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw_results, list):
        return []

    results: list[OnlineSearchResult] = []
    for entry in raw_results:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "(untitled)")
        url = str(entry.get("url") or "")
        snippet = _truncate_snippet(str(entry.get("content") or ""))
        results.append(OnlineSearchResult(title=title, url=url, snippet=snippet))
    return results


def search_tavily(
    query: str,
    *,
    config: WarrigalConfig | None = None,
    post: Callable[..., "requests.Response"] = requests.post,
    count: int = ONLINE_SEARCH_RESULT_COUNT,
    timeout: float = 10.0,
) -> list[OnlineSearchResult]:
    """Call the Tavily Search API for `query` and return parsed, bounded
    results.

    This performs exactly one HTTP POST and nothing else: no download, no
    acquisition, no indexing, no write to the object store, database, or
    any checkpoint path. `post` defaults to `requests.post` but can be
    swapped (e.g. in tests) to avoid any real network call.

    Raises:
        ValueError: `query` is empty.
        OnlineSearchSetupError: no Tavily API key is configured.
        OnlineSearchRequestError: the HTTP call failed, returned a
            non-200 status, or returned a body that could not be parsed
            as JSON.
    """

    if not query or not query.strip():
        raise ValueError("Enter a search query.")

    api_key = require_tavily_api_key(config)

    try:
        response = post(
            TAVILY_SEARCH_ENDPOINT,
            headers={
                "Accept": "application/json",
                # The key travels only in this header, never in the URL,
                # query parameters, or JSON body, so it cannot end up in
                # request logs or error messages that mention the
                # request URL or body.
                "Authorization": f"Bearer {api_key}",
            },
            json={"query": query},
            timeout=timeout,
        )
    except Exception as exc:
        raise OnlineSearchRequestError(
            "Online Search request failed. Check your network connection and try again."
        ) from exc

    if response.status_code in (401, 403):
        raise OnlineSearchRequestError(
            f"Online Search request was rejected (status {response.status_code}). "
            "The configured Tavily API key may be invalid or revoked."
        )
    if response.status_code != 200:
        raise OnlineSearchRequestError(
            f"Online Search request failed with status {response.status_code}."
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise OnlineSearchRequestError(
            "Online Search received a response that could not be parsed as JSON."
        ) from exc

    return parse_tavily_response(payload)[:count]


def search_online(
    query: str,
    *,
    provider: str | None = None,
    instance_url: str | None = None,
    config: WarrigalConfig | None = None,
    get: Callable[..., "requests.Response"] = requests.get,
    post: Callable[..., "requests.Response"] = requests.post,
    count: int = ONLINE_SEARCH_RESULT_COUNT,
    timeout: float = 10.0,
) -> list[OnlineSearchResult]:
    """Single Online Search entry point: resolves which provider to use
    and delegates unchanged to `search_searxng` (default, account-free),
    `search_brave`, or `search_tavily` (both optional, each requiring
    their own configured API key).

    `provider` overrides the configured default for this call only (any
    value other than exactly `"brave"` or `"tavily"`, case-insensitively,
    is treated as `"searxng"` - the safe, account-free choice); when
    omitted, `resolve_online_search_provider` is used.
    """

    resolved_provider = str(provider or resolve_online_search_provider(config) or "").strip().lower()
    if resolved_provider == "brave":
        return search_brave(query, config=config, get=get, count=count, timeout=timeout)
    if resolved_provider == "tavily":
        return search_tavily(query, config=config, post=post, count=count, timeout=timeout)
    return search_searxng(
        query,
        instance_url=instance_url,
        config=config,
        get=get,
        count=count,
        timeout=timeout,
    )


def format_online_search_compact(
    results: Sequence[OnlineSearchResult],
    start: int,
    count: int,
) -> str:
    """Render a compact title / URL / snippet view for one page of
    results, mirroring `source_panel.format_archive_search_compact` but
    kept entirely separate so Archive Search's own display is unaffected.
    """

    lines: list[str] = []
    for offset, result in enumerate(results[start : start + count], start=start + 1):
        lines.append(f"{offset}. {result.title}")
        lines.append(f"    {result.url}")
        if result.snippet:
            lines.append(f"    {result.snippet}")
        lines.append("")
    return "\n".join(lines)
