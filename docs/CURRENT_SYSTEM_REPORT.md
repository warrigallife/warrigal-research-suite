# Warrigal Research Suite — Current System Report

**Status date:** 29 September 2026 (Australia/Brisbane)  
**Maintainer:** Liam McIlmurray  
**Reference branch:** `warrigal-foundation-01` at `364fd85d654805cff0083e802b0258210535cbc2`

## What exists

Warrigal is a local-first research system for acquiring evidence, preserving original bytes, recording provenance, extracting passages, and retrieving and publishing collections. The repository contains source-specific adapters, a CLI, shared workflows, a source panel, an immutable content-addressed object store, SQLite records, resumable checkpoints, and lexical search. The canonical archive lives outside Git; the repository contains the software, tests, and documentation.

The source panel plans actions through shared workflows and invokes the existing CLI and adapters. Local PDF and recursive PDF archive ingestion, web acquisition, YouTube video and comment acquisition, Instagram workflows, and audio/video processing are present. Individual external tools and models are required for some media workflows; their availability varies by machine. See [README](../README.md), [Architecture](ARCHITECTURE.md), and [Data lifecycle](DATA_LIFECYCLE.md).

| Area | Current evidence and boundary |
|---|---|
| Archive | Original objects, acquisition provenance and indexed passages are separate. Local `workspace` and `archive` paths on Liam's Mac point into `INFORMATION_ARCHIVE/WARRIGAL_DATA`; that private archive is not in Git. |
| Source workflows | The panel and CLI preview share side-effect-free plans; execution delegates to existing adapters. |
| Retrieval | Persistent passage indexing and lexical search work. Grounded claim comparison and knowledge mapping are planned. |
| Authenticated YouTube Community comments | Collector implementation and focused tests were pushed in `364fd85`. Two controlled runs on one post resolved four distinct stable comment IDs to Tom F. Jennings's channel ID and a second run added no passages. The full `@TFJ7` campaign has **not** run. |

## Controlled Community-comment validation

The validated post contained four visually similar top-level comments. The collector retained four distinct IDs in source order, resolved each through canonical channel metadata to `UCa2sLLQdHhQX1gpSqijyZlg`, and reported `visible_count_basis="unavailable"` because no numerical visible count was available. Both live runs exited 0; the second recognized the same IDs and created zero new passages. The reported full suite passed **375 tests** before commit. These are results from the recorded validation, not a claim that every Community post has been collected.

**Outstanding data repair:** Those four IDs had already been checkpointed before author-ID extraction was fixed. Deduplication therefore skipped rewriting their existing canonical passages. Their stored `author_id` fields remain empty, despite the new raw provenance resolving the author correctly. The stored `author_id`, `is_target_author`, and `match_basis` must be checked and repaired against the saved provenance. Do not treat those four canonical passages as correctly attributed until a read-back confirms their fields. This repair does not require changing their text, stable IDs or checkpoint history.

The full authenticated `@TFJ7` Community-comment campaign is still pending. Completeness must be reported honestly: inaccessible, hidden, deleted, truncated or unresolved threads cannot silently count as complete.

## Recorded archive snapshot

The project assessment recorded the following **26 September 2026 snapshot**. These are historical counts, not a live database query made for this report.

| Measure | Recorded value |
|---|---:|
| Stored objects | 14,336 |
| Successful acquisitions | 17,050 |
| Indexed passages | 279,161 |
| Collections | 267 |

## Boundaries for contributors

- The canonical database, object store, authenticated browser profile, cookies, tokens and personal checkpoints do not belong in Git.
- Deduplicate posts, comments and replies by stable source IDs, not repeated text, display handles or visual position.
- Preserve raw observations separately from indexed interpretation; record incomplete collection as incomplete.
- Use fixtures and temporary stores for tests. A read-only reviewer should inspect code and data impact before a release.
- Keep changes scoped and report the commands, results, changed files and any unresolved limitations.

## Immediate next steps

1. Verify and repair only the four stale canonical passages against saved raw provenance; read them back and confirm exactly four distinct records without duplicates.
2. Review the repaired state, then run and audit the full authenticated `@TFJ7` Community-comment campaign, covering the archived posts and any newer posts with top-level and reply continuation checks.
3. Update the corpus report with counts, unresolved threads, provenance and completeness status.
4. Continue the John Kleinbauer acquisition priority and expose more of the archived evidence through the unified research interface.

**Verification command:** `python -m unittest discover -s tests -v` from the project root in a configured environment. The 375-test result above is the reported result for commit `364fd85`; this documentation update does not assert a new live acquisition or archive test.
