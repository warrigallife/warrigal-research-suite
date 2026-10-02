"""Acquisition and preservation of comments beneath YouTube Community posts:
top-level comments and their nested replies, across every post on one
channel, through Liam's already logged-in browser session.

ARCHITECTURE: Community-post comment threads require a signed-in session to
render. An anonymous HTTP request cannot see what an authenticated browser
sees, and Warrigal never extracts, prints, copies, exports, or stores
passwords, cookies, or session tokens. The only correct path is the same one
Warrigal already uses for Instagram: drive the user's own already-running,
already-logged-in Brave Browser through macOS Apple Events (``osascript``),
reading and interacting with the live, authenticated DOM. Authentication
material never leaves the browser process; Warrigal only ever receives
JSON-stringified page content back over stdout.

PROVISIONAL, UNVERIFIED AGAINST A LIVE, AUTHENTICATED PAGE (see
``PROVISIONAL_ASSUMPTIONS``): the DOM selectors, progress-detection
heuristics, and content-state signals the embedded JavaScript uses are
best-effort, not verified live in this session. The Python-side contract --
the JSON shape the JavaScript returns, and everything this module does with
it (identity resolution, count reconciliation, completion semantics) -- is
fully specified and tested independently of that risk.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Iterable

from warrigal.acquisition.service import AcquisitionService
from warrigal.acquisition.youtube_posts import YouTubePostCheckpointStore
from warrigal.models import Passage, Source
from warrigal.object_store import ObjectStore
from warrigal.repository import WarrigalRepository


TARGET_AUTHOR_CHANNEL_ID = "UCa2sLLQdHhQX1gpSqijyZlg"

# The handle text is NEVER trusted as proof of identity by itself -- it is
# only used as a lookup key to trigger a live, authenticated resolution
# (see resolve_channel_id_via_handle) whose result is then compared exactly
# against TARGET_AUTHOR_CHANNEL_ID, the same as any other author_id source.
TARGET_AUTHOR_HANDLE = "@TFJ7"

# Only these id_basis values are treated as a genuinely stable, canonical
# YouTube identifier. Anything else (missing, unrecognized, or explicitly
# "ordinal_fallback") is provisional and must never become a checkpointed,
# passage-indexed, or permalinked identity.
STABLE_ID_BASES = frozenset({"polymer_data", "copy_link"})

# Flip to True only once a controlled, authenticated live validation has
# confirmed exactly what YouTube's displayed comment count measures (top
# level only? including replies? including hidden/deleted?). Confirmed live
# (2026-09) on the validated post that Community-post comment sections
# render the comments-header count element with an explicit is-empty flag --
# no number is ever bound into it for this content type -- so this stays
# False in practice for Community posts specifically; the switch and its
# comparison logic remain correct and tested for any content type where a
# real count is one day observed.
VISIBLE_COUNT_BASIS_IS_VERIFIED = False

# Practical, documented wall-clock failsafe -- not an arbitrary round cap.
# "Unlimited" (max_continuation_fetches=None) means "run until genuine
# progress-based exhaustion, bounded only by this generous safety net."
DEFAULT_WALL_CLOCK_BUDGET_SECONDS = 1800
_SECONDS_PER_ROUND_ESTIMATE = 2.5
_PRACTICAL_MAX_ROUNDS = int(DEFAULT_WALL_CLOCK_BUDGET_SECONDS / _SECONDS_PER_ROUND_ESTIMATE)

PROVISIONAL_ASSUMPTIONS = (
    "ytd-comments / ytd-comment-thread-renderer / ytd-comment-replies-renderer "
    "custom-element tag names",
    "#more-replies button selector for expanding collapsed reply threads",
    "signature-based progress detection (thread/reply counts) used to tell "
    "genuine new content apart from a present-but-nonfunctional button",
    "content_state signal used to distinguish hidden/unavailable reply "
    "content from a plain selector failure",
    "canonical-link/og:url/meta[itemprop=identifier] resolution continuing "
    "to expose a handle's channel ID on future YouTube page revisions",
)

# CONFIRMED by live, authenticated diagnosis on 2026-09 (see the module
# docstring's history for the validated post) -- kept here, not in
# PROVISIONAL_ASSUMPTIONS, because these are no longer guesses:
#   - the legacy Polymer bound-data path (`.data`/`.__data.data` on
#     ytd-comment-thread-renderer) is absent; commentId resolution relies on
#     the "copy_link" fallback in practice, not "polymer_data";
#   - the newer comment-view-model Lit element exposes no accessible bound
#     data via own properties, prototype getters, or HTML attributes;
#   - no /channel/UC... href is present anywhere in a rendered comment
#     thread -- author links are handle-based (/@handle) only;
#   - navigating the same authenticated tab to a handle's own page
#     (https://www.youtube.com/<handle>) reliably exposes its true channel
#     ID via link[rel=canonical], meta[property=og:url], or
#     meta[itemprop=identifier];
#   - the comments-header count element (#count > .count-text) is real and
#     correctly targeted, but YouTube marks it is-empty for Community-post
#     comment sections -- no number is ever rendered there for this content
#     type.

_DELETED_PLACEHOLDER_TEXTS = {
    "[comment deleted]",
    "[deleted]",
    "this comment has been deleted",
}

# The single source of truth for "this reason forces INCOMPLETE." Anything
# not in this set (e.g. comments_disabled, comments_unavailable,
# deleted_comment_placeholder_present) is informational only.
_BLOCKING_REASONS = {
    "missing_comments_panel",
    "round_limit_reached",
    "wall_clock_exceeded",
    "incomplete_reply_expansion",
    "malformed_response",
    "unstable_comment_identifier",
    "missing_comment_text",
    "hidden_reply_content",
    "orphaned_parent_reference",
    "visible_count_mismatch",
    "unverified_zero_comments",
    "scroll_limit_reached",
}
# NOTE: reaching top-level idle-stability (JS: top_level_stalled) is NOT a
# blocking reason. It is the intended, progress-based proof that no more
# top-level comments remain to load -- the same idle-until-stable signal
# Warrigal's own Instagram discovery already treats as genuine completion,
# not failure. Only an artificial round/wall-clock cutoff, or a "more
# replies" control that never actually expanded, count as incomplete.

_CREDENTIAL_KEY_MARKERS = (
    "cookie",
    "password",
    "access_token",
    "session_token",
    "auth_token",
    "authorization",
)


def _resolve_status(reasons: Iterable[str]) -> str:
    """The single place completion status is decided, from the reason set."""

    reasons = list(reasons)
    if any(r.startswith("fetch_failure:") for r in reasons):
        return "failed"
    if any(r in _BLOCKING_REASONS for r in reasons):
        return "incomplete"
    return "completed"


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class YouTubePostComment:
    comment_id: str
    parent_id: str | None
    order: int
    text: str
    author: str | None
    author_id: str | None
    author_url: str | None
    published_text: str | None
    like_count: str | None
    id_basis: str = "unknown"


@dataclass(frozen=True)
class RawPageRecord:
    """One raw browser response, tagged with why it was captured."""

    kind: str
    parent_id: str | None
    token: str | None
    page: dict[str, Any]


@dataclass(frozen=True)
class IdentityCoverage:
    """How much of a post's comment set resolved to a stable, canonical ID."""

    stable_id_count: int
    unresolved_provisional_count: int
    stable_id_coverage_complete: bool


@dataclass(frozen=True)
class PostCommentCounts:
    visible_comment_count: str | None
    visible_count_basis: str  # "verified" | "provisional" | "unavailable"
    top_level_count: int
    reply_count: int
    total_count: int
    count_match: str  # "true" | "false" | "unknown"


@dataclass(frozen=True)
class PostCommentCollection:
    """The complete result of one collection attempt for one post.

    ``comments`` holds only records with a verified stable ID and non-empty
    text -- the only records ever eligible to become canonical passages.
    ``provisional_records`` holds every other raw record encountered (raw
    evidence preserved, never indexed, never checkpointed, never
    permalinked).
    """

    post_id: str
    post_url: str
    comments: tuple[YouTubePostComment, ...]
    provisional_records: tuple[dict[str, Any], ...]
    raw_pages: tuple[RawPageRecord, ...]
    counts: PostCommentCounts
    identity_coverage: IdentityCoverage
    status: str
    reasons: tuple[str, ...]
    post_title: str | None = None
    post_author: str | None = None
    post_author_id: str | None = None
    post_author_url: str | None = None


@dataclass(frozen=True)
class YouTubePostCommentIngestionResult:
    post_id: str
    post_url: str
    object_id: str
    acquisition_id: str
    sha256: str
    counts: PostCommentCounts
    identity_coverage: IdentityCoverage
    collected_count: int
    new_count: int
    indexed_count: int
    target_author_comment_count: int
    deduplicated: bool
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PostCommentCampaignItemResult:
    post_id: str
    status: str
    reasons: tuple[str, ...] = ()
    collected_count: int = 0
    new_count: int = 0
    target_author_comment_count: int = 0


@dataclass(frozen=True)
class PostFeedRefreshResult:
    discovered_post_ids: frozenset[str]
    stabilized: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PostCommentCampaignResult:
    known_before_refresh: tuple[str, ...]
    newly_discovered: tuple[str, ...]
    attempted: tuple[str, ...]
    items: tuple[PostCommentCampaignItemResult, ...]
    feed_coverage_status: str = "complete"
    feed_coverage_reasons: tuple[str, ...] = ()

    @property
    def completed(self) -> tuple[str, ...]:
        return tuple(i.post_id for i in self.items if i.status == "completed")

    @property
    def incomplete(self) -> tuple[str, ...]:
        return tuple(i.post_id for i in self.items if i.status == "incomplete")

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(i.post_id for i in self.items if i.status == "failed")


PostCommentExtractor = Callable[[str, "int | None"], PostCommentCollection]
PostFeedRefresher = Callable[..., PostFeedRefreshResult]


def resolve_post_id(value: str) -> str:
    """Return a bare Community-post ID from either an ID or a post URL."""

    value = value.strip().rstrip("/")
    if "/post/" in value:
        return value.rsplit("/post/", 1)[1]
    return value


def _is_deleted_placeholder(text: str | None) -> bool:
    if not isinstance(text, str):
        return False
    return text.strip().lower() in _DELETED_PLACEHOLDER_TEXTS


def _contains_credential_shaped_key(value: Any) -> str | None:
    """Return the offending key path if any key looks credential-shaped."""

    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _CREDENTIAL_KEY_MARKERS):
                return str(key)
            found = _contains_credential_shaped_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _contains_credential_shaped_key(item)
            if found:
                return found
    return None


def _normalize_visible_count(value: str | None) -> str | None:
    """Treat an empty/whitespace-only value the same as absent.

    Confirmed live: YouTube renders the comments-header count element with
    an explicit ``is-empty`` flag for Community-post comment sections (no
    number is ever bound into it for this content type), which previously
    came through as ``""`` and was wrongly classified as "provisional" (a
    present-but-unverified value) rather than "unavailable" (no value at
    all).
    """

    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _parse_visible_count(value: str | None) -> int | None:
    value = _normalize_visible_count(value)
    if value is None:
        return None
    cleaned = value.replace(",", "")
    return int(cleaned) if cleaned.isdigit() else None


def _visible_count_basis(visible_comment_count: str | None) -> str:
    if _normalize_visible_count(visible_comment_count) is None:
        return "unavailable"
    return "verified" if VISIBLE_COUNT_BASIS_IS_VERIFIED else "provisional"


def _compare_visible_count(visible: str | None, total: int, basis: str) -> str:
    """Never claim a proven match/mismatch on unverified count semantics."""

    if basis != "verified":
        return "unknown"
    parsed = _parse_visible_count(visible)
    if parsed is None:
        return "unknown"
    return "true" if parsed == total else "false"


def _empty_counts(visible_comment_count: str | None = None) -> PostCommentCounts:
    basis = _visible_count_basis(visible_comment_count)
    return PostCommentCounts(
        visible_comment_count=visible_comment_count,
        visible_count_basis=basis,
        top_level_count=0,
        reply_count=0,
        total_count=0,
        count_match=_compare_visible_count(visible_comment_count, 0, basis),
    )


def _empty_identity_coverage() -> IdentityCoverage:
    return IdentityCoverage(
        stable_id_count=0, unresolved_provisional_count=0, stable_id_coverage_complete=True
    )


# --------------------------------------------------------------------------
# Per-post comment collection through the authenticated browser
# --------------------------------------------------------------------------


_POST_COMMENTS_BOOTSTRAP_JS = r"""
(() => {
  window.__wrgIdle = 0;
  window.__wrgNonProductiveClicks = 0;
  window.__wrgRounds = 0;
  window.__wrgStartTime = Date.now();
  window.__wrgPreviousSignature = null;
  window.__wrgPendingReplyClick = false;

  const commentText = (node) => {
    const el = node.querySelector('#content-text');
    return el ? el.innerText.trim() : null;
  };
  const contentState = (node) => {
    const hidden = node.querySelector('[hidden-explanation-text], .hidden-content-text');
    if (hidden) return 'hidden';
    return null;
  };
  const authorHandle = (node) => {
    const el = node.querySelector('#author-text');
    return el ? el.innerText.trim() : null;
  };
  const authorUrl = (node) => {
    const el = node.querySelector('a#author-text');
    return el ? el.href : null;
  };
  const authorChannelId = (node) => {
    // Primary: a bound Polymer/entity data model, if one is ever present
    // (confirmed absent for the current comment-view-model rendering, but
    // kept as the preferred path for any future/alternate rendering mode).
    try {
      const data = node.data || (node.__data && node.__data.data);
      const renderer = data && data.comment ? (data.comment.commentRenderer || data.comment) : null;
      const browseId = renderer && renderer.authorEndpoint && renderer.authorEndpoint.browseEndpoint
        ? renderer.authorEndpoint.browseEndpoint.browseId
        : null;
      if (browseId) return browseId;
    } catch (e) { /* fall through to href fallback */ }
    // Fallback: a genuine /channel/UC... href, when one is actually present.
    const href = authorUrl(node);
    if (!href) return null;
    const match = href.match(/\/channel\/(UC[\w-]+)/);
    return match ? match[1] : null;
  };
  const publishedText = (node) => {
    const el = node.querySelector('#published-time-text');
    return el ? el.innerText.trim() : null;
  };
  const likeCount = (node) => {
    const el = node.querySelector('#vote-count-middle');
    return el ? el.innerText.trim() : null;
  };
  const stableId = (node) => {
    try {
      const data = node.data || (node.__data && node.__data.data);
      const commentId = data && data.comment && data.comment.commentId
        ? data.comment.commentId
        : (data && data.commentId ? data.commentId : null);
      if (commentId) return { id: commentId, basis: 'polymer_data' };
    } catch (e) { /* fall through to copy-link / ordinal */ }
    const copyLink = node.querySelector('a[href*="lc="]');
    if (copyLink) {
      const match = copyLink.href.match(/[?&]lc=([^&]+)/);
      if (match) return { id: decodeURIComponent(match[1]), basis: 'copy_link' };
    }
    return null;
  };

  const collect = (node, parentId, order) => {
    const identity = stableId(node);
    const id = identity ? identity.id : (parentId ? (parentId + '-ordinal-' + order) : ('ordinal-' + order));
    return {
      id,
      id_basis: identity ? identity.basis : 'ordinal_fallback',
      parent_id: parentId,
      order,
      text: commentText(node) || '',
      content_state: contentState(node),
      author: authorHandle(node),
      author_id: authorChannelId(node),
      author_url: authorUrl(node),
      published_text: publishedText(node),
      like_count: likeCount(node),
    };
  };

  window.__wrgCollectThread = (node, order) => collect(node, null, order);
  window.__wrgCollectReply = (node, parentId, order) => collect(node, parentId, order);

  window.__wrgReplyButtons = () => Array.from(document.querySelectorAll(
    'ytd-comment-replies-renderer #more-replies button, '
    + 'ytd-comment-replies-renderer #more-replies-button, '
    + 'ytd-comment-replies-renderer #expander button'
  )).filter(el => el.getClientRects().length > 0
    && !el.closest('[hidden], [aria-hidden="true"]') && !el.disabled);

  window.__wrgSignature = () => (
    document.querySelectorAll('ytd-comment-thread-renderer').length
    + ':' + document.querySelectorAll('ytd-comment-renderer, ytd-comment-view-model').length
  );

  return 'OK';
})();
"""

_POST_COMMENTS_ADVANCE_JS = r"""
(() => {
  if (Date.now() - window.__wrgStartTime > window.__wrgWallClockBudgetMs) {
    window.__wrgWallClockExceeded = true;
    return 'DONE';
  }

  // Compare with the previous round AFTER the AppleScript delay, allowing
  // asynchronous reply loading to change the DOM before judging progress.
  const signature = window.__wrgSignature();
  if (window.__wrgPreviousSignature !== null) {
    if (signature !== window.__wrgPreviousSignature) {
      window.__wrgIdle = 0;
      window.__wrgNonProductiveClicks = 0;
    } else if (window.__wrgPendingReplyClick) {
      window.__wrgNonProductiveClicks += 1;
    } else {
      window.__wrgIdle += 1;
    }
  }
  window.__wrgPreviousSignature = signature;

  const buttons = window.__wrgReplyButtons();
  if (buttons.length && window.__wrgNonProductiveClicks >= 3) return 'DONE';
  if (!buttons.length && window.__wrgIdle >= 3) return 'DONE';

  const moreReplies = buttons[0];
  window.__wrgPendingReplyClick = !!moreReplies;
  if (moreReplies) {
    moreReplies.click();
  } else {
    window.scrollTo(0, document.documentElement.scrollHeight);
  }
  return 'CONTINUE';
})();
"""

_POST_COMMENTS_FINALIZE_JS = r"""
(() => {
  const panel = document.querySelector('ytd-comments, ytd-item-section-renderer#sections');
  const disabledMessage = document.querySelector('ytd-message-renderer');
  const disabledText = disabledMessage ? disabledMessage.innerText.toLowerCase() : '';

  const result = {
    post_id: (location.pathname.split('/').filter(Boolean).pop() || null),
    post_url: location.href.split('?')[0],
    post_title: (document.querySelector('#content-text') || {}).innerText || null,
    post_author: null,
    post_author_id: null,
    post_author_url: null,
    comments_panel_found: !!panel,
    comments_disabled: disabledText.includes('turned off') || disabledText.includes('disabled'),
    comments_unavailable: disabledText.includes('unavailable'),
    visible_comment_count: (() => {
      const el = document.querySelector('#count .count-text, ytd-comments-header-renderer #count');
      return el ? el.innerText.trim() : null;
    })(),
    rounds_used: window.__wrgRounds || 0,
    round_limit_reached: !!window.__wrgRoundLimitReached,
    wall_clock_exceeded: !!window.__wrgWallClockExceeded,
    top_level_stalled: (window.__wrgIdle || 0) >= 3 && !window.__wrgRoundLimitReached && !window.__wrgWallClockExceeded,
    reply_expansion_incomplete: window.__wrgReplyButtons().length > 0,
    comments: [],
  };

  const threads = document.querySelectorAll('ytd-comment-thread-renderer');
  threads.forEach((thread, index) => {
    result.comments.push(window.__wrgCollectThread(thread, index));
    const replies = thread.querySelectorAll('ytd-comment-replies-renderer ytd-comment-renderer, '
      + 'ytd-comment-replies-renderer ytd-comment-view-model');
    const parentId = result.comments[result.comments.length - 1].id;
    replies.forEach((reply, replyIndex) => {
      result.comments.push(window.__wrgCollectReply(reply, parentId, replyIndex));
    });
  });

  return JSON.stringify(result);
})();
"""

# Pure, Brave-independent text logic -- deliberately factored out of the
# tab-handling handlers below so the dedicated-tab identity check itself
# (not just its presence) can be executed and verified directly via
# `osascript`, with no running browser required.
_EXTRACT_POST_ID_APPLESCRIPT = r'''
on extractPostId(theURL)
    set cleanURL to theURL
    if cleanURL contains "?" then
        set AppleScript's text item delimiters to "?"
        set cleanURL to item 1 of (text items of cleanURL)
    end if
    if cleanURL contains "#" then
        set AppleScript's text item delimiters to "#"
        set cleanURL to item 1 of (text items of cleanURL)
    end if
    set AppleScript's text item delimiters to ""
    if cleanURL ends with "/" then
        set cleanURL to text 1 thru -2 of cleanURL
    end if
    set AppleScript's text item delimiters to "/"
    set lastPart to item -1 of (text items of cleanURL)
    set AppleScript's text item delimiters to ""
    return lastPart
end extractPostId

on urlMatchesExpectedPost(currentURL, expectedPostId)
    if currentURL does not start with "https://www.youtube.com/post/" then return false
    return (my extractPostId(currentURL)) is expectedPostId
end urlMatchesExpectedPost
'''

POST_COMMENTS_APPLESCRIPT = _EXTRACT_POST_ID_APPLESCRIPT + r'''
on resolveDedicatedTab(wantedWindowId)
    -- Addressed directly by window id -- never a scan over every window and
    -- every tab of every window, which races against unrelated tabs opening
    -- or closing elsewhere in the same Brave process (e.g. the user's own
    -- browsing) and can throw spurious "invalid index" errors that have
    -- nothing to do with this collection's own isolated window.
    tell application "Brave Browser"
        try
            return active tab of (window id wantedWindowId)
        on error
            error "Warrigal's isolated collection window was closed or lost during collection"
        end try
    end tell
end resolveDedicatedTab

on verifyDedicatedTabOnTarget(wantedWindowId, expectedPostId, stageLabel)
    set theTab to my resolveDedicatedTab(wantedWindowId)
    tell application "Brave Browser" to set currentURL to URL of theTab
    if not (my urlMatchesExpectedPost(currentURL, expectedPostId)) then
        error "Brave tab navigated away from the target post (" & stageLabel & "): expected post " & expectedPostId & " but the tab is now at " & currentURL
    end if
end verifyDedicatedTabOnTarget

on run argv
    set postURL to item 1 of argv
    set maximumRounds to (item 2 of argv) as integer
    set wallClockSeconds to (item 3 of argv) as integer
    set expectedPostId to my extractPostId(postURL)

    if application "Brave Browser" is not running then error "BRAVE NOT RUNNING"

    tell application "Brave Browser"
        -- Always a brand-new, isolated window dedicated to this one
        -- collection run -- never a scan over existing windows/tabs, so a
        -- personal tab (even one already on YouTube) is never reused or
        -- navigated. Never activated, so it never comes to the foreground.
        set dedicatedWindow to make new window
        set dedicatedWindowId to id of dedicatedWindow
        set URL of (active tab of dedicatedWindow) to postURL

        try
            delay 6

            my verifyDedicatedTabOnTarget(dedicatedWindowId, expectedPostId, "before bootstrap")

            set targetTab to my resolveDedicatedTab(dedicatedWindowId)
            set bootstrapped to execute targetTab javascript BOOTSTRAP_PLACEHOLDER

            if bootstrapped is not "OK" then error bootstrapped

            execute targetTab javascript ("window.__wrgWallClockBudgetMs = " & (wallClockSeconds * 1000) & ";")

            set roundsUsed to 0
            set roundLimitReached to false

            repeat with roundNumber from 1 to maximumRounds
                set roundsUsed to roundNumber
                my verifyDedicatedTabOnTarget(dedicatedWindowId, expectedPostId, "round " & roundNumber)
                set targetTab to my resolveDedicatedTab(dedicatedWindowId)
                set advanced to execute targetTab javascript ADVANCE_PLACEHOLDER
                if advanced is "DONE" then exit repeat
                delay 2
            end repeat

            if roundsUsed is maximumRounds then
                set roundLimitReached to true
                set targetTab to my resolveDedicatedTab(dedicatedWindowId)
                execute targetTab javascript "window.__wrgRoundLimitReached = true;"
            end if

            my verifyDedicatedTabOnTarget(dedicatedWindowId, expectedPostId, "before extraction")
            set targetTab to my resolveDedicatedTab(dedicatedWindowId)
            execute targetTab javascript ("window.__wrgRounds = " & roundsUsed & ";")

            set finalResult to execute targetTab javascript FINALIZE_PLACEHOLDER
            close dedicatedWindow
            return finalResult
        on error errMsg
            try
                close dedicatedWindow
            end try
            error errMsg
        end try
    end tell
end run
'''.replace(
    "BOOTSTRAP_PLACEHOLDER", json.dumps(_POST_COMMENTS_BOOTSTRAP_JS)
).replace(
    "ADVANCE_PLACEHOLDER", json.dumps(_POST_COMMENTS_ADVANCE_JS)
).replace(
    "FINALIZE_PLACEHOLDER", json.dumps(_POST_COMMENTS_FINALIZE_JS)
)


def run_browser_post_comment_collection(
    post_url: str, max_rounds: int, wall_clock_budget_seconds: int
) -> str:
    """Drive the logged-in Brave tab and return its JSON-stringified result.

    Never reads, prints, or stores any cookie, token, or credential -- it
    only asks the already-authenticated tab to report rendered page content.
    """

    timeout = int(max_rounds * 3 + wall_clock_budget_seconds + 120)
    process = subprocess.run(
        ["osascript", "-", post_url, str(max_rounds), str(wall_clock_budget_seconds)],
        input=POST_COMMENTS_APPLESCRIPT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if process.returncode:
        message = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError("YouTube browser comment collection failed: " + message)
    return process.stdout


def parse_browser_comment_payload(
    post_id: str, raw_output: str
) -> PostCommentCollection:
    """Parse the browser's JSON-stringified result into stable evidence.

    This is the fully-specified, fully-tested contract between this module
    and its own injected JavaScript -- it does not depend on guessing any
    YouTube-internal API schema. This is also the single place completion
    status is decided for one post.
    """

    try:
        payload = json.loads(raw_output)
        if not isinstance(payload, dict):
            raise ValueError("not a JSON object")
    except (json.JSONDecodeError, ValueError):
        return PostCommentCollection(
            post_id=post_id,
            post_url=f"https://www.youtube.com/post/{post_id}",
            comments=(),
            provisional_records=(),
            raw_pages=(RawPageRecord("browser_snapshot", None, None, {"raw": raw_output}),),
            counts=_empty_counts(),
            identity_coverage=_empty_identity_coverage(),
            status="incomplete",
            reasons=("malformed_response",),
        )

    post_url = str(payload.get("post_url") or f"https://www.youtube.com/post/{post_id}")
    comments_disabled = bool(payload.get("comments_disabled"))
    comments_unavailable = bool(payload.get("comments_unavailable"))
    comments_panel_found = bool(payload.get("comments_panel_found", False))

    canonical: list[YouTubePostComment] = []
    provisional: list[dict[str, Any]] = []
    seen_canonical_ids: set[str] = set()
    triggered: set[str] = set()

    def _identity_and_text_reasons(raw: dict[str, Any]) -> list[str]:
        comment_id = raw.get("id")
        text = raw.get("text")
        id_basis = str(raw.get("id_basis") or "unknown")
        content_state = raw.get("content_state")

        text_ok = isinstance(text, str) and text.strip() != ""
        id_ok = bool(comment_id) and id_basis in STABLE_ID_BASES

        record_reasons: list[str] = []
        if not id_ok:
            record_reasons.append("unstable_comment_identifier")
        if not text_ok:
            if content_state in {"hidden", "unavailable"}:
                record_reasons.append("hidden_reply_content")
            else:
                record_reasons.append("missing_comment_text")
        return record_reasons

    def _make_canonical(raw: dict[str, Any], *, parent_id: str | None) -> YouTubePostComment:
        return YouTubePostComment(
            comment_id=str(raw["id"]),
            parent_id=parent_id,
            order=int(raw.get("order", 0)),
            text=raw.get("text"),
            author=raw.get("author"),
            author_id=raw.get("author_id"),
            author_url=raw.get("author_url"),
            published_text=raw.get("published_text"),
            like_count=raw.get("like_count"),
            id_basis=str(raw.get("id_basis") or "unknown"),
        )

    raw_comments = [r for r in (payload.get("comments") or []) if isinstance(r, dict)]

    # Resolve-only pass: determine which top-level comment IDs are stable
    # and canonical-eligible, before classifying or appending anything, so
    # a reply's parent-validity check never depends on encounter order.
    canonical_top_level_ids: set[str] = {
        str(r["id"])
        for r in raw_comments
        if not r.get("parent_id") and not _identity_and_text_reasons(r)
    }

    # Output pass: walk the original encounter order exactly once,
    # classifying and appending each record immediately. This preserves
    # natural thread order (a comment followed by its own replies, then
    # the next comment) instead of grouping all top-level comments ahead
    # of all replies. A reply is only canonical when its own identity/text
    # are valid AND its parent resolved to a stable ID above -- an
    # ordinal/missing/provisional parent is never written into canonical
    # metadata, and the reply stays provisional (not silently dropped)
    # until the parent is stable.
    for raw in raw_comments:
        parent_raw = raw.get("parent_id")
        is_reply = bool(parent_raw)
        record_reasons = _identity_and_text_reasons(raw)

        if is_reply:
            parent_ref = str(parent_raw)
            if parent_ref not in canonical_top_level_ids:
                record_reasons = [*record_reasons, "orphaned_parent_reference"]

        if record_reasons:
            provisional.append({**raw, "unresolved_reasons": record_reasons})
            triggered.update(record_reasons)
            continue

        comment_id = str(raw["id"])
        if comment_id in seen_canonical_ids:
            continue
        seen_canonical_ids.add(comment_id)
        if _is_deleted_placeholder(raw.get("text")):
            triggered.add("deleted_comment_placeholder_present")
        canonical.append(
            _make_canonical(raw, parent_id=(str(parent_raw) if is_reply else None))
        )

    reasons: list[str] = []
    if comments_disabled:
        reasons.append("comments_disabled")
    if comments_unavailable:
        reasons.append("comments_unavailable")
    if not (comments_disabled or comments_unavailable) and not comments_panel_found:
        reasons.append("missing_comments_panel")
    if payload.get("round_limit_reached"):
        reasons.append("round_limit_reached")
    if payload.get("wall_clock_exceeded"):
        reasons.append("wall_clock_exceeded")
    # top_level_stalled (idle-stability) is intentionally NOT surfaced as a
    # reason -- it is the genuine, progress-based exhaustion signal, not a
    # blocker. See the _BLOCKING_REASONS note above.
    if payload.get("reply_expansion_incomplete"):
        reasons.append("incomplete_reply_expansion")
    for extra in (
        "unstable_comment_identifier",
        "missing_comment_text",
        "hidden_reply_content",
        "orphaned_parent_reference",
        "deleted_comment_placeholder_present",
    ):
        if extra in triggered:
            reasons.append(extra)

    total_count = len(canonical)
    visible_comment_count = payload.get("visible_comment_count")
    basis = _visible_count_basis(visible_comment_count)
    count_match = _compare_visible_count(visible_comment_count, total_count, basis)
    if basis == "verified" and count_match == "false":
        reasons.append("visible_count_mismatch")
    if total_count == 0 and not (comments_disabled or comments_unavailable):
        reasons.append("unverified_zero_comments")

    counts = PostCommentCounts(
        visible_comment_count=visible_comment_count,
        visible_count_basis=basis,
        top_level_count=sum(1 for c in canonical if c.parent_id is None),
        reply_count=sum(1 for c in canonical if c.parent_id is not None),
        total_count=total_count,
        count_match=count_match,
    )
    identity_coverage = IdentityCoverage(
        stable_id_count=len(canonical),
        unresolved_provisional_count=len(provisional),
        stable_id_coverage_complete=(len(provisional) == 0),
    )

    return PostCommentCollection(
        post_id=post_id,
        post_url=post_url,
        comments=tuple(canonical),
        provisional_records=tuple(provisional),
        raw_pages=(RawPageRecord("browser_snapshot", None, None, payload),),
        counts=counts,
        identity_coverage=identity_coverage,
        status=_resolve_status(reasons),
        reasons=tuple(reasons),
        post_title=payload.get("post_title"),
        post_author=payload.get("post_author"),
        post_author_id=payload.get("post_author_id"),
        post_author_url=payload.get("post_author_url"),
    )


# --------------------------------------------------------------------------
# Handle -> stable channel-ID resolution. Confirmed live: no comment thread
# exposes a /channel/UC... href or accessible bound author data, but
# navigating the same authenticated tab to a handle's own page reliably
# exposes YouTube's own canonical channel ID for it. The handle text is
# never trusted by itself -- it is only used as a lookup key, and the
# result is compared exactly against TARGET_AUTHOR_CHANNEL_ID like any
# other author_id source.
# --------------------------------------------------------------------------


_RESOLVE_HANDLE_JS = r"""
(() => {
  const fromHref = (href) => {
    if (!href) return null;
    const match = href.match(/\/channel\/(UC[\w-]{10,})/);
    return match ? match[1] : null;
  };
  const canonical = document.querySelector('link[rel="canonical"]');
  const fromCanonical = canonical ? fromHref(canonical.href) : null;
  if (fromCanonical) return fromCanonical;

  const ogUrl = document.querySelector('meta[property="og:url"]');
  const fromOgUrl = ogUrl ? fromHref(ogUrl.content) : null;
  if (fromOgUrl) return fromOgUrl;

  const identifier = document.querySelector('meta[itemprop="identifier"]');
  if (identifier && /^UC[\w-]{10,}$/.test(identifier.content)) return identifier.content;

  return '';
})();
"""

RESOLVE_HANDLE_APPLESCRIPT = r'''
on run argv
    set handleURL to item 1 of argv

    if application "Brave Browser" is not running then error "BRAVE NOT RUNNING"

    tell application "Brave Browser"
        -- A brand-new, isolated window dedicated to this one resolution --
        -- never a scan over existing windows/tabs, and never activated, so
        -- a personal tab is never reused/navigated and nothing comes to
        -- the foreground.
        set dedicatedWindow to make new window
        set dedicatedTab to active tab of dedicatedWindow
        set URL of dedicatedTab to handleURL

        try
            delay 5

            set currentURL to URL of dedicatedTab
            if currentURL does not start with "https://www.youtube.com/" and currentURL does not start with "https://youtube.com/" then
                error "Brave tab navigated away from YouTube during handle resolution: now at " & currentURL
            end if

            set result to execute dedicatedTab javascript RESOLVE_JS_PLACEHOLDER
            close dedicatedWindow
            return result
        on error errMsg
            try
                close dedicatedWindow
            end try
            error errMsg
        end try
    end tell
end run
'''.replace("RESOLVE_JS_PLACEHOLDER", json.dumps(_RESOLVE_HANDLE_JS))


def run_browser_handle_resolution(handle_url: str) -> str:
    """Navigate the authenticated browser to a handle's own page and return
    the raw, stripped resolution text (a channel ID, or empty)."""

    process = subprocess.run(
        ["osascript", "-", handle_url],
        input=RESOLVE_HANDLE_APPLESCRIPT,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    if process.returncode:
        message = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError("YouTube handle resolution failed: " + message)
    return process.stdout.strip()


def _normalize_handle(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    handle = value.strip()
    if not handle.startswith("@"):
        handle = "@" + handle
    return handle


def resolve_channel_id_via_handle(
    handle: str, *, runner: Callable[[str], str] = run_browser_handle_resolution
) -> str | None:
    """Resolve a handle to its stable channel ID via the same authenticated
    browser session, using only YouTube's own canonical/og:url/identifier
    metadata on that handle's own page -- never the handle text itself."""

    normalized = _normalize_handle(handle)
    if normalized is None:
        return None
    handle_url = f"https://www.youtube.com/{normalized}"
    try:
        result = runner(handle_url)
    except Exception:  # noqa: BLE001 - resolution failure just means "unresolved"
        return None
    result = (result or "").strip()
    if re.fullmatch(r"UC[\w-]{10,}", result):
        return result
    return None


def _resolve_target_author_ids(
    comments: tuple[YouTubePostComment, ...],
    *,
    resolve_handle: Callable[[str], str | None],
) -> tuple[YouTubePostComment, ...]:
    """Fill in author_id for canonical comments whose handle exactly matches
    the known target handle but whose author_id is still missing, via one
    live resolution per unique handle text (cached within this call). Every
    other comment is returned unchanged. The final identity check remains
    an exact comparison against TARGET_AUTHOR_CHANNEL_ID regardless of how
    author_id was populated.
    """

    cache: dict[str, str | None] = {}
    resolved: list[YouTubePostComment] = []
    changed = False

    target_handle = _normalize_handle(TARGET_AUTHOR_HANDLE)
    for comment in comments:
        normalized_author = _normalize_handle(comment.author)
        if (
            comment.author_id is None
            and normalized_author is not None
            and normalized_author.lower() == (target_handle or "").lower()
        ):
            if comment.author not in cache:
                cache[comment.author] = resolve_handle(comment.author)
            resolved_id = cache[comment.author]
            if resolved_id:
                comment = replace(comment, author_id=resolved_id)
                changed = True
        resolved.append(comment)

    return tuple(resolved) if changed else comments


def collect_post_comments_via_browser(
    post_id: str,
    max_continuation_fetches: int | None = None,
    *,
    wall_clock_budget_seconds: int = DEFAULT_WALL_CLOCK_BUDGET_SECONDS,
    runner: Callable[[str, int, int], str] = run_browser_post_comment_collection,
    resolve_handle: Callable[[str], str | None] = resolve_channel_id_via_handle,
) -> PostCommentCollection:
    """Default extractor: authenticated-browser fetch + parse.

    ``max_continuation_fetches`` bounds the number of scroll/expand rounds
    the browser script performs for this post. ``None`` means "no arbitrary
    round cap" -- a practical, documented wall-clock-derived bound is used
    instead of a pseudo-unlimited constant, and either bound being reached
    is reported as ``round_limit_reached``/``wall_clock_exceeded``, which
    always forces INCOMPLETE, never completed.

    After parsing, any canonical comment whose handle exactly matches
    ``TARGET_AUTHOR_HANDLE`` but still lacks an ``author_id`` is resolved via
    ``resolve_handle`` (one live lookup per unique handle text for this
    post) -- see ``_resolve_target_author_ids``.
    """

    post_url = f"https://www.youtube.com/post/{post_id}"
    max_rounds = (
        max_continuation_fetches
        if max_continuation_fetches is not None
        else _PRACTICAL_MAX_ROUNDS
    )
    try:
        raw_output = runner(post_url, max_rounds, wall_clock_budget_seconds)
    except Exception as exc:  # noqa: BLE001 - surfaced as a reason, not raised
        return PostCommentCollection(
            post_id=post_id,
            post_url=post_url,
            comments=(),
            provisional_records=(),
            raw_pages=(),
            counts=_empty_counts(),
            identity_coverage=_empty_identity_coverage(),
            status="failed",
            reasons=(f"fetch_failure:{type(exc).__name__}: {exc}",),
        )
    collection = parse_browser_comment_payload(post_id, raw_output)
    resolved_comments = _resolve_target_author_ids(
        collection.comments, resolve_handle=resolve_handle
    )
    if resolved_comments is collection.comments:
        return collection
    return replace(collection, comments=resolved_comments)


# --------------------------------------------------------------------------
# Authenticated Community-post feed refresh (mirrors the proven Instagram
# scroll-until-stable discovery pattern)
# --------------------------------------------------------------------------


POST_FEED_APPLESCRIPT = r'''
on run argv
    set channelURL to item 1 of argv
    set maximumScrolls to (item 2 of argv) as integer
    set pauseSeconds to (item 3 of argv) as real
    set stableLimit to (item 4 of argv) as integer
    set snapshots to {}
    set previousHeight to -1
    set stableRounds to 0
    set stabilized to false

    if application "Brave Browser" is not running then error "BRAVE NOT RUNNING"

    tell application "Brave Browser"
        -- A brand-new, isolated window dedicated to this one discovery run
        -- -- never a scan over existing windows/tabs, and never activated,
        -- so a personal tab is never reused/navigated and nothing comes to
        -- the foreground.
        set targetWindow to make new window
        set targetTab to active tab of targetWindow
        set URL of targetTab to channelURL

        try
            delay 6

            set currentURL to URL of targetTab
            if currentURL does not start with "https://www.youtube.com/" and currentURL does not start with "https://youtube.com/" then
                error "Brave tab navigated away from YouTube during Community-post discovery: now at " & currentURL
            end if

            repeat with roundNumber from 1 to maximumScrolls
                set payload to execute targetTab javascript "
                    JSON.stringify(
                        Array.from(document.querySelectorAll('a[href*=\"/post/\"]'))
                            .map(a => a.href)
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
                    set stabilized to true
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

            close targetWindow
        on error errMsg
            try
                close targetWindow
            end try
            error errMsg
        end try
    end tell

    set oldDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set joinedSnapshots to snapshots as text
    set AppleScript's text item delimiters to oldDelimiters

    if stabilized then
        return joinedSnapshots & linefeed & "__WRG_STABILIZED__"
    else
        return joinedSnapshots & linefeed & "__WRG_SCROLL_LIMIT_REACHED__"
    end if
end run
'''


def run_browser_post_feed_discovery(
    channel_url: str,
    max_scrolls: int,
    delay: float,
    stable_rounds: int,
) -> str:
    """Run logged-in Brave discovery of Community-post permalinks."""

    timeout = int(max_scrolls * (delay + 1.0) + 120)
    process = subprocess.run(
        ["osascript", "-", channel_url, str(max_scrolls), str(delay), str(stable_rounds)],
        input=POST_FEED_APPLESCRIPT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if process.returncode:
        message = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError("YouTube Community-post feed discovery failed: " + message)
    return process.stdout


def parse_browser_post_feed_payload(output: str) -> PostFeedRefreshResult:
    """Extract stable post IDs and stabilization status from scroll output."""

    discovered: set[str] = set()
    stabilized = False
    saw_marker = False

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if line == "__WRG_STABILIZED__":
            stabilized = True
            saw_marker = True
            continue
        if line == "__WRG_SCROLL_LIMIT_REACHED__":
            stabilized = False
            saw_marker = True
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
            post_id = resolve_post_id(value)
            if post_id and "/post/" not in post_id:
                discovered.add(post_id)

    reasons = () if stabilized else ("scroll_limit_reached",)
    if not saw_marker:
        # No stabilization marker at all: treat conservatively as unstabilized.
        stabilized = False
        reasons = ("scroll_limit_reached",)

    return PostFeedRefreshResult(
        discovered_post_ids=frozenset(discovered), stabilized=stabilized, reasons=reasons
    )


def refresh_post_feed_via_browser(
    channel_url: str,
    posts_checkpoint_path: str | Path,
    *,
    repository: WarrigalRepository | None = None,
    object_store: ObjectStore | None = None,
    job_id: str | None = None,
    node_id: str | None = None,
    batch_id: str | None = None,
    collection_id: str | None = None,
    max_scrolls: int = 2000,
    delay: float = 1.5,
    stable_rounds: int = 12,
    runner: Callable[[str, int, float, int], str] = run_browser_post_feed_discovery,
) -> PostFeedRefreshResult:
    """Discover every currently-visible Community post through the
    authenticated browser and merge the IDs into the existing post
    checkpoint, so a campaign never relies solely on a stale, pre-existing
    checkpoint. Accepts (and ignores) the repository/object_store/job
    identity keywords so it satisfies the same ``PostFeedRefresher``
    signature as any future acquisition-backed refresher. Reports whether
    discovery stabilized or hit its scroll limit.
    """

    output = runner(channel_url, max_scrolls, delay, stable_rounds)
    result = parse_browser_post_feed_payload(output)

    store = YouTubePostCheckpointStore(posts_checkpoint_path)
    try:
        existing = store.load(channel_url)
    except ValueError:
        existing = set()
    store.save(channel_url, existing | set(result.discovered_post_ids))
    return result


# --------------------------------------------------------------------------
# Checkpoint: per-post collected comment/reply IDs plus completion status.
# Only canonical (stable-ID, non-empty-text) comments are ever passed in.
# --------------------------------------------------------------------------


class YouTubePostCommentCheckpointStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"posts": {}}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload.setdefault("posts", {})
        return payload

    def load_comment_ids(self, post_id: str) -> set[str]:
        entry = self._read()["posts"].get(post_id, {})
        return {str(v) for v in entry.get("comment_ids", [])}

    def load_status(self, post_id: str) -> dict[str, Any] | None:
        entry = self._read()["posts"].get(post_id)
        if entry is None:
            return None
        return {"status": entry.get("status"), "reasons": entry.get("reasons", [])}

    def save(
        self,
        post_id: str,
        *,
        comment_ids: set[str],
        status: str,
        reasons: list[str] | tuple[str, ...],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._read()
        payload["posts"][post_id] = {
            "comment_ids": sorted(comment_ids),
            "status": status,
            "reasons": list(reasons),
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)


# --------------------------------------------------------------------------
# Ingestion. Only ``collection.comments`` (already stable-ID, non-empty-text
# only) is ever checkpointed, indexed, or permalinked.
# --------------------------------------------------------------------------


def ingest_youtube_post_comments(
    post_id: str,
    *,
    checkpoint_path: str | Path,
    max_continuation_fetches: int | None = None,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    extractor: PostCommentExtractor = collect_post_comments_via_browser,
) -> YouTubePostCommentIngestionResult:
    """Preserve a raw comment-thread snapshot and index every canonical
    comment/reply.

    Every canonical top-level comment and reply is indexed (not only ones
    authored by Tom); each passage's metadata records whether its author's
    stable channel ID matches ``TARGET_AUTHOR_CHANNEL_ID`` exactly. No
    handle-text fallback is used, so a spoofed display name is never
    treated as confirmed authorship. No reconciliation fields are written
    here. Status/reasons/counts are consumed as decided by the extractor
    (``parse_browser_comment_payload`` is the single source of truth) --
    this function does not re-derive completion logic.
    """

    collection = extractor(post_id, max_continuation_fetches)
    comments = list(collection.comments)
    status = collection.status
    reasons = list(collection.reasons)

    snapshot = {
        "schema": "warrigal.youtube-post-comments.v4",
        "post": {
            "id": post_id,
            "url": collection.post_url,
            "title": collection.post_title,
            "author": collection.post_author,
            "author_id": collection.post_author_id,
            "author_url": collection.post_author_url,
            "visible_comment_count": collection.counts.visible_comment_count,
        },
        "status": status,
        "reasons": reasons,
        "comments": [asdict(c) for c in comments],
        "provisional_records": list(collection.provisional_records),
        "identity_coverage": asdict(collection.identity_coverage),
        "raw_pages": [asdict(p) for p in collection.raw_pages],
    }

    offending_key = _contains_credential_shaped_key(snapshot)
    if offending_key is not None:
        raise ValueError(
            f"Refusing to persist snapshot containing credential-shaped key: {offending_key!r}"
        )

    data = (
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    source = Source(
        source_type="youtube_post_comments",
        locator=collection.post_url,
        final_locator=collection.post_url,
        title=f"Post comments: {post_id}",
        metadata={"post_id": post_id, "post_url": collection.post_url},
    )
    repository.save_source(source)
    acquisition = AcquisitionService(repository, object_store).acquire_bytes(
        data=data,
        source_id=source.source_id,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        method="youtube_post_comments_browser",
        mime_type="application/json",
        original_filename=f"{post_id}.post-comments.json",
        collection_id=collection_id,
        metadata={
            "post_id": post_id,
            "post_url": collection.post_url,
            "status": status,
            "reasons": reasons,
            "visible_comment_count": collection.counts.visible_comment_count,
            "collected_count": collection.counts.total_count,
        },
    )

    checkpoint = YouTubePostCommentCheckpointStore(checkpoint_path)
    completed_ids = checkpoint.load_comment_ids(post_id)
    new_comments = [c for c in comments if c.comment_id not in completed_ids]

    existing_rows = repository.get_passages_for_object(acquisition.object_id)
    next_index = max(
        (int(row["passage_index"]) + 1 for row in existing_rows), default=0
    )

    indexed = 0
    for comment in new_comments:
        is_target_author = comment.author_id == TARGET_AUTHOR_CHANNEL_ID
        repository.save_passage(
            Passage(
                object_id=acquisition.object_id,
                acquisition_id=acquisition.acquisition_id,
                passage_index=next_index,
                text=comment.text,
                source_url=f"{collection.post_url}?lc={comment.comment_id}",
                source_title=f"Post comments: {post_id}",
                metadata={
                    **asdict(comment),
                    "post_id": post_id,
                    "post_url": collection.post_url,
                    "content_type": "youtube_post_comment",
                    "is_reply": comment.parent_id is not None,
                    "is_target_author": is_target_author,
                    "match_basis": "author_id" if is_target_author else None,
                },
            )
        )
        completed_ids.add(comment.comment_id)
        next_index += 1
        indexed += 1

    checkpoint.save(post_id, comment_ids=completed_ids, status=status, reasons=reasons)

    target_author_comment_count = sum(
        1 for c in comments if c.author_id == TARGET_AUTHOR_CHANNEL_ID
    )

    return YouTubePostCommentIngestionResult(
        post_id=post_id,
        post_url=collection.post_url,
        object_id=acquisition.object_id,
        acquisition_id=acquisition.acquisition_id,
        sha256=acquisition.sha256,
        counts=collection.counts,
        identity_coverage=collection.identity_coverage,
        collected_count=collection.counts.total_count,
        new_count=len(new_comments),
        indexed_count=indexed,
        target_author_comment_count=target_author_comment_count,
        deduplicated=acquisition.deduplicated,
        status=status,
        reasons=tuple(reasons),
    )


# --------------------------------------------------------------------------
# Campaign
# --------------------------------------------------------------------------


def plan_post_comment_campaign(
    channel_url: str, *, posts_checkpoint_path: str | Path
) -> list[str]:
    """Return the currently checkpointed post IDs, read-only, no refresh."""

    return sorted(YouTubePostCheckpointStore(posts_checkpoint_path).load(channel_url))


def run_post_comment_campaign(
    channel_url: str,
    *,
    posts_checkpoint_path: str | Path,
    comments_checkpoint_path: str | Path,
    max_continuation_fetches: int | None = None,
    repository: WarrigalRepository,
    object_store: ObjectStore,
    job_id: str,
    node_id: str,
    batch_id: str,
    collection_id: str,
    skip_completed: bool = False,
    post_feed_refresher: PostFeedRefresher = refresh_post_feed_via_browser,
    comment_extractor: PostCommentExtractor = collect_post_comments_via_browser,
) -> PostCommentCampaignResult:
    """Refresh the post feed, then attempt every currently-known post.

    By default, previously completed posts are revisited too (so newly
    added comments/replies are discovered); pass ``skip_completed=True``
    to opt into skipping them. A post's own checkpoint dedup means
    revisiting never duplicates a passage.
    """

    posts_store = YouTubePostCheckpointStore(posts_checkpoint_path)
    try:
        known_before = posts_store.load(channel_url)
    except ValueError:
        known_before = set()

    feed_result = post_feed_refresher(
        channel_url,
        posts_checkpoint_path,
        repository=repository,
        object_store=object_store,
        job_id=job_id,
        node_id=node_id,
        batch_id=batch_id,
        collection_id=collection_id,
    )

    current_posts = set(posts_store.load(channel_url))
    newly_discovered = sorted(current_posts - known_before)

    comments_store = YouTubePostCommentCheckpointStore(comments_checkpoint_path)
    attempted: list[str] = []
    for post_id in sorted(current_posts):
        if skip_completed:
            status_entry = comments_store.load_status(post_id)
            if status_entry is not None and status_entry.get("status") == "completed":
                continue
        attempted.append(post_id)

    items: list[PostCommentCampaignItemResult] = []
    for post_id in attempted:
        try:
            result = ingest_youtube_post_comments(
                post_id,
                checkpoint_path=comments_checkpoint_path,
                max_continuation_fetches=max_continuation_fetches,
                repository=repository,
                object_store=object_store,
                job_id=job_id,
                node_id=node_id,
                batch_id=batch_id,
                collection_id=collection_id,
                extractor=comment_extractor,
            )
            items.append(
                PostCommentCampaignItemResult(
                    post_id=post_id,
                    status=result.status,
                    reasons=result.reasons,
                    collected_count=result.collected_count,
                    new_count=result.new_count,
                    target_author_comment_count=result.target_author_comment_count,
                )
            )
        except Exception as exc:  # noqa: BLE001 - isolate one post's failure
            items.append(
                PostCommentCampaignItemResult(
                    post_id=post_id,
                    status="failed",
                    reasons=(f"fetch_failure:{type(exc).__name__}: {exc}",),
                )
            )

    return PostCommentCampaignResult(
        known_before_refresh=tuple(sorted(known_before)),
        newly_discovered=tuple(newly_discovered),
        attempted=tuple(attempted),
        items=tuple(items),
        feed_coverage_status="complete" if feed_result.stabilized else "incomplete",
        feed_coverage_reasons=feed_result.reasons,
    )
