# Manifest-Based Acquisition Operating Guide

This guide describes the reusable operating pattern for any bounded,
manifest-driven acquisition campaign — not one specific collection. A
manifest campaign discovers and validates source URLs, acquires a bounded
batch against a persistent checkpoint, preserves original bytes, extracts
searchable passages where supported, publishes verified files, and records
failures in a recovery queue for later, separate investigation.

## Permanent locations (pattern)

Each manifest-driven collection has its own paths under the canonical
information archive, following this pattern:

- Master catalogue: `INFORMATION_ARCHIVE/COLLECTIONS/<collection>/CATALOGUES`
- Readable collection: `INFORMATION_ARCHIVE/COLLECTIONS/<collection>/BUNKERS`
- Warrigal database and checkpoints: `INFORMATION_ARCHIVE/SYSTEM/WARRIGAL/runtime`
- Protected object archive: `INFORMATION_ARCHIVE/SYSTEM/WARRIGAL/archive/objects`

`<collection>` is specific to each campaign and belongs in that campaign's
own manifest and local configuration, not in this general guide.

## Verified workflow

1. Discover and validate source URLs.
2. Acquire a bounded batch using the persistent checkpoint.
3. Preserve original bytes in Warrigal's hashed object store.
4. Extract searchable passages from supported PDFs.
5. Publish verified files into readable branch folders.
6. Record failures in a recovery queue.
7. Retry temporary failures and separately investigate damaged or missing files.

## Recovery classifications

- `complete`: archived, indexed and published.
- `damaged_recoverable`: source bytes exist, but PDF repair is required.
- `missing_search_required`: source returned 404; search for mirrors.
- `alternate_recovered`: replacement found and provenance recorded.
- `temporary_network_failure`: retry through the same checkpoint.
- `access_blocked`: source-access review required.
- `unclassified_failure`: manual diagnostic review required.

## Evidence rule

Never silently replace a damaged original. Preserve the original bytes,
create any repaired copy as a derivative, and record the relationship,
checksums, source URL and repair tool.

## Worked example in this repository

`scripts/run_bunker_document_batch.sh` and `manifests/bunker-semico.json` are
a working instantiation of this pattern against one specific collection's
manifest and checkpoint. Treat them as a reference for how to wire a batch
script to `warrigal.cli acquire-manifest`, `warrigal.publish_manifest_collection`
and `warrigal.document_recovery_queue` for a new collection, not as the only
collection this guide applies to.
