# Warrigal Research Suite — Collaborator Handover

**Snapshot reviewed:** 21 September 2026  
**Repository:** `warrigallife/warrigal-research-suite`  
**Reviewed branch:** `warrigal-foundation-01`  
**Reviewed commit:** `a7d1685` — *Expose controlled YouTube workflows in source panel*  
**Working tree in supplied snapshot:** clean

## 1. What Warrigal is

Warrigal is a local-first research system for collecting public source material, preserving the exact source bytes, recording provenance, extracting searchable material, and publishing readable research collections.

Its central rule is that acquired evidence must remain traceable. Warrigal therefore keeps the original bytes, their source and acquisition records, and any later derivatives as separate but connected records.

The GitHub repository contains the application and its tests. It does **not** contain the main research archive. The canonical archive, SQLite database, runtime checkpoints, downloaded media, model files, and private session material live outside Git and must be backed up separately.

## 2. Current development state

This is not an empty prototype. The supplied repository contains:

- 61 Python source files under `src/warrigal/`
- 54 test modules
- 250 test methods detected in the supplied snapshot
- A central command-line interface
- A graphical source-acquisition panel
- A graphical name calculator
- SQLite persistence and schema migration code
- A SHA-256 content-addressed object store
- Source-specific acquisition, checkpointing, verification, indexing, and publication workflows
- Current README, architecture, data-lifecycle, and Bunker of Doom operating documentation

The supplied Git tree is clean, meaning the snapshot does not contain uncommitted code changes. The full test suite was not rerun in the review environment because the supplied virtual environment is built for Liam's Mac and the operational archive is external. Test count and implementation claims below are based on static inspection of the current snapshot; the suite should be run on the Mac before accepting new changes.

## 3. The system model

Warrigal separates the research lifecycle into seven layers:

1. **Discover** candidate sources without necessarily downloading them.
2. **Acquire** bounded source material.
3. **Preserve** exact bytes in the immutable object store and provenance in SQLite.
4. **Derive** text, transcript units, comments, frames, and observations without replacing originals.
5. **Index** evidence as persistent passages connected to its sources.
6. **Research** through lexical retrieval now, with grounded synthesis and saved research runs planned.
7. **Publish** verified human-readable collections derived from the canonical evidence.

### Sources of truth

| Concern | Source of truth |
|---|---|
| Application behaviour | Git repository |
| Exact acquired bytes | SHA-256 object store |
| Provenance and relationships | SQLite database |
| Resume state | Runtime checkpoint files |
| Human-readable collections | Published collection folders |
| Machine-specific paths and tools | `warrigal.local.toml` or environment variables |

Published folders are views of archived evidence. They are not replacements for the object store or database.

## 4. Repository structure

| Path | Role |
|---|---|
| `src/warrigal/` | Main application package |
| `src/warrigal/acquisition/` | Web, manifest, Instagram, YouTube, comment, and Community-post workflows |
| `src/warrigal/retrieval/` | Passage creation, lexical retrieval, and JUFE archive search |
| `tests/` | Unit and workflow tests |
| `docs/` | Architecture, lifecycle, and operating documentation |
| `manifests/` | Versioned bounded acquisition manifests |
| `scripts/` | Operator scripts for controlled campaigns |
| `resources/` | Versioned supporting inputs such as JUFE trigger terms |
| `workspace/` | Local runtime/database link or location; not canonical code |
| `archive/` | Local object-store link or location; not canonical code |

Important modules include:

- `config.py` — resolves paths, tools, models, and local configuration.
- `doctor.py` — read-only installation and configuration diagnostics.
- `archive_health.py` — read-only database/object-store integrity reporting.
- `database.py` — schema creation and migrations.
- `repository.py` — persistence boundary for Warrigal records.
- `object_store.py` — immutable, deduplicated byte storage.
- `workflows.py` — side-effect-free plans shared by the CLI preview and graphical source panel.
- `source_panel.py` — operator-facing acquisition interface.
- `cli.py` — main command dispatcher.
- `name_calculator.py` and `name_calculator_panel.py` — versioned text/name fingerprint calculation and interface.
- `scripture_import.py` — structured corpus import for later research use.

## 5. Implemented capabilities

### Core archive and provenance

- Store exact bytes by SHA-256 hash.
- Deduplicate identical objects while retaining separate acquisition provenance.
- Persist nodes, jobs, batches, collections, acquisitions, derivatives, checkpoints, passages, and source-specific records in SQLite.
- Inspect archive coverage and optionally verify every stored hash.
- Diagnose configured paths, Python dependencies, local executables, and model files without modifying evidence.

### Websites and documents

- Acquire one public URL.
- Discover links without archiving every target.
- Perform bounded same-site crawling.
- Build section-aware PDF/ZIP inventories.
- Review and select inventoried documents before acquisition.
- Apply per-resource byte limits.
- Run resumable manifest campaigns with bounded retries.
- Verify selected or complete manifest coverage.
- Repair damaged PDFs through a controlled derivative path when `qpdf` is configured.
- Ingest local PDFs recursively.
- Publish verified documents into readable collection trees.
- Produce recovery queues for unresolved document failures.

### YouTube

- Resolve and inventory channels.
- Acquire available captions without downloading video media.
- Download a selected video's media and transcribe it locally through Whisper.
- Acquire and preserve video comments.
- Run resumable, bounded multi-video comment campaigns.
- Acquire Community posts.
- Build sentence-oriented transcript text.
- Persist and search archived comments.
- Find comment authors and show an author's archived comments.
- Run channel stages independently: inventory, transcripts, comments, posts, or indexing.
- Run all non-media research layers as one controlled workflow.

### Instagram

- Discover a profile inventory.
- Acquire individual posts or resumable profile campaigns using a saved authenticated session.
- Preserve post metadata, captions, media references, and provenance.
- Checkpoint completed posts and retry unfinished work.
- Verify whether inventory work remains.
- Publish verified Instagram collections.

The workflow exists in code, but actual acquisition remains dependent on Instagram accepting the authenticated session. Recent `feedback_required`, HTTP 400, and HTTP 401 responses should be treated as an external operational access problem, not evidence that the persistence architecture is absent.

### Audio, video, and visual evidence

- Archive audio and video inputs.
- Transcribe audio/video locally with `whisper-cli` when configured.
- Extract video frames with FFmpeg.
- Persist visual observations as derivatives linked to source frames.
- Run configured local Qwen/llama.cpp visual analysis.
- Build motion and temporal transition outputs.
- Run resumable visual campaigns over archived video.

### Retrieval and research inputs

- Split extracted material into persistent passages.
- Run basic lexical search while retaining source/object identifiers.
- Search the archive using versioned JUFE trigger terms.
- Import structured scripture/corpus material.
- Generate versioned name/text fingerprints and a canonical representation.

## 6. Current interfaces

### Installation

From the repository root on the intended Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

The package currently requires Python 3.14 or newer and declares `crawlee[beautifulsoup]`, `pypdf`, and `yt-dlp` as Python dependencies. Particular workflows also use external executables:

- `ffmpeg` and `ffprobe`
- `whisper-cli`
- `qpdf`
- `llama-cli`

### First checks

```bash
python -m warrigal.doctor
python -m warrigal.archive_health
python -m unittest discover -s tests -v
```

Use `python -m warrigal.archive_health --verify-hashes` only when a full byte-for-byte archive check is intentionally required.

### User interfaces

```bash
python -m warrigal.source_panel
python -m warrigal.name_calculator_panel
python -m warrigal.cli --help
```

The source panel creates and runs the same workflow plans exposed through `plan-source`. Inventory/review actions must not silently acquire an entire source.

## 7. Machine-specific configuration

Copy `warrigal.local.toml.example` to `warrigal.local.toml` and configure only the paths and tools used on that machine. The live local TOML is intentionally ignored by Git.

On Liam's Mac, `workspace` and `archive` may be symbolic links into:

```text
~/Desktop/INFORMATION_ARCHIVE
```

The intended external runtime location is:

```text
~/Desktop/INFORMATION_ARCHIVE/SYSTEM/WARRIGAL/runtime
```

Do not replace these links, move the archive, rewrite paths, or commit personal absolute paths without first checking `python -m warrigal.doctor` and confirming the intended storage boundary with Liam.

## 8. Current research work and priorities

### Immediate operational priority: John Kleinbauer research pipeline

The current priority is to complete and validate the John Kleinbauer YouTube/document pipeline before expanding to later sources. The repository contains:

- A Bunker of Doom semiconductor manifest with 69 bounded resources.
- Provenance connecting that manifest to John Kleinbauer's YouTube research trail.
- A dedicated Bunker of Doom operating guide.
- A controlled batch script and document recovery-queue workflow.
- Current YouTube source-panel examples using the Dutch Uncle John channel.

The next work is to verify the real external checkpoint/database state on Liam's Mac, finish unresolved resources, verify the published collection, and confirm that the related YouTube layers are complete and searchable. Repository code alone cannot establish completion because checkpoints and canonical evidence are deliberately outside Git.

### Current interface work

The source-acquisition panel has recently been consolidated so YouTube, Instagram, and Website actions share deterministic workflow plans with CLI preview. The name calculator panel is also under active operator review. The immediate goal should be usability verification and correction of demonstrated faults, not broad redesign.

### Agreed sequence after John Kleinbauer

1. Return to the radionics webpage/source work.
2. Add Tom and “God's Scrolls” as explicit research sources.
3. Use the resulting archives as groundwork for renewed JUFE research.

## 9. Known limitations and boundaries

- Retrieval currently provides lexical search; grounded synthesis and saved research-run layers are planned rather than complete.
- Live-source success depends on external sites and authentication. Instagram access restrictions cannot be solved solely through internal persistence code.
- Local transcription and visual analysis require separately installed executables and model files.
- Operational campaign completion cannot be inferred from Git because the live database and checkpoints are outside the repository.
- JUFE archive search presently identifies trigger-based passages; it should not be represented as a complete JUFE reasoning or book-analysis engine.
- The name/text fingerprint system is English-first. Multilingual canonicalisation remains later work and must preserve language-specific rules rather than flattening all languages into English assumptions.
- The repository includes domain-specific tools at different maturity levels. New features should not be labelled complete merely because a module or interface exists.

## 10. Collaboration rules

1. Create a branch for each bounded change.
2. State the exact fault, feature, or acceptance criterion before editing.
3. Preserve the archive/database/object-store separation.
4. Never commit credentials, cookies, Instagram sessions, `.env`, model files, archive objects, live databases, or personal machine paths.
5. Do not delete or rewrite canonical objects as a cleanup shortcut.
6. Treat originals and derivatives separately and preserve their relationship.
7. Add or update tests for behavioural changes.
8. Run the complete test suite before requesting review.
9. Inspect the diff and keep unrelated changes out of the branch.
10. Open a pull request; do not push experimental changes directly into Liam's working branch.
11. Describe any data migration separately from code changes and provide a safe rollback or backup requirement.
12. Do not infer scientific or JUFE definitions that have not been supplied.

## 11. Recommended GitHub issues

These should be created as separate, bounded issues rather than one general “work on Warrigal” task.

### Issue 1 — Verify a fresh collaborator installation

**Goal:** Prove that a new collaborator can install the package and run its non-destructive checks from the README.

**Acceptance criteria:**

- Installation succeeds on the collaborator's supported Python environment.
- `python -m warrigal.doctor` runs and distinguishes required from optional components.
- The complete unit-test suite passes, or every environment-related failure is recorded without changing application behaviour to hide it.
- Any missing setup step is added to the README.

### Issue 2 — Audit declared and actual dependencies

**Goal:** Confirm that a fresh installation obtains every required Python package.

**Acceptance criteria:**

- Imports across the application are compared with `pyproject.toml`.
- Runtime-only external tools remain documented as external tools rather than Python dependencies.
- Tests run in a newly created environment.
- Dependency changes are minimal and justified.

### Issue 3 — Verify John Kleinbauer campaign state

**Goal:** Reconcile the external database, object store, manifests, checkpoints, and published files for the John Kleinbauer collection.

**Acceptance criteria:**

- Bunker manifest counts are reconciled with checkpoint states.
- Completed, failed, unsupported, and unattempted resources are reported separately.
- All acquired objects referenced by the campaign exist and pass integrity checks.
- Remaining failures have a recovery classification.
- Publication coverage is verified against canonical archive records.

**Safety:** This begins with read-only checks. No archive deletion or checkpoint reset is permitted.

### Issue 4 — Complete channel-scoped YouTube verification

**Goal:** Confirm that inventory, transcripts, comments, Community posts, and archived-comment indexing remain scoped to the selected channel and resume correctly.

**Acceptance criteria:**

- Each stage can be previewed before execution.
- Re-running completed stages does not duplicate preserved evidence.
- Stage limits behave as documented.
- Search results retain channel, video, comment/post, acquisition, and object identity where applicable.

### Issue 5 — Conduct a source-panel usability pass

**Goal:** Make the existing workflows understandable without redesigning the evidence architecture.

**Acceptance criteria:**

- Every visible action describes whether it discovers, acquires, verifies, indexes, or publishes.
- The planned command is visible before execution.
- Controls prevent accidental unbounded acquisition.
- Demonstrated UI faults receive regression tests.

### Issue 6 — Verify the name calculator end to end

**Goal:** Confirm that the graphical calculator and core calculation code produce the same versioned output.

**Acceptance criteria:**

- Known examples are fixed as regression tests.
- UI output matches the core engine exactly.
- Canonical representation and version identifiers are visible in exported results.
- Collection-opening behaviour is labelled generally if it is not Instagram-specific.

### Issue 7 — Specify the grounded research layer

**Goal:** Define, before implementation, how Warrigal will turn retrieved passages into a saved, auditable research run.

**Acceptance criteria:**

- Inputs, retrieval query, selected passages, citations, model/tool version, output, and timestamps have an explicit record design.
- Claims remain traceable to passage and object identifiers.
- The proposal does not alter canonical source bytes.
- Implementation is deferred until Liam approves the specification.

### Issue 8 — Prepare the radionics source campaign

**Goal:** Define a bounded and reviewable acquisition plan for the next priority source after John Kleinbauer.

**Acceptance criteria:**

- Source boundaries and exclusions are documented.
- Discovery and acquisition are separate stages.
- Expected document/media types and size limits are explicit.
- Checkpoint, archive collection, and publication paths are defined through configuration.

## 12. Suggested GitHub Project board

Create one GitHub Project named **Warrigal Research Suite** and use these statuses:

- **Backlog** — agreed work not yet ready to start.
- **Ready** — sufficiently defined and safe to begin.
- **In progress** — currently assigned work.
- **Review** — pull request or result awaiting verification.
- **Blocked** — requires access, clarification, or an external dependency.
- **Done** — acceptance criteria verified.

Useful fields:

| Field | Values |
|---|---|
| Area | Archive, Web, YouTube, Instagram, Audio/Video, Retrieval, Name Calculator, Interface, Documentation |
| Priority | Immediate, Next, Later |
| Work type | Bug, Verification, Feature, Documentation, Research specification |
| Risk | Read-only, Code-only, External acquisition, Data migration |
| Assignee | Liam or collaborator |

Recommended initial placement:

| Issue | Status | Priority |
|---|---|---|
| Fresh collaborator installation | Ready | Immediate |
| Dependency audit | Ready | Immediate |
| John Kleinbauer campaign verification | Ready after Mac/archive access | Immediate |
| YouTube channel verification | Ready | Immediate |
| Source-panel usability pass | Backlog | Next |
| Name calculator verification | In progress / current review | Immediate |
| Grounded research-layer specification | Backlog | Later |
| Radionics campaign preparation | Backlog | Next |

## 13. What the collaborator needs from Liam

- Invitation to the GitHub repository.
- Agreement on which issue they will handle first.
- Confirmation that they will work through a branch and pull request.
- A supported development environment.
- Only the minimum operational archive access required for the assigned task.
- No Instagram credentials or saved sessions unless an Instagram task specifically requires them and a safe sharing method is agreed.
- Scientific or research intent from Liam where code behaviour depends on meaning rather than mechanics.

## 14. Recommended first assignment

The safest and most informative first assignment is **Verify a fresh collaborator installation**, followed by the **dependency audit**. This tests whether the repository is genuinely transferable without giving immediate write access to the canonical research archive.

Once that is verified, the collaborator can help reconcile the John Kleinbauer campaign with the live Mac archive under a clearly bounded, initially read-only issue.
