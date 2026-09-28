# Warrigal Research Suite

Warrigal is a local-first research system for acquiring public evidence,
preserving exact source bytes, recording provenance, extracting searchable
content, and publishing readable research collections.

The immutable object archive and SQLite database are the canonical evidence
store. Published collection folders are readable views of that evidence; they
are not replacements for the archive.

## Current capabilities

- Web-page acquisition and bounded same-site crawling
- Website PDF/ZIP inventory, selection, resumable acquisition and publication
- Recursive local PDF ingestion
- YouTube channel inventories, transcripts, comments and Community posts
- Instagram inventory, resumable acquisition, verification and publication
- Audio/video transcription through whisper.cpp
- Video-frame and local visual-model analysis
- Persistent passage storage and basic lexical search
- Versioned text/name fingerprints and structured corpus import for JUFE research

## Project layout

| Path | Purpose |
|---|---|
| `src/warrigal/` | Warrigal application code |
| `src/warrigal/acquisition/` | Source-specific acquisition workflows |
| `src/warrigal/retrieval/` | Passage creation and search |
| `tests/` | Unit and workflow tests |
| `workspace/warrigal.db` | Default SQLite database path |
| `archive/objects/` | Default content-addressed object-store path |
| `docs/` | Operating and architecture documentation |

On Liam's Mac, `workspace` and `archive` may be symbolic links into the
canonical `INFORMATION_ARCHIVE`. Warrigal Doctor reports the resolved targets.

## Initial setup

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Warrigal also uses local executables for particular workflows:

- `ffmpeg` and `ffprobe` for audio/video processing
- `whisper-cli` for local transcription
- `qpdf` for damaged-PDF repair
- `llama-cli` for configured local visual models

Run the read-only system check before acquisition:

```bash
python -m warrigal.doctor
```

The same check is available through the main CLI:

```bash
python -m warrigal.cli doctor
```

Inspect database/archive coverage without changing evidence:

```bash
python -m warrigal.archive_health
```

Add `--verify-hashes` when a full byte-for-byte integrity pass is required.

`OK` means a component was found. `MISSING` identifies an unavailable path,
package or executable. Optional model/tool checks do not prevent the acquisition
core from operating.

## Configuration

Existing Warrigal defaults remain unchanged. Override them when required with
environment variables:

| Variable | Default |
|---|---|
| `WARRIGAL_ARCHIVE_ROOT` | `~/Desktop/INFORMATION_ARCHIVE` |
| `WARRIGAL_RUNTIME_ROOT` | `$WARRIGAL_ARCHIVE_ROOT/SYSTEM/WARRIGAL/runtime` |
| `WARRIGAL_DATABASE_PATH` | `workspace/warrigal.db` |
| `WARRIGAL_OBJECT_STORE` | `archive/objects` |
| `WARRIGAL_FFMPEG` | `ffmpeg` |
| `WARRIGAL_FFPROBE` | `ffprobe` |
| `WARRIGAL_WHISPER` | `whisper-cli` |
| `WARRIGAL_LLAMA` | `llama-cli` |
| `WARRIGAL_QPDF` | `qpdf` |
| `WARRIGAL_WHISPER_MODEL` | not configured |
| `WARRIGAL_QWEN_MODEL` | not configured |
| `WARRIGAL_QWEN_PROJECTOR` | not configured |

Absolute paths are accepted for tools and models. Warrigal reads this
configuration without creating, moving or deleting archive content.

For persistent settings on one Mac, copy `warrigal.local.toml.example` to
`warrigal.local.toml` and edit the copy. The local file is excluded from Git.
Environment variables override the local TOML values.

See [Architecture](docs/ARCHITECTURE.md) and
[Data lifecycle](docs/DATA_LIFECYCLE.md) for the system boundaries.

For collaborators, read the [Current System Report](docs/CURRENT_SYSTEM_REPORT.md)
and [Future Direction Report](docs/FUTURE_DIRECTION_REPORT.md). The first
records verified progress and open limitations; the second describes planned
research, publishing, coordination and specialist integrations.

## Interfaces

Launch the source-acquisition panel:

```bash
python -m warrigal.source_panel
```

Launch the name calculator:

```bash
python -m warrigal.name_calculator_panel
```

List CLI commands:

```bash
python -m warrigal.cli --help
```

The source panel orchestrates existing command modules. Selecting an inventory
or review action does not automatically acquire every resource; acquisition and
publication remain explicit stages.

Preview the panel's exact plan without running any command:

```bash
python -m warrigal.cli plan-source YouTube \
  "https://www.youtube.com/@DutchUncleJohn" \
  --action "Discover channel inventory"
```

The panel and this read-only preview use the same workflow definition.

## Verification

Run the complete test suite from the project root:

```bash
python -m unittest discover -s tests -v
```

Tests must run against the active Warrigal virtual environment. A missing
Python dependency or system executable should be treated as an environment
failure, not silently interpreted as missing archive data.

## Evidence lifecycle

1. A source is identified.
2. Exact bytes are acquired into the SHA-256 object store.
3. Provenance and acquisition records are written to SQLite.
4. Readable/structured derivatives and passages are created without replacing
   the original evidence.
5. Checkpoints make bounded campaigns resumable.
6. Publication creates verified human-readable collection views.
7. Search operates over persistent passages while retaining source and object
   identifiers.

Do not manually delete object-store files merely because the same document is
visible in a published collection. Multiple source acquisitions may legitimately
refer to one deduplicated object.

## Development rule

New work should be delivered as a bounded Git change with tests. Do not copy
installer builds over the live repository as the normal update method. Before
applying a patch, create a branch; after tests pass, inspect the diff and commit
the verified state.
