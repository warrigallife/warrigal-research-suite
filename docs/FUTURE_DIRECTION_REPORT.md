# Warrigal Research Suite — Future Direction

**Direction as of:** 29 September 2026  
**Owner of priorities and acceptance:** Liam McIlmurray

Warrigal is intended to grow from evidence acquisition into a research environment where source material remains traceable while people and agents investigate it, organise projects and produce publications. The preserved archive remains the source of evidence; interpretations, analyses and publications link back to it.

## Development path

| Stage | Intended result | Present state |
|---|---|---|
| Finish the active collector | An audited `@TFJ7` Community-comment corpus with stable identities, parent links, reply coverage and explicit completeness limits | Collector code pushed; four older canonical passages need attribution repair; full campaign pending |
| Make the project legible | Current status, architecture, operating instructions and bounded contribution tasks on GitHub | These reports are an initial step; fuller contributor workflow remains planned |
| Complete priority corpora | John Kleinbauer, radionics sources, Tom F. Jennings and God's Scrolls material available for source-grounded retrieval | Acquisition is uneven across sources; each corpus needs its own audit |
| Research intelligence | Extract claims, definitions, entities, equations and relationships; compare support, conflict and uncertainty against cited passages | Planned, not an implemented claim-verification engine |
| Publishing | Generate reports, ebooks, talks, carousels, websites and presentations from selected, versioned evidence | Planned; Designrr is a capability reference, not a dependency |
| Project coordination | Track goals, jobs, evidence requests, contributors, reviews and decisions linked to archive objects and Git changes | Planned; Build Power is a capability reference, not a dependency |
| Specialist integrations | Narrow interfaces to JUFE, multilingual name/word-to-digit tools, the Sequence Laboratory, Audio Generator and later visual or geospatial tools | Separate or exploratory tracks; no production interchange contract yet |

## Research design

A future analysis should distinguish **source observation**, **extraction**, **inference** and **publication**. A claim map should link every supporting or conflicting statement to preserved passages and original objects. Suggested relationships may be hypotheses; they should not be promoted to verified facts without a recorded evaluation. This allows the same corpus to support research questions, reading lists, literature comparisons and later publications without losing provenance.

The publishing layer should retain the evidence selection and citations for each output, so a report or talk can be revised when sources change. A project layer should connect tasks to the relevant evidence and Git changes rather than becoming an isolated planning board.

## Warrigal and JUFE

Warrigal acquires and organises source evidence. JUFE evaluates defined sequences or relational inputs through its own runtime and manuscript framework. A future adapter could pass a selected, explicitly defined representation to JUFE, then store the result as a **derived artefact** linked to the original inputs. JUFE output would not replace archived source evidence, and Warrigal would not silently treat it as an observed fact.

## Collaboration model

| Role | Responsibility |
|---|---|
| Liam | Sets purpose, priorities, access and final acceptance |
| Reid | Warrigal implementation, focused tests and operational reporting |
| Nora | Independent, read-only review of diffs, tests, scope and data protection |
| Dana | JUFE runtime implementation and focused tests |
| Human contributors | Propose bounded changes, tests and documentation through reviewable Git work |

Agent roles should remain stable even when an execution model reaches a session limit. A later model-neutral task checkpoint could preserve approved scope, Git state, completed and remaining steps, tests and protected paths so a bounded task can resume without confusing role ownership.

## Useful contribution packages

- Verify module maps and operating instructions against the code.
- Add synthetic parser fixtures and focused regression tests.
- Prototype read-only search views against fixtures.
- Propose an adapter contract covering access, stable IDs, provenance, authentication and completeness before writing a new source adapter.
- Prototype publishing with exported sample evidence rather than the canonical archive.
- Review dependency licences, telemetry, costs and rollback paths.

External projects such as jCodeMunch, Hindsight, Paperclip, LangFuzz, The Gibson and RuVector KGE are **candidates for study or isolated pilots**, not installed Warrigal components. OSIRIS is a separate future geospatial and open-source intelligence learning track. Flutter is a possible later interface once stable Warrigal APIs exist.

See the [Current System Report](CURRENT_SYSTEM_REPORT.md) for what is implemented and what remains open today.
