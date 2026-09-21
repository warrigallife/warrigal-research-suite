# Warrigal Evidence and Data Lifecycle

## 1. Discovery

Discovery identifies candidate URLs or local files. A discovered item is not
necessarily acquired. Website inventories and user selections allow scope to be
reviewed before downloading resource bodies.

## 2. Acquisition

An acquisition records who/what obtained a resource, the method, source,
timestamp, job, node and batch. Repeated acquisitions may legitimately refer to
the same immutable object.

## 3. Preservation and deduplication

Warrigal calculates SHA-256 over exact bytes. One hash has one canonical object
path. If identical bytes are seen again, the object is reused while the new
acquisition provenance is retained.

## 4. Derivation

Text extraction, PDF repair, transcription, passage splitting, frame extraction
and model observations are derivatives. A derivative must record its relationship
to the source object and must never silently replace original bytes.

## 5. Indexing

Readable evidence is stored as passages carrying object, acquisition and source
identifiers. Search results must retain those identifiers so evidence can be
inspected independently of any later interpretation.

## 6. Checkpointing

Runtime inventories and checkpoints make bounded campaigns resumable. They are
operational state, not substitutes for archived objects or database provenance.
Re-running a completed workflow should reuse existing objects and skip completed
work according to its checkpoint contract.

## 7. Publication

Publication creates readable collection trees from verified archived objects.
It may use hard links or verified copies. Publication reports and manifests show
which canonical objects produced the visible files.

## 8. Integrity checks

Use the fast read-only report routinely:

```bash
python -m warrigal.archive_health
```

Use full hashing deliberately because it reads every archived byte:

```bash
python -m warrigal.archive_health --verify-hashes
```

The same operations are available as `python -m warrigal.cli archive-health`.

## 9. Backup boundary

Back up the Git repository and the canonical information archive independently.
The Git repository preserves application behavior; the archive preserves evidence,
the database and runtime state. A complete recovery requires both.

## 10. Deletion rule

Do not delete canonical object files merely because a readable duplicate exists.
Resolve object and acquisition references first. Cleanup tooling must verify the
exact target and report whether recovery remains possible.
