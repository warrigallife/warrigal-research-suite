# Warrigal Research Suite — System Audit and Consolidation Roadmap

Audit date: 20 September 2026  
Audited snapshot: `warrigal-audit-current.zip`

## Executive assessment

Warrigal is not a collection of empty experiments. It already has a real local-first foundation for acquisition, immutable preservation, provenance, deduplication, resumable campaigns, publication, passage storage, basic search, media analysis, and the JUFE name-calculator research stream.

The unfinished feeling is also real. Development has progressed source by source and installer by installer faster than the project has been consolidated. The strongest layer is acquisition and preservation. The weakest layer is the actual research loop: ask a question, retrieve the best evidence, inspect it, synthesize a grounded answer, and preserve the answer with citations and reproducibility details.

The correct next move is consolidation, not a rewrite.

## What exists now

| Capability | Current state | Assessment |
|---|---|---|
| Content-addressed object archive | SHA-256 storage and deduplication | Strong foundation; retain |
| Provenance database | Sources, objects, acquisitions, collections, storage locations, passages | Strong foundation; retain |
| Instagram | Inventory, resumable acquisition, verification, publication | Substantial workflow; consolidate |
| YouTube | Channel inventory, transcripts, comments, Community posts, comment indexing, separate media ingestion | Substantial workflow; consolidate and expose media options |
| Websites | Link discovery, bounded crawling, direct document inventory, selection, size ordering, resumable acquisition, section-aware publication | Useful but split across several concepts; clarify in UI |
| PDFs and archives | Text extraction, recursive PDF ingestion, qpdf repair derivative | Useful; add OCR and better parsing |
| Audio/video | Whisper.cpp transcription, frame extraction, Qwen/llama.cpp visual analyses | Real specialist pipeline; external-tool setup is under-documented |
| Search | Passage persistence and deterministic lexical ranking | Prototype-quality; not yet a search engine at archive scale |
| Question answering | No grounded answer synthesis or saved citations | Missing top-level layer |
| Name calculator | Reproducible English custom mapping, source preservation, batch corpus import | Useful v1; language and JUFE mappings deliberately incomplete |
| Graph/relationships | Collections exist, but claims/entities/relationships are not modeled | Future layer, not current capability |

## Verified strengths

1. **Original evidence is preserved before interpretation.** Acquired bytes are stored by hash, and acquisition provenance is recorded separately.
2. **Duplicate bytes are not duplicated in the object store.** Multiple acquisitions can point to one immutable object.
3. **Long-running source workflows are resumable.** Instagram, YouTube and manifest campaigns use checkpoints.
4. **Published folders are views, not the canonical archive.** Website publication verifies object hashes and uses hard links when possible.
5. **Derived evidence is distinguished from originals.** The PDF-repair path preserves the original and records a repaired derivative separately.
6. **The code is test-oriented.** The snapshot contains 50 test modules and 146 discovered unit tests.
7. **The project compiles.** Every Python source and test file in the supplied snapshot passes Python bytecode compilation.

## Confirmed consolidation problems

### 1. The product boundary is unclear

`source_panel.py` is an acquisition launcher, not a Warrigal control centre. Search, research questions, answer generation, archive health, the name calculator and media analysis are separate entry points. That is why the project feels like separate pieces even where the backend is sound.

### 2. The CLI has become a monolith

`src/warrigal/cli.py` is 1,808 lines and dispatches many unrelated workflows. `repository.py` is 786 lines. Both are still workable, but they are now friction points for safe extension and testing.

### 3. Search is an early prototype

Current search loads every passage and scans it in Python. Tokenization is whitespace/punctuation based. Stop words are a small hard-coded list, and stemming covers only three explicit families: `contain`, `study`, and `produce`. Passage chunks are fixed 120-word blocks with no overlap or document structure. There is no SQLite FTS index, BM25 retrieval, semantic retrieval, reranking, query expansion, or source/collection filtering.

### 4. The answer layer does not exist yet

The CLI prints ranked passages and provenance, but it does not create a cited answer, distinguish quotation from inference, compare conflicting sources, or save research runs. The database has no research-question, answer, claim, citation, or model-run records.

### 5. Packaging does not declare the whole runtime

`pyproject.toml` declares Crawlee, pypdf and yt-dlp. The code also directly relies on `certifi`, Tk, and external executables including ffmpeg, whisper.cpp, qpdf and llama.cpp. Some are system tools rather than Python dependencies, but Warrigal needs a single preflight check that reports their status and paths.

### 6. Patch/install history has leaked into the codebase

Two tests load `source_panel.py` and `youtube_channel_workflow.py` from the `tests` directory rather than `src/warrigal`, so they error in the supplied snapshot. Several tests inject fake `warrigal` modules into the global interpreter, which contaminates later tests when the entire suite runs in one process. This is test-harness debt, not evidence that the workflows themselves are absent.

### 7. One name-calculator method is duplicated

`NameCalculatorPanel.export_number_script` is defined twice. Python silently replaces the first definition with the second. The visible behavior is therefore the second implementation only.

### 8. Documentation and architecture records are missing

The top-level README is empty and the supplied `specs` directory is empty. There is one specialist Bunker operating guide, but no authoritative overview of storage, source lifecycles, commands, external dependencies, or the relationship between canonical archive objects and published collections.

### 9. Fixed paths reduce portability

Several modules assume `~/Desktop/INFORMATION_ARCHIVE`, while audio/frame tools include Homebrew paths such as `/opt/homebrew/bin/ffmpeg` and `/opt/homebrew/bin/whisper-cli`. These should become one configuration object with UI-visible health checks.

## Test interpretation

The complete test invocation discovered 146 tests. In this audit container, 27 ended in errors and none produced assertion failures. This is not a valid claim that 27 Warrigal features are broken: the snapshot does not include its macOS virtual environment, and this environment lacks declared/runtime components such as yt-dlp and certifi. The run also exposed the two incorrect test paths and global module-stubbing contamination described above.

Before further feature work, the suite should be made hermetic enough that one command produces a trustworthy green/red result on the Mac.

## Recommended target architecture

Warrigal should remain a small, understandable local system with six explicit layers:

1. **Acquire** — source adapters fetch or import evidence.
2. **Preserve** — immutable objects, provenance, checkpoints and integrity checks.
3. **Extract** — structured text, timestamps, pages, sections, OCR and media observations.
4. **Index** — lexical index first, optional semantic index second.
5. **Research** — questions, retrieval, evidence review, grounded synthesis and citations.
6. **Publish/use** — readable collections, exports, JUFE inputs and software-development outputs.

The GUI should mirror those layers. A URL may be entered immediately, but acquisition scope remains explicitly selectable. “Everything” can remain a preset, never the only path.

## Recommended build order

### Phase 0 — Freeze and prove the baseline

- Put the current project under a clean Git commit/tag.
- Remove installer-build copies from the active source of truth.
- Add one configuration file for archive, database, runtime and model/tool paths.
- Add a `warrigal doctor` command showing Python packages, ffmpeg, qpdf, whisper.cpp, llama.cpp, models, archive paths and database status.
- Repair test imports and isolation; make one test command authoritative.
- Write the system README and data-lifecycle document.

Exit criterion: a fresh checkout can be configured and tested without reconstructing old chat instructions.

### Phase 1 — Build the real search core

- Add SQLite FTS5 as an index over passages and titles.
- Replace fixed word blocks with structure-aware chunks carrying page, section, timestamp and comment/thread metadata.
- Add filters for collection, source type, creator/channel/profile, date and document.
- Return highlighted snippets and stable citation identifiers.
- Add an index rebuild/status command.

Why first: Warrigal already has SQLite and passage records. FTS5 provides a large improvement without introducing a new database service. SQLite documents FTS5 and BM25 ranking in its official reference: [SQLite FTS5](https://www.sqlite.org/fts5.html).

### Phase 2 — Add a grounded question-and-answer workflow

- A question screen with selectable collections and source types.
- Retrieve and display evidence before synthesis.
- Generate an answer only from selected evidence.
- Attach citations to exact passage IDs and source locations.
- Clearly label direct evidence, model inference, uncertainty and conflicts.
- Save the question, retrieval parameters, evidence set, model identity, prompt/version and final answer.

Use the local model runner already present rather than embedding a large framework immediately. Ollama exposes a local embeddings capability if semantic retrieval is later added: [Ollama embeddings](https://docs.ollama.com/capabilities/embeddings). Warrigal can also standardize its existing llama.cpp integration around the maintained server interface: [llama.cpp](https://github.com/ggml-org/llama.cpp).

### Phase 3 — Improve document understanding

- OCR for scanned PDFs and photos.
- Preserve page numbers, headings, tables and image references.
- Add DOCX, PPTX, HTML and common office-document extraction.
- Record extractor name/version and extraction quality.

Evaluate Docling as an extractor behind Warrigal’s own interface rather than allowing it to own the archive model: [Docling documentation](https://docling-project.github.io/docling/).

### Phase 4 — Unify the control centre

Create one Warrigal window with these tabs:

- Sources
- Runs and progress
- Archive health
- Search
- Ask Warrigal
- Collections/publication
- Name calculator/JUFE
- Settings and tool health

Do this after the underlying research flow is stable. A larger GUI built before Phases 0–2 would conceal ambiguity rather than solve it.

### Phase 5 — Add semantic retrieval only when measured

Build a small evaluation set of real questions and expected evidence. Compare FTS5 against hybrid lexical-plus-embedding retrieval. Add embeddings only when they improve measured recall. Keep passage IDs and SQLite as the source of truth even if vectors are stored separately.

### Phase 6 — Coding assistance and research automation

Once cited answers are reliable, expose carefully bounded tools for:

- producing implementation briefs from archived research;
- locating relevant Warrigal modules and tests;
- drafting patches in a separate Git branch;
- running tests and presenting diffs for approval.

Do not let the research model directly mutate the canonical archive or main code branch. Acquisition, research, and coding actions should remain auditable.

## What not to do next

- Do not rewrite Warrigal around a large RAG framework.
- Do not add a vector database before establishing a search evaluation set.
- Do not continue distributing feature installers as the normal development process.
- Do not treat published folders as the canonical archive.
- Do not add more source-specific GUI actions until configuration, tests and workflow state are unified.
- Do not present calculated name values as physical frequencies without an explicit, sourced transform. The current caution in the calculator is correct.

## Immediate implementation slice

The next coherent engineering job is a **Warrigal Foundation Consolidation** change set:

1. Correct the two broken test paths and isolate module mocks.
2. Remove the duplicate calculator method.
3. Add `config.py` and `doctor.py`.
4. Split CLI parser/dispatch by domain without changing commands.
5. Write README plus `docs/ARCHITECTURE.md` and `docs/DATA_LIFECYCLE.md`.
6. Add FTS5 schema migration, index rebuild and search tests.
7. Add a basic Search tab that returns highlighted, source-linked evidence.

That slice gives a stable platform and an immediately better research tool while preserving all existing acquisition work.

## Bottom line

Warrigal already is the beginning of a personal research engine. Its archive and provenance core are more mature than its interface suggests. The project does not need more indiscriminate acquisition or a wholesale replacement. It needs one source of truth, a dependable test/configuration baseline, a proper full-text index, and a citation-preserving research loop. Once those exist, the name calculator, JUFE work, media interpretation and coding assistance can all become clients of the same evidence system instead of separate islands.
