# Bunker of Doom Acquisition Operating Guide

## Permanent locations

- Master catalogue:
  `INFORMATION_ARCHIVE/COLLECTIONS/JOHN_KLEINBAUER/CATALOGUES`
- Readable collection:
  `INFORMATION_ARCHIVE/COLLECTIONS/JOHN_KLEINBAUER/BUNKERS`
- Warrigal database and checkpoints:
  `INFORMATION_ARCHIVE/SYSTEM/WARRIGAL/runtime`
- Protected object archive:
  `INFORMATION_ARCHIVE/SYSTEM/WARRIGAL/archive/objects`

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
