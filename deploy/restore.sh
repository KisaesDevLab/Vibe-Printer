#!/usr/bin/env bash
# Restore a Vibe Print backup from Backblaze B2 (P22.7 restore drill).
#   ./restore.sh <STAMP>     e.g. ./restore.sh 20260627T120000Z
# Restores into DATA_DIR (the host path backing the /data volume). Stop the appliance first.
set -euo pipefail

STAMP="${1:?usage: restore.sh <STAMP>}"
BUCKET="${B2_BUCKET:?set B2_BUCKET}"
ENDPOINT="${B2_ENDPOINT:?set B2_ENDPOINT}"
DATA_DIR="${DATA_DIR:?set DATA_DIR}"
PREFIX="vibe-print/${STAMP}"

echo "This will overwrite $DATA_DIR. Stop the vibe-print container first."
mkdir -p "$DATA_DIR/backups" "$DATA_DIR/assets"

echo "Downloading DB ..."
aws --endpoint-url "$ENDPOINT" s3 cp "s3://$BUCKET/$PREFIX/db.sqlite" "$DATA_DIR/vibe-print.sqlite"
# Remove stale WAL/SHM so the restored DB is authoritative.
rm -f "$DATA_DIR/vibe-print.sqlite-wal" "$DATA_DIR/vibe-print.sqlite-shm"

echo "Downloading assets ..."
aws --endpoint-url "$ENDPOINT" s3 sync "s3://$BUCKET/$PREFIX/assets/" "$DATA_DIR/assets/"

echo "Restore complete from $PREFIX. Start the appliance; migrations are idempotent."
