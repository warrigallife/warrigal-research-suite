#!/usr/bin/env bash

set -uo pipefail

BATCH_SIZE="${1:-20}"
MAX_BYTES="${2:-26214400}"

PROJECT_ROOT="$HOME/Desktop/WARRIGAL RESEARCH SUITE"
COLLECTION_ROOT="$HOME/Desktop/INFORMATION_ARCHIVE/COLLECTIONS/JOHN_KLEINBAUER"
MANIFEST="$COLLECTION_ROOT/CATALOGUES/bunker-of-doom-acquisition-manifest.json"
CHECKPOINT="$PROJECT_ROOT/workspace/bunker-of-doom-acquisition.checkpoint.json"
OUTPUT_ROOT="$COLLECTION_ROOT/BUNKERS"
RECOVERY_JSON="$COLLECTION_ROOT/CATALOGUES/bunker-of-doom-document-recovery-queue.json"
RECOVERY_MD="$COLLECTION_ROOT/CATALOGUES/bunker-of-doom-document-recovery-queue.md"
LOG="$PROJECT_ROOT/workspace/bunker-of-doom-acquisition.log"

cd "$PROJECT_ROOT" || exit 1

printf '\n=== BUNKER DOCUMENT ACQUISITION ===\n'
echo "BATCH SIZE: $BATCH_SIZE"
echo "MAXIMUM RESOURCE BYTES: $MAX_BYTES"

python -m warrigal.cli acquire-manifest \
  "$MANIFEST" \
  --checkpoint "$CHECKPOINT" \
  --max-resources "$BATCH_SIZE" \
  --max-resource-bytes "$MAX_BYTES" \
  --retry-failures 2 \
  --retry-delay-seconds 3 \
  --read-timeout 180 \
  2>&1 | tee -a "$LOG"

ACQUISITION_STATUS=$?

printf '\n=== PUBLISHING READABLE ORIGINALS ===\n'

python -m warrigal.publish_manifest_collection \
  "$MANIFEST" \
  --checkpoint "$CHECKPOINT" \
  --output-root "$OUTPUT_ROOT" \
  2>&1 | tee -a "$LOG"

PUBLICATION_STATUS=$?

printf '\n=== REFRESHING RECOVERY QUEUE ===\n'

python -m warrigal.document_recovery_queue \
  "$MANIFEST" \
  --checkpoint "$CHECKPOINT" \
  --json-output "$RECOVERY_JSON" \
  --markdown-output "$RECOVERY_MD" \
  2>&1 | tee -a "$LOG"

RECOVERY_STATUS=$?

printf '\n=== BUNKER BATCH COMPLETE ===\n'
echo "ACQUISITION STATUS: $ACQUISITION_STATUS"
echo "PUBLICATION STATUS: $PUBLICATION_STATUS"
echo "RECOVERY STATUS: $RECOVERY_STATUS"
echo "CHECKPOINT: $CHECKPOINT"
echo "LOG: $LOG"
echo "READABLE COLLECTION: $OUTPUT_ROOT"

if [ "$PUBLICATION_STATUS" -ne 0 ] ||
   [ "$RECOVERY_STATUS" -ne 0 ]; then
    exit 1
fi

exit "$ACQUISITION_STATUS"
