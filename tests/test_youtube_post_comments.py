from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from warrigal.acquisition.youtube_post_comments import (
    TARGET_AUTHOR_CHANNEL_ID,
    TARGET_AUTHOR_HANDLE,
    PostCommentCollection,
    PostFeedRefreshResult,
    RawPageRecord,
    YouTubePostCommentCheckpointStore,
    _contains_credential_shaped_key,
    _empty_counts,
    _empty_identity_coverage,
    _normalize_handle,
    _resolve_target_author_ids,
    collect_post_comments_via_browser,
    ingest_youtube_post_comments,
    parse_browser_comment_payload,
    parse_browser_post_feed_payload,
    plan_post_comment_campaign,
    refresh_post_feed_via_browser,
    resolve_channel_id_via_handle,
    resolve_post_id,
    run_post_comment_campaign,
)
import warrigal.acquisition.youtube_post_comments as ypc_module
from warrigal.acquisition.youtube_posts import YouTubePostCheckpointStore


CHANNEL_URL = "https://www.youtube.com/@TFJ7/posts"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def comment_payload(
    comment_id: str,
    text: str,
    *,
    parent_id: str | None = None,
    order: int = 0,
    author: str = "@SomeoneElse",
    author_id: str = "UC-OTHER",
    id_basis: str = "polymer_data",
    content_state: str | None = None,
) -> dict:
    return {
        "id": comment_id,
        "id_basis": id_basis,
        "parent_id": parent_id,
        "order": order,
        "text": text,
        "content_state": content_state,
        "author": author,
        "author_id": author_id,
        "author_url": f"https://www.youtube.com/{author}",
        "published_text": "2 weeks ago",
        "like_count": "4",
    }


def browser_payload(
    *,
    post_id: str = "P1",
    comments: list[dict] | None = None,
    comments_panel_found: bool = True,
    comments_disabled: bool = False,
    comments_unavailable: bool = False,
    visible_comment_count: str | None = None,
    round_limit_reached: bool = False,
    wall_clock_exceeded: bool = False,
    top_level_stalled: bool = True,
    reply_expansion_incomplete: bool = False,
    rounds_used: int = 4,
    post_title: str | None = "Manuscript excerpt",
    post_author: str | None = "@TFJ7",
    post_author_id: str | None = TARGET_AUTHOR_CHANNEL_ID,
) -> dict:
    return {
        "post_id": post_id,
        "post_url": f"https://www.youtube.com/post/{post_id}",
        "post_title": post_title,
        "post_author": post_author,
        "post_author_id": post_author_id,
        "post_author_url": f"https://www.youtube.com/{post_author}" if post_author else None,
        "comments_panel_found": comments_panel_found,
        "comments_disabled": comments_disabled,
        "comments_unavailable": comments_unavailable,
        "visible_comment_count": visible_comment_count,
        "rounds_used": rounds_used,
        "round_limit_reached": round_limit_reached,
        "wall_clock_exceeded": wall_clock_exceeded,
        "top_level_stalled": top_level_stalled,
        "reply_expansion_incomplete": reply_expansion_incomplete,
        "comments": comments or [],
    }


def _mock_acquisition(object_id: str, acquisition_id: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        object_id=object_id, acquisition_id=acquisition_id, sha256="a" * 64, deduplicated=False
    )


# ---------------------------------------------------------------------------
# Blocker 1: ordinal fallback identities never become canonical
# ---------------------------------------------------------------------------


class OrdinalFallbackTests(unittest.TestCase):
    def test_ordinal_fallback_record_is_provisional_not_canonical(self):
        payload = browser_payload(
            comments=[comment_payload("ordinal-0", "no stable id", id_basis="ordinal_fallback")]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.comments, ())
        self.assertEqual(len(result.provisional_records), 1)
        self.assertEqual(result.provisional_records[0]["id"], "ordinal-0")

    def test_unstable_identifier_forces_incomplete(self):
        payload = browser_payload(
            comments=[comment_payload("ordinal-0", "text", id_basis="ordinal_fallback")]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "incomplete")
        self.assertIn("unstable_comment_identifier", result.reasons)

    def test_raw_fallback_evidence_is_retained_verbatim(self):
        payload = browser_payload(
            comments=[
                comment_payload(
                    "ordinal-0", "irreplaceable evidence text", id_basis="ordinal_fallback"
                )
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(
            result.provisional_records[0]["text"], "irreplaceable evidence text"
        )
        self.assertIn("unresolved_reasons", result.provisional_records[0])

    def test_later_stable_comment_at_same_ordinal_position_is_not_skipped(self):
        # Two records both at order=0 (same visual/ordinal position): one
        # an unresolved fallback, the other a genuinely stable comment with
        # a different real ID. The stable one must not be blocked.
        payload = browser_payload(
            comments=[
                comment_payload("ordinal-0", "fallback text", order=0, id_basis="ordinal_fallback"),
                comment_payload("Ugx-REAL-1", "real stable comment", order=0, id_basis="polymer_data"),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(len(result.comments), 1)
        self.assertEqual(result.comments[0].comment_id, "Ugx-REAL-1")

    def test_identity_coverage_counts_are_reported(self):
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-A", "stable one"),
                comment_payload("ordinal-1", "unstable one", id_basis="ordinal_fallback"),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.identity_coverage.stable_id_count, 1)
        self.assertEqual(result.identity_coverage.unresolved_provisional_count, 1)
        self.assertFalse(result.identity_coverage.stable_id_coverage_complete)

    def test_full_stable_coverage_is_reported_complete(self):
        payload = browser_payload(comments=[comment_payload("Ugx-A", "stable")])

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertTrue(result.identity_coverage.stable_id_coverage_complete)

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_ordinal_fallback_never_reaches_checkpoint_passage_or_permalink(self, service):
        service.return_value.acquire_bytes.return_value = _mock_acquisition("O1", "A1")
        repository = Mock()
        repository.get_passages_for_object.return_value = []
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-STABLE", "stable comment"),
                comment_payload("ordinal-1", "fallback comment", id_basis="ordinal_fallback"),
            ]
        )

        def extractor(post_id, max_continuation_fetches):
            return parse_browser_comment_payload(post_id, json.dumps(payload))

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "c.json"
            ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=extractor,
            )

            saved = [c.args[0] for c in repository.save_passage.call_args_list]
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].metadata["comment_id"], "Ugx-STABLE")
            self.assertNotIn("ordinal-1?lc=", saved[0].source_url)
            self.assertNotIn("ordinal-1", saved[0].source_url)

            store = YouTubePostCommentCheckpointStore(checkpoint)
            self.assertEqual(store.load_comment_ids("P1"), {"Ugx-STABLE"})


# ---------------------------------------------------------------------------
# Nora's data-integrity finding: a reply must not become canonical when its
# parent top-level comment never resolved to a stable ID.
# ---------------------------------------------------------------------------


class OrphanedParentReferenceTests(unittest.TestCase):
    def test_stable_reply_with_unstable_parent_remains_provisional(self):
        payload = browser_payload(
            comments=[
                comment_payload("ordinal-0", "unresolved top-level text", id_basis="ordinal_fallback"),
                comment_payload(
                    "Ugx-REPLY-STABLE", "a perfectly good reply",
                    parent_id="ordinal-0", id_basis="polymer_data",
                ),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        reply_ids = {c.comment_id for c in result.comments}
        self.assertNotIn("Ugx-REPLY-STABLE", reply_ids)
        provisional_ids = {r["id"] for r in result.provisional_records}
        self.assertIn("Ugx-REPLY-STABLE", provisional_ids)

    def test_orphaned_parent_reference_forces_incomplete(self):
        payload = browser_payload(
            comments=[
                comment_payload("ordinal-0", "unresolved parent", id_basis="ordinal_fallback"),
                comment_payload(
                    "Ugx-REPLY-STABLE", "a reply", parent_id="ordinal-0", id_basis="polymer_data",
                ),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "incomplete")
        self.assertIn("orphaned_parent_reference", result.reasons)
        reply_record = next(
            r for r in result.provisional_records if r["id"] == "Ugx-REPLY-STABLE"
        )
        self.assertIn("orphaned_parent_reference", reply_record["unresolved_reasons"])

    def test_raw_provenance_retains_the_orphaned_reply_observation(self):
        payload = browser_payload(
            comments=[
                comment_payload("ordinal-0", "unresolved parent", id_basis="ordinal_fallback"),
                comment_payload(
                    "Ugx-REPLY-STABLE", "irreplaceable reply evidence",
                    parent_id="ordinal-0", id_basis="polymer_data",
                ),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        reply_record = next(
            r for r in result.provisional_records if r["id"] == "Ugx-REPLY-STABLE"
        )
        self.assertEqual(reply_record["text"], "irreplaceable reply evidence")
        self.assertEqual(reply_record["parent_id"], "ordinal-0")

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_orphaned_reply_creates_no_passage_checkpoint_or_permalink(self, service):
        service.return_value.acquire_bytes.return_value = _mock_acquisition("O1", "A1")
        repository = Mock()
        repository.get_passages_for_object.return_value = []
        payload = browser_payload(
            comments=[
                comment_payload("ordinal-0", "unresolved parent", id_basis="ordinal_fallback"),
                comment_payload(
                    "Ugx-REPLY-STABLE", "a reply", parent_id="ordinal-0", id_basis="polymer_data",
                ),
            ]
        )

        def extractor(post_id, max_continuation_fetches):
            return parse_browser_comment_payload(post_id, json.dumps(payload))

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "c.json"
            ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=extractor,
            )

            repository.save_passage.assert_not_called()
            store = YouTubePostCommentCheckpointStore(checkpoint)
            self.assertEqual(store.load_comment_ids("P1"), set())

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_rerun_with_resolved_parent_ingests_both_exactly_once_with_correct_linkage(
        self, service
    ):
        service.return_value.acquire_bytes.side_effect = [
            _mock_acquisition("O1", "A1"),
            _mock_acquisition("O2", "A2"),
        ]
        repository = Mock()
        repository.get_passages_for_object.return_value = []

        first_payload = browser_payload(
            comments=[
                comment_payload("ordinal-0", "unresolved parent", id_basis="ordinal_fallback"),
                comment_payload(
                    "Ugx-REPLY-STABLE", "a reply", parent_id="ordinal-0", id_basis="polymer_data",
                ),
            ]
        )
        second_payload = browser_payload(
            comments=[
                comment_payload("Ugx-PARENT-STABLE", "now-stable parent", id_basis="polymer_data"),
                comment_payload(
                    "Ugx-REPLY-STABLE", "a reply",
                    parent_id="Ugx-PARENT-STABLE", id_basis="polymer_data",
                ),
            ]
        )

        def first_extractor(post_id, max_continuation_fetches):
            return parse_browser_comment_payload(post_id, json.dumps(first_payload))

        def second_extractor(post_id, max_continuation_fetches):
            return parse_browser_comment_payload(post_id, json.dumps(second_payload))

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "c.json"
            first = ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=first_extractor,
            )
            self.assertEqual(first.new_count, 0)
            repository.save_passage.reset_mock()

            second = ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=second_extractor,
            )

            self.assertEqual(second.new_count, 2)
            saved = [c.args[0] for c in repository.save_passage.call_args_list]
            self.assertEqual(len(saved), 2)
            reply_passage = next(p for p in saved if p.metadata["comment_id"] == "Ugx-REPLY-STABLE")
            self.assertEqual(reply_passage.metadata["parent_id"], "Ugx-PARENT-STABLE")
            parent_passage = next(p for p in saved if p.metadata["comment_id"] == "Ugx-PARENT-STABLE")
            self.assertIsNone(parent_passage.metadata["parent_id"])

            store = YouTubePostCommentCheckpointStore(checkpoint)
            self.assertEqual(
                store.load_comment_ids("P1"), {"Ugx-PARENT-STABLE", "Ugx-REPLY-STABLE"}
            )

    def test_ordinary_stable_parent_and_reply_thread_is_unaffected(self):
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-A", "Top text"),
                comment_payload("Ugx-R1", "A reply", parent_id="Ugx-A", order=0),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(len(result.comments), 2)
        self.assertEqual(result.provisional_records, ())
        self.assertEqual(result.status, "completed")
        reply = next(c for c in result.comments if c.comment_id == "Ugx-R1")
        self.assertEqual(reply.parent_id, "Ugx-A")


# ---------------------------------------------------------------------------
# Output-order regression fix: canonical/provisional records must appear in
# their original encounter/thread order, not grouped by type.
# ---------------------------------------------------------------------------


class EncounterOrderTests(unittest.TestCase):
    def test_two_top_level_threads_with_replies_retain_thread_interleaved_order(self):
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-TOP-1", "Top level comment 1"),
                comment_payload("Ugx-REPLY-1A", "Reply 1a", parent_id="Ugx-TOP-1"),
                comment_payload("Ugx-TOP-2", "Top level comment 2", order=1),
                comment_payload("Ugx-REPLY-2A", "Reply 2a", parent_id="Ugx-TOP-2"),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(
            [c.comment_id for c in result.comments],
            ["Ugx-TOP-1", "Ugx-REPLY-1A", "Ugx-TOP-2", "Ugx-REPLY-2A"],
        )

    def test_each_records_explicit_order_value_and_parent_linkage_preserved(self):
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-TOP-1", "Top level comment 1", order=0),
                comment_payload("Ugx-REPLY-1A", "Reply 1a", parent_id="Ugx-TOP-1", order=0),
                comment_payload("Ugx-TOP-2", "Top level comment 2", order=1),
                comment_payload("Ugx-REPLY-2A", "Reply 2a", parent_id="Ugx-TOP-2", order=0),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        by_id = {c.comment_id: c for c in result.comments}
        self.assertEqual(by_id["Ugx-TOP-1"].order, 0)
        self.assertEqual(by_id["Ugx-TOP-2"].order, 1)
        self.assertEqual(by_id["Ugx-REPLY-1A"].parent_id, "Ugx-TOP-1")
        self.assertEqual(by_id["Ugx-REPLY-2A"].parent_id, "Ugx-TOP-2")

    def test_orphaned_parent_protection_still_works_amid_interleaved_threads(self):
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-TOP-1", "Top level comment 1"),
                comment_payload("Ugx-REPLY-1A", "Reply 1a", parent_id="Ugx-TOP-1"),
                comment_payload("ordinal-2", "unresolved top level 2", id_basis="ordinal_fallback"),
                comment_payload(
                    "Ugx-REPLY-2A-STABLE", "Reply 2a", parent_id="ordinal-2", id_basis="polymer_data"
                ),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(
            [c.comment_id for c in result.comments], ["Ugx-TOP-1", "Ugx-REPLY-1A"]
        )
        provisional_ids = {r["id"] for r in result.provisional_records}
        self.assertEqual(provisional_ids, {"ordinal-2", "Ugx-REPLY-2A-STABLE"})
        self.assertEqual(result.status, "incomplete")
        self.assertIn("orphaned_parent_reference", result.reasons)

    def test_duplicate_id_within_one_payload_does_not_attach_to_wrong_thread(self):
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-TOP-1", "Top level comment 1"),
                comment_payload("Ugx-REPLY-1A", "Reply 1a", parent_id="Ugx-TOP-1"),
                comment_payload("Ugx-TOP-2", "Top level comment 2", order=1),
                # Same ID as an earlier reply, but attached to a different parent.
                comment_payload("Ugx-REPLY-1A", "duplicate id, different thread", parent_id="Ugx-TOP-2"),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        matches = [c for c in result.comments if c.comment_id == "Ugx-REPLY-1A"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].parent_id, "Ugx-TOP-1")
        self.assertEqual(matches[0].text, "Reply 1a")

    def test_separate_parser_calls_do_not_leak_state_across_posts(self):
        payload_a = browser_payload(
            post_id="PA",
            comments=[
                comment_payload("ordinal-0", "unresolved parent", id_basis="ordinal_fallback"),
                comment_payload("Ugx-SHARED-ID", "reply on post A", parent_id="ordinal-0"),
            ],
        )
        payload_b = browser_payload(
            post_id="PB",
            comments=[
                comment_payload("Ugx-SHARED-ID", "unrelated top-level comment on post B"),
            ],
        )

        result_a = parse_browser_comment_payload("PA", json.dumps(payload_a))
        result_b = parse_browser_comment_payload("PB", json.dumps(payload_b))

        self.assertEqual(result_a.comments, ())
        self.assertEqual(len(result_b.comments), 1)
        self.assertEqual(result_b.comments[0].comment_id, "Ugx-SHARED-ID")
        self.assertIsNone(result_b.comments[0].parent_id)
        self.assertEqual(result_b.comments[0].text, "unrelated top-level comment on post B")

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_persisted_snapshot_comments_array_order_matches_encounter_order(self, service):
        captured_snapshots = []

        def capture_acquire_bytes(**kwargs):
            captured_snapshots.append(json.loads(kwargs["data"].decode("utf-8")))
            return _mock_acquisition("O1", "A1")

        service.return_value.acquire_bytes.side_effect = capture_acquire_bytes
        repository = Mock()
        repository.get_passages_for_object.return_value = []
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-TOP-1", "Top level comment 1"),
                comment_payload("Ugx-REPLY-1A", "Reply 1a", parent_id="Ugx-TOP-1"),
                comment_payload("Ugx-TOP-2", "Top level comment 2", order=1),
                comment_payload("Ugx-REPLY-2A", "Reply 2a", parent_id="Ugx-TOP-2"),
            ]
        )

        def extractor(post_id, max_continuation_fetches):
            return parse_browser_comment_payload(post_id, json.dumps(payload))

        with tempfile.TemporaryDirectory() as tmp:
            ingest_youtube_post_comments(
                "P1", checkpoint_path=Path(tmp) / "c.json", repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=extractor,
            )

        self.assertEqual(len(captured_snapshots), 1)
        persisted_ids = [c["comment_id"] for c in captured_snapshots[0]["comments"]]
        self.assertEqual(
            persisted_ids,
            ["Ugx-TOP-1", "Ugx-REPLY-1A", "Ugx-TOP-2", "Ugx-REPLY-2A"],
        )

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_passage_index_order_matches_source_encounter_order(self, service):
        service.return_value.acquire_bytes.return_value = _mock_acquisition("O1", "A1")
        repository = Mock()
        repository.get_passages_for_object.return_value = []
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-TOP-1", "Top level comment 1"),
                comment_payload("Ugx-REPLY-1A", "Reply 1a", parent_id="Ugx-TOP-1"),
                comment_payload("Ugx-TOP-2", "Top level comment 2", order=1),
                comment_payload("Ugx-REPLY-2A", "Reply 2a", parent_id="Ugx-TOP-2"),
            ]
        )

        def extractor(post_id, max_continuation_fetches):
            return parse_browser_comment_payload(post_id, json.dumps(payload))

        with tempfile.TemporaryDirectory() as tmp:
            ingest_youtube_post_comments(
                "P1", checkpoint_path=Path(tmp) / "c.json", repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=extractor,
            )

        saved = [c.args[0] for c in repository.save_passage.call_args_list]
        ordered_ids = [p.metadata["comment_id"] for p in saved]
        self.assertEqual(
            ordered_ids, ["Ugx-TOP-1", "Ugx-REPLY-1A", "Ugx-TOP-2", "Ugx-REPLY-2A"]
        )
        indices = [p.passage_index for p in saved]
        self.assertEqual(indices, sorted(indices))
        self.assertEqual(indices, list(range(len(indices))))

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_rerun_with_resolved_parent_retains_order_and_linkage(self, service):
        service.return_value.acquire_bytes.side_effect = [
            _mock_acquisition("O1", "A1"),
            _mock_acquisition("O2", "A2"),
        ]
        repository = Mock()
        repository.get_passages_for_object.return_value = []

        first_payload = browser_payload(
            comments=[
                comment_payload("Ugx-TOP-1", "Top level comment 1"),
                comment_payload("Ugx-REPLY-1A", "Reply 1a", parent_id="Ugx-TOP-1"),
                comment_payload("ordinal-2", "unresolved parent", id_basis="ordinal_fallback", order=1),
                comment_payload(
                    "Ugx-REPLY-2A", "Reply 2a", parent_id="ordinal-2", id_basis="polymer_data"
                ),
            ]
        )
        second_payload = browser_payload(
            comments=[
                comment_payload("Ugx-TOP-1", "Top level comment 1"),
                comment_payload("Ugx-REPLY-1A", "Reply 1a", parent_id="Ugx-TOP-1"),
                comment_payload("Ugx-TOP-2", "now-stable top level comment 2", order=1),
                comment_payload("Ugx-REPLY-2A", "Reply 2a", parent_id="Ugx-TOP-2"),
            ]
        )

        def first_extractor(post_id, max_continuation_fetches):
            return parse_browser_comment_payload(post_id, json.dumps(first_payload))

        def second_extractor(post_id, max_continuation_fetches):
            return parse_browser_comment_payload(post_id, json.dumps(second_payload))

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "c.json"
            first = ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=first_extractor,
            )
            self.assertEqual(first.new_count, 2)
            repository.save_passage.reset_mock()

            second = ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=second_extractor,
            )

            self.assertEqual(second.new_count, 2)
            saved = [c.args[0] for c in repository.save_passage.call_args_list]
            ordered_ids = [p.metadata["comment_id"] for p in saved]
            self.assertEqual(ordered_ids, ["Ugx-TOP-2", "Ugx-REPLY-2A"])
            reply = next(p for p in saved if p.metadata["comment_id"] == "Ugx-REPLY-2A")
            self.assertEqual(reply.metadata["parent_id"], "Ugx-TOP-2")

            store = YouTubePostCommentCheckpointStore(checkpoint)
            self.assertEqual(
                store.load_comment_ids("P1"),
                {"Ugx-TOP-1", "Ugx-REPLY-1A", "Ugx-TOP-2", "Ugx-REPLY-2A"},
            )


# ---------------------------------------------------------------------------
# Blocker 2: count reconciliation gates completion
# ---------------------------------------------------------------------------


class CountReconciliationTests(unittest.TestCase):
    def test_provisional_basis_reports_unknown_even_when_numbers_agree(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "t")], visible_comment_count="1"
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.visible_count_basis, "provisional")
        self.assertEqual(result.counts.count_match, "unknown")
        self.assertNotIn("visible_count_mismatch", result.reasons)
        self.assertEqual(result.status, "completed")

    def test_provisional_basis_reports_unknown_even_when_numbers_disagree(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "t")], visible_comment_count="99"
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.count_match, "unknown")
        self.assertNotIn("visible_count_mismatch", result.reasons)

    def test_verified_mismatch_forces_incomplete(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "t")], visible_comment_count="99"
        )

        with patch.object(ypc_module, "VISIBLE_COUNT_BASIS_IS_VERIFIED", True):
            result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.visible_count_basis, "verified")
        self.assertEqual(result.counts.count_match, "false")
        self.assertIn("visible_count_mismatch", result.reasons)
        self.assertEqual(result.status, "incomplete")

    def test_verified_match_stays_completed(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "t")], visible_comment_count="1"
        )

        with patch.object(ypc_module, "VISIBLE_COUNT_BASIS_IS_VERIFIED", True):
            result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.count_match, "true")
        self.assertEqual(result.status, "completed")

    def test_unavailable_basis_when_no_count_shown(self):
        payload = browser_payload(comments=[comment_payload("Ugx-1", "t")], visible_comment_count=None)

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.visible_count_basis, "unavailable")
        self.assertEqual(result.counts.count_match, "unknown")

    def test_zero_capture_without_disabled_signal_is_incomplete_not_completed(self):
        payload = browser_payload(comments=[])

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "incomplete")
        self.assertIn("unverified_zero_comments", result.reasons)

    def test_blocking_reasons_constant_is_wired_into_status_resolution(self):
        # Regression guard: every _BLOCKING_REASONS entry that can plausibly
        # appear in a per-post reasons list actually drives "incomplete".
        for reason in ("missing_comments_panel", "round_limit_reached", "wall_clock_exceeded"):
            self.assertEqual(ypc_module._resolve_status([reason]), "incomplete")
        self.assertEqual(ypc_module._resolve_status([]), "completed")


# ---------------------------------------------------------------------------
# Blocker 3: empty comment/reply bodies are rejected from canonical indexing
# ---------------------------------------------------------------------------


class EmptyTextTests(unittest.TestCase):
    def test_empty_top_level_text_is_provisional(self):
        payload = browser_payload(comments=[comment_payload("Ugx-1", "")])

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.comments, ())
        self.assertEqual(len(result.provisional_records), 1)

    def test_empty_reply_text_is_provisional(self):
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-A", "top text"),
                comment_payload("Ugx-R1", "   ", parent_id="Ugx-A"),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(len(result.comments), 1)
        self.assertEqual(result.comments[0].comment_id, "Ugx-A")
        self.assertEqual(len(result.provisional_records), 1)

    def test_missing_text_forces_incomplete(self):
        payload = browser_payload(comments=[comment_payload("Ugx-1", "")])

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "incomplete")
        self.assertIn("missing_comment_text", result.reasons)

    def test_deleted_placeholder_is_canonical_and_distinct_from_missing_text(self):
        payload = browser_payload(comments=[comment_payload("Ugx-1", "[deleted]")])

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(len(result.comments), 1)
        self.assertIn("deleted_comment_placeholder_present", result.reasons)
        self.assertNotIn("missing_comment_text", result.reasons)
        # A genuine placeholder does not, by itself, force incomplete.
        self.assertEqual(result.status, "completed")

    def test_hidden_content_is_distinct_from_plain_selector_failure(self):
        hidden = browser_payload(
            post_id="P1",
            comments=[comment_payload("Ugx-1", "", content_state="hidden")],
        )
        selector_failure = browser_payload(
            post_id="P2",
            comments=[comment_payload("Ugx-2", "", content_state=None)],
        )

        hidden_result = parse_browser_comment_payload("P1", json.dumps(hidden))
        failure_result = parse_browser_comment_payload("P2", json.dumps(selector_failure))

        self.assertIn("hidden_reply_content", hidden_result.reasons)
        self.assertNotIn("missing_comment_text", hidden_result.reasons)

        self.assertIn("missing_comment_text", failure_result.reasons)
        self.assertNotIn("hidden_reply_content", failure_result.reasons)

    def test_selector_failure_never_silently_completes_with_empty_comments(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", ""), comment_payload("Ugx-2", "")]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.comments, ())
        self.assertEqual(result.status, "incomplete")


# ---------------------------------------------------------------------------
# Operational risk corrections
# ---------------------------------------------------------------------------


class OperationalRiskTests(unittest.TestCase):
    def test_progress_based_expansion_terminates_on_genuine_stability(self):
        # top_level_stalled=True with no round/wall-clock limit and no
        # pending reply expansion is genuine, progress-proven exhaustion --
        # not a blocker.
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "final comment")],
            top_level_stalled=True,
            round_limit_reached=False,
            wall_clock_exceeded=False,
            reply_expansion_incomplete=False,
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.reasons, ())

    def test_nonfunctional_more_replies_button_is_reported_incomplete(self):
        # Simulates the button-present-but-nonfunctional case: the browser
        # script gave up after repeated non-productive clicks, and the
        # button is still (spuriously) present -- must not be silently done.
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "top text")],
            reply_expansion_incomplete=True,
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "incomplete")
        self.assertIn("incomplete_reply_expansion", result.reasons)

    def test_round_limit_forces_incomplete_never_completed(self):
        payload = browser_payload(round_limit_reached=True, top_level_stalled=False)

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "incomplete")
        self.assertIn("round_limit_reached", result.reasons)

    def test_wall_clock_limit_forces_incomplete_never_completed(self):
        payload = browser_payload(wall_clock_exceeded=True, top_level_stalled=False)

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "incomplete")
        self.assertIn("wall_clock_exceeded", result.reasons)

    def test_unlimited_default_passes_a_practical_bound_not_a_million(self):
        captured = {}

        def fake_runner(post_url, max_rounds, wall_clock_budget_seconds):
            captured["max_rounds"] = max_rounds
            captured["wall_clock"] = wall_clock_budget_seconds
            return json.dumps(browser_payload())

        collect_post_comments_via_browser("P1", None, runner=fake_runner)

        self.assertIsInstance(captured["max_rounds"], int)
        self.assertLess(captured["max_rounds"], 1_000_000)
        self.assertGreater(captured["max_rounds"], 0)
        self.assertEqual(captured["wall_clock"], ypc_module.DEFAULT_WALL_CLOCK_BUDGET_SECONDS)

    def test_explicit_round_bound_is_forwarded_to_runner(self):
        captured = {}

        def fake_runner(post_url, max_rounds, wall_clock_budget_seconds):
            captured["max_rounds"] = max_rounds
            return json.dumps(browser_payload())

        collect_post_comments_via_browser("P1", 12, runner=fake_runner)

        self.assertEqual(captured["max_rounds"], 12)

    def test_runner_failure_is_reported_as_failed_not_raised(self):
        def raising_runner(post_url, max_rounds, wall_clock_budget_seconds):
            raise RuntimeError("Brave is not running")

        result = collect_post_comments_via_browser("P1", 5, runner=raising_runner)

        self.assertEqual(result.status, "failed")
        self.assertTrue(any(r.startswith("fetch_failure:") for r in result.reasons))

    def test_feed_refresh_reports_stabilized(self):
        output = "\n".join(
            [json.dumps(["https://www.youtube.com/post/Ugkx-A"]), "__WRG_STABILIZED__"]
        )

        result = parse_browser_post_feed_payload(output)

        self.assertTrue(result.stabilized)
        self.assertEqual(result.reasons, ())

    def test_feed_refresh_reports_scroll_limit_reached(self):
        output = "\n".join(
            [json.dumps(["https://www.youtube.com/post/Ugkx-A"]), "__WRG_SCROLL_LIMIT_REACHED__"]
        )

        result = parse_browser_post_feed_payload(output)

        self.assertFalse(result.stabilized)
        self.assertIn("scroll_limit_reached", result.reasons)

    def test_feed_refresh_limit_makes_campaign_coverage_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            posts_checkpoint = Path(tmp) / "posts.json"

            def limited_refresher(channel_url, posts_checkpoint_path, **_kwargs):
                store = YouTubePostCheckpointStore(posts_checkpoint_path)
                store.save(channel_url, {"Ugkx-A"})
                return PostFeedRefreshResult(
                    discovered_post_ids=frozenset({"Ugkx-A"}),
                    stabilized=False,
                    reasons=("scroll_limit_reached",),
                )

            def extractor(post_id, max_continuation_fetches):
                return parse_browser_comment_payload(
                    post_id, json.dumps(browser_payload(post_id=post_id, comments_disabled=True))
                )

            with patch(
                "warrigal.acquisition.youtube_post_comments.AcquisitionService"
            ) as service:
                service.return_value.acquire_bytes.return_value = _mock_acquisition("O", "A")
                repository = Mock()
                repository.get_passages_for_object.return_value = []
                result = run_post_comment_campaign(
                    CHANNEL_URL,
                    posts_checkpoint_path=posts_checkpoint,
                    comments_checkpoint_path=Path(tmp) / "comments.json",
                    repository=repository,
                    object_store=Mock(),
                    job_id="J", node_id="N", batch_id="B", collection_id="C",
                    post_feed_refresher=limited_refresher,
                    comment_extractor=extractor,
                )

            self.assertEqual(result.feed_coverage_status, "incomplete")
            self.assertIn("scroll_limit_reached", result.feed_coverage_reasons)


# ---------------------------------------------------------------------------
# Credential safety (unchanged, reused)
# ---------------------------------------------------------------------------


class CredentialSafetyTests(unittest.TestCase):
    def test_no_credential_shaped_key_in_clean_payload(self):
        clean = browser_payload(comments=[comment_payload("C1", "hello")])
        self.assertIsNone(_contains_credential_shaped_key(clean))

    def test_credential_shaped_key_is_detected(self):
        dirty = {"session_cookie": "abc123", "nested": {"auth_token": "xyz"}}
        self.assertIsNotNone(_contains_credential_shaped_key(dirty))

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_ingestion_refuses_to_persist_a_credential_shaped_snapshot(self, service):
        service.return_value.acquire_bytes.return_value = _mock_acquisition("O", "A")
        repository = Mock()
        repository.get_passages_for_object.return_value = []

        def poisoned_extractor(post_id, max_continuation_fetches):
            return PostCommentCollection(
                post_id=post_id,
                post_url=f"https://www.youtube.com/post/{post_id}",
                comments=(),
                provisional_records=(),
                raw_pages=(
                    RawPageRecord(
                        "browser_snapshot", None, None, {"leaked_cookie": "should-not-persist"}
                    ),
                ),
                counts=_empty_counts(),
                identity_coverage=_empty_identity_coverage(),
                status="completed",
                reasons=("comments_disabled",),
            )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "credential-shaped"):
                ingest_youtube_post_comments(
                    "P1", checkpoint_path=Path(tmp) / "c.json", repository=repository,
                    object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                    collection_id="C", extractor=poisoned_extractor,
                )
        repository.save_passage.assert_not_called()


# ---------------------------------------------------------------------------
# Core parsing / identity / ordering (regression coverage retained)
# ---------------------------------------------------------------------------


class ParseBrowserCommentPayloadTests(unittest.TestCase):
    def test_comments_panel_found_and_top_level_comment_parsed(self):
        payload = browser_payload(comments=[comment_payload("Ugx-1", "Top text")])

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(len(result.comments), 1)
        self.assertIsNone(result.comments[0].parent_id)

    def test_missing_comments_panel_is_incomplete(self):
        payload = browser_payload(comments_panel_found=False)

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "incomplete")
        self.assertIn("missing_comments_panel", result.reasons)

    def test_nested_reply_links_to_parent(self):
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-A", "Top text"),
                comment_payload("Ugx-R1", "A reply", parent_id="Ugx-A", order=0),
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        reply = next(c for c in result.comments if c.comment_id == "Ugx-R1")
        self.assertEqual(reply.parent_id, "Ugx-A")

    def test_comments_disabled_with_zero_comments_is_genuinely_completed(self):
        payload = browser_payload(comments_disabled=True)

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.comments, ())

    def test_comments_unavailable_with_zero_comments_is_genuinely_completed(self):
        payload = browser_payload(comments_unavailable=True)

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.status, "completed")

    def test_malformed_response_does_not_crash(self):
        result = parse_browser_comment_payload("P1", "not valid json {{{")

        self.assertEqual(result.status, "incomplete")
        self.assertIn("malformed_response", result.reasons)

    def test_raw_browser_payload_is_preserved_as_provenance(self):
        payload = browser_payload(comments=[comment_payload("Ugx-1", "Top text")])

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(len(result.raw_pages), 1)
        self.assertEqual(result.raw_pages[0].kind, "browser_snapshot")
        self.assertEqual(result.raw_pages[0].page["comments"][0]["id"], "Ugx-1")

    def test_stable_author_id_confirms_tom(self):
        payload = browser_payload(
            comments=[
                comment_payload(
                    "Ugx-TOM", "Manuscript", author="@TFJ7", author_id=TARGET_AUTHOR_CHANNEL_ID
                )
            ]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.comments[0].author_id, TARGET_AUTHOR_CHANNEL_ID)

    def test_spoofed_handle_with_different_channel_id_is_not_target(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-SPOOF", "Impersonation", author="@TFJ7", author_id="UC-IMPOSTER")]
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.comments[0].author, "@TFJ7")
        self.assertNotEqual(result.comments[0].author_id, TARGET_AUTHOR_CHANNEL_ID)


class ResolvePostIdTests(unittest.TestCase):
    def test_bare_id_is_returned_unchanged(self):
        self.assertEqual(resolve_post_id("Ugkx-ABC"), "Ugkx-ABC")

    def test_full_url_extracts_id(self):
        self.assertEqual(resolve_post_id("https://www.youtube.com/post/Ugkx-ABC"), "Ugkx-ABC")


class PlanPostCommentCampaignTests(unittest.TestCase):
    def test_plan_reads_existing_checkpoint_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            posts_checkpoint = Path(tmp) / "posts.json"
            YouTubePostCheckpointStore(posts_checkpoint).save(
                CHANNEL_URL, {"Ugkx-2", "Ugkx-1"}
            )

            plan = plan_post_comment_campaign(
                CHANNEL_URL, posts_checkpoint_path=posts_checkpoint
            )

            self.assertEqual(plan, ["Ugkx-1", "Ugkx-2"])


# ---------------------------------------------------------------------------
# Checkpoint store (unchanged)
# ---------------------------------------------------------------------------


class CheckpointStoreTests(unittest.TestCase):
    def test_atomic_write_leaves_no_temp_file_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comments.json"
            store = YouTubePostCommentCheckpointStore(path)
            store.save("Ugkx-1", comment_ids={"C1", "C2"}, status="completed", reasons=[])

            self.assertFalse(path.with_name(path.name + ".tmp").exists())
            self.assertEqual(store.load_comment_ids("Ugkx-1"), {"C1", "C2"})

    def test_interrupted_write_preserves_previous_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comments.json"
            store = YouTubePostCommentCheckpointStore(path)
            store.save("Ugkx-1", comment_ids={"C1"}, status="completed", reasons=[])
            original = path.read_bytes()

            with patch.object(Path, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    store.save(
                        "Ugkx-1", comment_ids={"C1", "C2"}, status="completed", reasons=[]
                    )

            self.assertEqual(path.read_bytes(), original)


# ---------------------------------------------------------------------------
# Ingestion: dedup, incremental rerun, dual timestamps
# ---------------------------------------------------------------------------


class IngestYoutubePostCommentsTests(unittest.TestCase):
    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_dual_timestamps_and_no_reconciliation_fields(self, service):
        service.return_value.acquire_bytes.return_value = _mock_acquisition("O1", "A1")
        repository = Mock()
        repository.get_passages_for_object.return_value = []
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-TOM", "Manuscript", author="@TFJ7", author_id=TARGET_AUTHOR_CHANNEL_ID),
                comment_payload("Ugx-R1", "reply", parent_id="Ugx-TOM", author="@Other", author_id="UC-OTHER"),
            ],
        )

        def extractor(post_id, max_continuation_fetches):
            return parse_browser_comment_payload(post_id, json.dumps(payload))

        with tempfile.TemporaryDirectory() as tmp:
            result = ingest_youtube_post_comments(
                "P1", checkpoint_path=Path(tmp) / "c.json", repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=extractor,
            )

        self.assertEqual(result.counts.total_count, 2)
        saved = [c.args[0] for c in repository.save_passage.call_args_list]
        top_passage = next(p for p in saved if p.metadata["comment_id"] == "Ugx-TOM")
        self.assertTrue(top_passage.metadata["is_target_author"])
        self.assertIsNotNone(top_passage.created_at)
        self.assertNotIn("manual_reference_match", top_passage.metadata)

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_rerun_against_identical_payload_adds_nothing(self, service):
        service.return_value.acquire_bytes.return_value = _mock_acquisition("O2", "A2")
        repository = Mock()
        repository.get_passages_for_object.return_value = []

        def extractor(post_id, max_continuation_fetches):
            payload = browser_payload(comments=[comment_payload("Ugx-1", "t")])
            return parse_browser_comment_payload(post_id, json.dumps(payload))

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "c.json"
            first = ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=extractor,
            )
            repository.save_passage.reset_mock()
            second = ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=extractor,
            )

        self.assertEqual(first.new_count, 1)
        self.assertEqual(second.new_count, 0)
        repository.save_passage.assert_not_called()

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_partial_failure_then_successful_rerun_does_not_duplicate(self, service):
        service.return_value.acquire_bytes.side_effect = [
            _mock_acquisition("O3A", "A3A"),
            _mock_acquisition("O3B", "A3B"),
        ]
        repository = Mock()
        repository.get_passages_for_object.return_value = []

        def failing_extractor(post_id, max_continuation_fetches):
            return PostCommentCollection(
                post_id=post_id,
                post_url=f"https://www.youtube.com/post/{post_id}",
                comments=(),
                provisional_records=(),
                raw_pages=(),
                counts=_empty_counts(),
                identity_coverage=_empty_identity_coverage(),
                status="failed",
                reasons=("fetch_failure:ConnectionError: simulated blip",),
            )

        def succeeding_extractor(post_id, max_continuation_fetches):
            payload = browser_payload(
                comments=[
                    comment_payload("Ugx-A", "a"),
                    comment_payload("Ugx-B", "b", order=1),
                ]
            )
            return parse_browser_comment_payload(post_id, json.dumps(payload))

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "c.json"
            first = ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=failing_extractor,
            )
            repository.save_passage.reset_mock()
            second = ingest_youtube_post_comments(
                "P1", checkpoint_path=checkpoint, repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=succeeding_extractor,
            )

        self.assertEqual(first.status, "failed")
        self.assertEqual(second.status, "completed")
        self.assertEqual(second.new_count, 2)
        self.assertEqual(repository.save_passage.call_count, 2)


# ---------------------------------------------------------------------------
# Authenticated Community-post feed refresh
# ---------------------------------------------------------------------------


class RefreshPostFeedViaBrowserTests(unittest.TestCase):
    def test_discovers_newer_posts_and_merges_with_existing_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            posts_checkpoint = Path(tmp) / "posts.json"
            YouTubePostCheckpointStore(posts_checkpoint).save(CHANNEL_URL, {"Ugkx-OLD"})

            def fake_runner(channel_url, max_scrolls, delay, stable_rounds):
                return "\n".join(
                    [
                        json.dumps(["https://www.youtube.com/post/Ugkx-NEW"]),
                        "__WRG_STABILIZED__",
                    ]
                )

            result = refresh_post_feed_via_browser(
                CHANNEL_URL, posts_checkpoint, runner=fake_runner
            )

            self.assertTrue(result.stabilized)
            store_result = YouTubePostCheckpointStore(posts_checkpoint).load(CHANNEL_URL)
            self.assertEqual(store_result, {"Ugkx-OLD", "Ugkx-NEW"})

    def test_parse_feed_payload_deduplicates_across_snapshot_lines(self):
        output = "\n".join(
            [
                json.dumps(["https://www.youtube.com/post/Ugkx-A"]),
                json.dumps(
                    [
                        "https://www.youtube.com/post/Ugkx-A",
                        "https://www.youtube.com/post/Ugkx-B",
                    ]
                ),
                "__WRG_STABILIZED__",
            ]
        )

        result = parse_browser_post_feed_payload(output)

        self.assertEqual(set(result.discovered_post_ids), {"Ugkx-A", "Ugkx-B"})


# ---------------------------------------------------------------------------
# Campaign: refresh, coverage, per-post isolation, default revisit behaviour
# ---------------------------------------------------------------------------


def _stabilized_refresher(discovered: set[str] | None = None):
    def refresher(channel_url, posts_checkpoint_path, **_kwargs):
        store = YouTubePostCheckpointStore(posts_checkpoint_path)
        existing = store.load(channel_url) if posts_checkpoint_path else set()
        merged = existing | (discovered or set())
        store.save(channel_url, merged)
        return PostFeedRefreshResult(
            discovered_post_ids=frozenset(merged), stabilized=True, reasons=()
        )

    return refresher


class PostCommentCampaignTests(unittest.TestCase):
    def test_refresh_is_invoked_and_newly_discovered_posts_are_attempted(self):
        with tempfile.TemporaryDirectory() as tmp:
            posts_checkpoint = Path(tmp) / "posts.json"
            comments_checkpoint = Path(tmp) / "comments.json"
            YouTubePostCheckpointStore(posts_checkpoint).save(CHANNEL_URL, {"Ugkx-OLD"})

            def fake_refresher(channel_url, posts_checkpoint_path, **_kwargs):
                store = YouTubePostCheckpointStore(posts_checkpoint_path)
                merged = store.load(channel_url) | {"Ugkx-NEW"}
                store.save(channel_url, merged)
                return PostFeedRefreshResult(frozenset(merged), True, ())

            def fake_extractor(post_id, max_continuation_fetches):
                return parse_browser_comment_payload(
                    post_id, json.dumps(browser_payload(post_id=post_id, comments_disabled=True))
                )

            with patch(
                "warrigal.acquisition.youtube_post_comments.AcquisitionService"
            ) as service:
                service.return_value.acquire_bytes.return_value = _mock_acquisition("O", "A")
                repository = Mock()
                repository.get_passages_for_object.return_value = []
                result = run_post_comment_campaign(
                    CHANNEL_URL,
                    posts_checkpoint_path=posts_checkpoint,
                    comments_checkpoint_path=comments_checkpoint,
                    repository=repository,
                    object_store=Mock(),
                    job_id="J", node_id="N", batch_id="B", collection_id="C",
                    post_feed_refresher=fake_refresher,
                    comment_extractor=fake_extractor,
                )

            self.assertEqual(result.known_before_refresh, ("Ugkx-OLD",))
            self.assertEqual(result.newly_discovered, ("Ugkx-NEW",))
            self.assertEqual(set(result.completed), {"Ugkx-OLD", "Ugkx-NEW"})
            self.assertEqual(result.feed_coverage_status, "complete")

    def test_failure_on_one_post_does_not_stop_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            posts_checkpoint = Path(tmp) / "posts.json"
            comments_checkpoint = Path(tmp) / "comments.json"
            YouTubePostCheckpointStore(posts_checkpoint).save(
                CHANNEL_URL, {"Ugkx-GOOD", "Ugkx-BAD"}
            )

            def extractor(post_id, max_continuation_fetches):
                if post_id == "Ugkx-BAD":
                    raise ValueError("simulated failure")
                return parse_browser_comment_payload(
                    post_id, json.dumps(browser_payload(post_id=post_id, comments_disabled=True))
                )

            with patch(
                "warrigal.acquisition.youtube_post_comments.AcquisitionService"
            ) as service:
                service.return_value.acquire_bytes.return_value = _mock_acquisition("O", "A")
                repository = Mock()
                repository.get_passages_for_object.return_value = []
                result = run_post_comment_campaign(
                    CHANNEL_URL,
                    posts_checkpoint_path=posts_checkpoint,
                    comments_checkpoint_path=comments_checkpoint,
                    repository=repository,
                    object_store=Mock(),
                    job_id="J", node_id="N", batch_id="B", collection_id="C",
                    post_feed_refresher=_stabilized_refresher(),
                    comment_extractor=extractor,
                )

            self.assertEqual(result.completed, ("Ugkx-GOOD",))
            self.assertEqual(result.failed, ("Ugkx-BAD",))

    def test_completed_posts_are_revisited_by_default_and_new_comments_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            posts_checkpoint = Path(tmp) / "posts.json"
            comments_checkpoint = Path(tmp) / "comments.json"
            YouTubePostCheckpointStore(posts_checkpoint).save(CHANNEL_URL, {"Ugkx-DONE"})
            YouTubePostCommentCheckpointStore(comments_checkpoint).save(
                "Ugkx-DONE", comment_ids={"Ugx-OLD"}, status="completed", reasons=[]
            )

            def extractor(post_id, max_continuation_fetches):
                payload = browser_payload(
                    post_id=post_id,
                    comments=[
                        comment_payload("Ugx-OLD", "already seen"),
                        comment_payload("Ugx-NEW-REPLY", "brand new"),
                    ],
                )
                return parse_browser_comment_payload(post_id, json.dumps(payload))

            with patch(
                "warrigal.acquisition.youtube_post_comments.AcquisitionService"
            ) as service:
                service.return_value.acquire_bytes.return_value = _mock_acquisition("O", "A")
                repository = Mock()
                repository.get_passages_for_object.return_value = []
                result = run_post_comment_campaign(
                    CHANNEL_URL,
                    posts_checkpoint_path=posts_checkpoint,
                    comments_checkpoint_path=comments_checkpoint,
                    repository=repository,
                    object_store=Mock(),
                    job_id="J", node_id="N", batch_id="B", collection_id="C",
                    post_feed_refresher=_stabilized_refresher(),
                    comment_extractor=extractor,
                )

            self.assertIn("Ugkx-DONE", result.attempted)
            item = next(i for i in result.items if i.post_id == "Ugkx-DONE")
            self.assertEqual(item.new_count, 1)
            saved = [c.args[0] for c in repository.save_passage.call_args_list]
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].metadata["comment_id"], "Ugx-NEW-REPLY")

    def test_skip_completed_opt_in_still_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            posts_checkpoint = Path(tmp) / "posts.json"
            comments_checkpoint = Path(tmp) / "comments.json"
            YouTubePostCheckpointStore(posts_checkpoint).save(
                CHANNEL_URL, {"Ugkx-DONE", "Ugkx-RETRY"}
            )
            YouTubePostCommentCheckpointStore(comments_checkpoint).save(
                "Ugkx-DONE", comment_ids=set(), status="completed", reasons=[]
            )
            YouTubePostCommentCheckpointStore(comments_checkpoint).save(
                "Ugkx-RETRY", comment_ids=set(), status="incomplete", reasons=["round_limit_reached"]
            )

            calls: list[str] = []

            def extractor(post_id, max_continuation_fetches):
                calls.append(post_id)
                return parse_browser_comment_payload(
                    post_id, json.dumps(browser_payload(post_id=post_id, comments_disabled=True))
                )

            with patch(
                "warrigal.acquisition.youtube_post_comments.AcquisitionService"
            ) as service:
                service.return_value.acquire_bytes.return_value = _mock_acquisition("O", "A")
                repository = Mock()
                repository.get_passages_for_object.return_value = []
                result = run_post_comment_campaign(
                    CHANNEL_URL,
                    posts_checkpoint_path=posts_checkpoint,
                    comments_checkpoint_path=comments_checkpoint,
                    repository=repository,
                    object_store=Mock(),
                    job_id="J", node_id="N", batch_id="B", collection_id="C",
                    skip_completed=True,
                    post_feed_refresher=_stabilized_refresher(),
                    comment_extractor=extractor,
                )

            self.assertNotIn("Ugkx-DONE", calls)
            self.assertIn("Ugkx-RETRY", calls)
            self.assertNotIn("Ugkx-DONE", result.attempted)


# ---------------------------------------------------------------------------
# Phase 2: verified author-channel-ID resolution and unavailable-count
# handling, based on the controlled live diagnosis of the validated post.
# ---------------------------------------------------------------------------


class NormalizeVisibleCountTests(unittest.TestCase):
    def test_empty_string_is_treated_as_unavailable_not_provisional(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "t")], visible_comment_count=""
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.visible_count_basis, "unavailable")
        self.assertEqual(result.counts.count_match, "unknown")

    def test_whitespace_only_string_is_treated_as_unavailable(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "t")], visible_comment_count="   "
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.visible_count_basis, "unavailable")

    def test_none_remains_unavailable(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "t")], visible_comment_count=None
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.visible_count_basis, "unavailable")

    def test_genuine_numeric_string_is_provisional_when_unverified(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "t")], visible_comment_count="4"
        )

        result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.visible_count_basis, "provisional")

    def test_verified_basis_with_matching_total_is_true_and_completed(self):
        payload = browser_payload(
            comments=[
                comment_payload("Ugx-1", "a"),
                comment_payload("Ugx-2", "b", order=1),
            ],
            visible_comment_count="2",
        )

        with patch.object(ypc_module, "VISIBLE_COUNT_BASIS_IS_VERIFIED", True):
            result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.visible_count_basis, "verified")
        self.assertEqual(result.counts.count_match, "true")
        self.assertEqual(result.status, "completed")

    def test_verified_basis_with_mismatching_total_forces_incomplete(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "a")], visible_comment_count="4"
        )

        with patch.object(ypc_module, "VISIBLE_COUNT_BASIS_IS_VERIFIED", True):
            result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.count_match, "false")
        self.assertEqual(result.status, "incomplete")
        self.assertIn("visible_count_mismatch", result.reasons)

    def test_ambiguous_non_numeric_count_stays_unknown_even_when_verified_flag_set(self):
        # e.g. an abbreviated "1.2K" -- present, but not a value we can
        # compare exactly, so it must never be presented as a proven match.
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "a")], visible_comment_count="1.2K"
        )

        with patch.object(ypc_module, "VISIBLE_COUNT_BASIS_IS_VERIFIED", True):
            result = parse_browser_comment_payload("P1", json.dumps(payload))

        self.assertEqual(result.counts.visible_count_basis, "verified")
        self.assertEqual(result.counts.count_match, "unknown")
        self.assertNotIn("visible_count_mismatch", result.reasons)


class NormalizeHandleTests(unittest.TestCase):
    def test_adds_leading_at_sign_if_missing(self):
        self.assertEqual(_normalize_handle("TFJ7"), "@TFJ7")

    def test_preserves_existing_at_sign(self):
        self.assertEqual(_normalize_handle("@TFJ7"), "@TFJ7")

    def test_none_and_empty_return_none(self):
        self.assertIsNone(_normalize_handle(None))
        self.assertIsNone(_normalize_handle(""))
        self.assertIsNone(_normalize_handle("   "))


class ResolveChannelIdViaHandleTests(unittest.TestCase):
    def test_accepts_a_wellformed_channel_id_from_the_runner(self):
        def fake_runner(handle_url: str) -> str:
            self.assertEqual(handle_url, "https://www.youtube.com/@TFJ7")
            return TARGET_AUTHOR_CHANNEL_ID

        result = resolve_channel_id_via_handle("@TFJ7", runner=fake_runner)

        self.assertEqual(result, TARGET_AUTHOR_CHANNEL_ID)

    def test_normalizes_a_bare_handle_without_at_sign_before_building_the_url(self):
        captured = {}

        def fake_runner(handle_url: str) -> str:
            captured["url"] = handle_url
            return TARGET_AUTHOR_CHANNEL_ID

        resolve_channel_id_via_handle("TFJ7", runner=fake_runner)

        self.assertEqual(captured["url"], "https://www.youtube.com/@TFJ7")

    def test_rejects_a_malformed_result(self):
        result = resolve_channel_id_via_handle("@TFJ7", runner=lambda url: "not-a-channel-id")

        self.assertIsNone(result)

    def test_empty_result_resolves_to_none(self):
        result = resolve_channel_id_via_handle("@TFJ7", runner=lambda url: "")

        self.assertIsNone(result)

    def test_runner_failure_resolves_to_none_not_raised(self):
        def raising_runner(handle_url: str) -> str:
            raise RuntimeError("Brave is not running")

        result = resolve_channel_id_via_handle("@TFJ7", runner=raising_runner)

        self.assertIsNone(result)

    def test_none_handle_resolves_to_none_without_calling_runner(self):
        called = []
        result = resolve_channel_id_via_handle(None, runner=lambda url: called.append(url) or "x")

        self.assertIsNone(result)
        self.assertEqual(called, [])


class ResolveTargetAuthorIdsTests(unittest.TestCase):
    def _comment(self, **overrides):
        from warrigal.acquisition.youtube_post_comments import YouTubePostComment

        defaults = dict(
            comment_id="Ugx-1", parent_id=None, order=0, text="hi",
            author="@TFJ7", author_id=None, author_url="https://www.youtube.com/@TFJ7",
            published_text="2 weeks ago", like_count=None, id_basis="copy_link",
        )
        defaults.update(overrides)
        return YouTubePostComment(**defaults)

    def test_handle_only_target_remains_unconfirmed_when_resolver_returns_none(self):
        comment = self._comment()

        resolved = _resolve_target_author_ids((comment,), resolve_handle=lambda h: None)

        self.assertIsNone(resolved[0].author_id)

    def test_exact_tom_id_is_confirmed_via_resolution(self):
        comment = self._comment()

        resolved = _resolve_target_author_ids(
            (comment,), resolve_handle=lambda h: TARGET_AUTHOR_CHANNEL_ID
        )

        self.assertEqual(resolved[0].author_id, TARGET_AUTHOR_CHANNEL_ID)

    def test_resolution_is_cached_per_unique_handle_within_one_call(self):
        comments = (self._comment(comment_id="Ugx-1"), self._comment(comment_id="Ugx-2"))
        calls = []

        def counting_resolver(handle):
            calls.append(handle)
            return TARGET_AUTHOR_CHANNEL_ID

        resolved = _resolve_target_author_ids(comments, resolve_handle=counting_resolver)

        self.assertEqual(len(calls), 1)
        self.assertTrue(all(c.author_id == TARGET_AUTHOR_CHANNEL_ID for c in resolved))

    def test_non_target_handle_is_never_sent_to_the_resolver(self):
        comment = self._comment(author="@SomeoneElse", author_id=None)
        called = []

        resolved = _resolve_target_author_ids(
            (comment,), resolve_handle=lambda h: called.append(h) or "UC-WRONG"
        )

        self.assertEqual(called, [])
        self.assertIsNone(resolved[0].author_id)

    def test_already_populated_author_id_is_never_overwritten_or_resolved(self):
        # Guards the existing spoofed-handle-rejection guarantee: if some
        # other extraction path already set a (wrong) author_id, resolution
        # must not be attempted or allowed to override it.
        comment = self._comment(author="@TFJ7", author_id="UC-IMPOSTER")
        called = []

        resolved = _resolve_target_author_ids(
            (comment,), resolve_handle=lambda h: called.append(h) or TARGET_AUTHOR_CHANNEL_ID
        )

        self.assertEqual(called, [])
        self.assertEqual(resolved[0].author_id, "UC-IMPOSTER")

    def test_unchanged_tuple_identity_when_nothing_resolves(self):
        comment = self._comment(author="@SomeoneElse", author_id=None)
        comments = (comment,)

        resolved = _resolve_target_author_ids(comments, resolve_handle=lambda h: None)

        self.assertIs(resolved, comments)


class CollectPostCommentsViaBrowserHandleResolutionTests(unittest.TestCase):
    def test_default_extractor_resolves_target_handle_end_to_end(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "hi", author="@TFJ7", author_id=None)]
        )

        def fetch_runner(post_url, max_rounds, wall_clock_budget_seconds):
            return json.dumps(payload)

        def resolve_runner(handle_url):
            return TARGET_AUTHOR_CHANNEL_ID

        result = collect_post_comments_via_browser(
            "P1", runner=fetch_runner,
            resolve_handle=lambda h: resolve_channel_id_via_handle(h, runner=resolve_runner),
        )

        self.assertEqual(result.comments[0].author_id, TARGET_AUTHOR_CHANNEL_ID)

    def test_default_extractor_leaves_non_target_authors_unresolved(self):
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "hi", author="@SomeoneElse", author_id=None)]
        )

        def fetch_runner(post_url, max_rounds, wall_clock_budget_seconds):
            return json.dumps(payload)

        called = []

        result = collect_post_comments_via_browser(
            "P1", runner=fetch_runner,
            resolve_handle=lambda h: called.append(h) or None,
        )

        self.assertEqual(called, [])
        self.assertIsNone(result.comments[0].author_id)

    @patch("warrigal.acquisition.youtube_post_comments.AcquisitionService")
    def test_ingestion_marks_is_target_author_true_after_resolution(self, service):
        service.return_value.acquire_bytes.return_value = _mock_acquisition("O1", "A1")
        repository = Mock()
        repository.get_passages_for_object.return_value = []
        payload = browser_payload(
            comments=[comment_payload("Ugx-1", "hi", author="@TFJ7", author_id=None)]
        )

        def extractor(post_id, max_continuation_fetches):
            collection = parse_browser_comment_payload(post_id, json.dumps(payload))
            resolved = _resolve_target_author_ids(
                collection.comments, resolve_handle=lambda h: TARGET_AUTHOR_CHANNEL_ID
            )
            from dataclasses import replace as _replace
            return _replace(collection, comments=resolved)

        with tempfile.TemporaryDirectory() as tmp:
            ingest_youtube_post_comments(
                "P1", checkpoint_path=Path(tmp) / "c.json", repository=repository,
                object_store=Mock(), job_id="J", node_id="N", batch_id="B",
                collection_id="C", extractor=extractor,
            )

        saved = repository.save_passage.call_args_list[0].args[0]
        self.assertTrue(saved.metadata["is_target_author"])
        self.assertEqual(saved.metadata["match_basis"], "author_id")


class NoCredentialMaterialInHandleResolutionTests(unittest.TestCase):
    def test_resolve_handle_applescript_source_has_no_credential_markers(self):
        source = ypc_module.RESOLVE_HANDLE_APPLESCRIPT + ypc_module._RESOLVE_HANDLE_JS
        lowered = source.lower()
        for marker in ("cookie", "password", "localstorage", "sessionstorage", "document.cookie"):
            self.assertNotIn(marker, lowered)

    def test_resolve_handle_js_only_reads_public_canonical_metadata(self):
        source = ypc_module._RESOLVE_HANDLE_JS
        self.assertIn("link[rel=\"canonical\"]", source)
        self.assertIn("og:url", source)
        self.assertIn("itemprop=\"identifier\"", source)


if __name__ == "__main__":
    unittest.main()
