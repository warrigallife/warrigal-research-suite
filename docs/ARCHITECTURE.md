# Warrigal Architecture

## Purpose

Warrigal is a local-first evidence system. It separates acquisition from
preservation, interpretation and publication so that later research conclusions
can always be traced back to preserved source material.

## Layers

1. **Acquire** — adapters obtain public web resources, social-source evidence,
   local documents, audio and video. Where a source requires a signed-in
   session to render its content, acquisition drives a dedicated, isolated
   browser profile rather than any personal browsing session, and never
   reads, stores or copies its authentication material.
2. **Preserve** — exact bytes enter the content-addressed object store; SQLite
   records their origin and acquisition event.
3. **Extract** — readable text, transcript units, comments, frames and visual
   observations are derived without replacing original evidence.
4. **Index** — persistent passages provide the current searchable layer.
   Where a source exposes a stable, canonical identifier for an individual
   item, only items that resolve to one are indexed and permalinked;
   anything that only resolves to a provisional or positional identifier is
   preserved as raw evidence but held back from the searchable index until a
   stable identity can be confirmed.
5. **Research** — current lexical search returns evidence; grounded synthesis
   and saved research runs are planned layers.
6. **Publish/use** — verified readable collections and JUFE/name-calculator
   exports consume preserved evidence.

## Sources of truth

| Concern | Source of truth |
|---|---|
| Exact acquired bytes | SHA-256 object store |
| Provenance and relationships | SQLite database |
| Resumable campaign state | Runtime checkpoint files |
| Human-readable copies | Published collection folders |
| Machine-local paths/tools/models | `warrigal.local.toml` or environment overrides |
| Versioned application behavior | Git repository |
| Authenticated session material (cookies/tokens) | Dedicated, isolated acquisition browser profile; never read or copied by Warrigal |

Published folders are projections. Deleting a published copy must not be
treated as deleting canonical evidence. Conversely, copying a file into a
published folder does not register it as archived evidence.

## Primary modules

- `config.py` — one resolved configuration object.
- `doctor.py` — read-only installation diagnostics.
- `archive_health.py` — read-only database/archive integrity reporting.
- `workflows.py` — side-effect-free source action and command plans shared by
  the visual panel and CLI preview.
- `database.py` — schema creation and migrations.
- `repository.py` — persistence boundary for domain records.
- `object_store.py` — immutable content-addressed byte storage.
- `acquisition/` — bounded source adapters and campaigns.
- `retrieval/` — passage construction and current lexical ranking.
- `source_panel.py` — graphical orchestration of acquisition commands.
- `name_calculator.py` and `scripture_import.py` — versioned research
  calculations and corpus inputs.

## Dependency boundary

Python package dependencies belong in `pyproject.toml`. System executables and
model files are discovered through central configuration and reported by
`warrigal doctor`. Source modules should not add new hard-coded personal paths.

## Change discipline

Each upgrade is developed on a Git branch, tested against the complete suite,
reviewed as a bounded diff and committed only after verification. Archive and
runtime data are never included in code commits.
