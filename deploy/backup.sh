#!/usr/bin/env bash
# Scheduled backup to Backblaze B2 (S3-compatible, Object Lock) — P22.7.
# Run from cron (e.g. hourly). Requires the AWS CLI configured for the B2 S3 endpoint:
#   aws configure set aws_access_key_id    "$B2_KEY_ID"
#   aws configure set aws_secret_access_key "$B2_APP_KEY"
#
# Env:
#   VIBE_PRINT_URL     default http://localhost:8080
#   VIBE_PRINT_SECRET  bearer secret
#   B2_BUCKET          target bucket (create it WITH Object Lock enabled for immutability)
#   B2_ENDPOINT        e.g. https://s3.us-west-004.backblazeb2.com
#   DATA_DIR           host path of the appliance /data volume (for the DB snapshot + assets)
set -euo pipefail

URL="${VIBE_PRINT_URL:-http://localhost:8080}"
SECRET="${VIBE_PRINT_SECRET:?set VIBE_PRINT_SECRET}"
BUCKET="${B2_BUCKET:?set B2_BUCKET}"
ENDPOINT="${B2_ENDPOINT:?set B2_ENDPOINT}"
DATA_DIR="${DATA_DIR:?set DATA_DIR (the host path backing /data)}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PREFIX="vibe-print/${STAMP}"

echo "Requesting consistent DB snapshot ..."
RESP="$(curl -fsS -X POST "$URL/v1/admin/backup/snapshot" -H "Authorization: Bearer $SECRET")"
SNAP_PATH="$(echo "$RESP" | sed -n 's/.*"path"[^"]*"\([^"]*\)".*/\1/p')"
# Map the in-container path to the host data dir.
SNAP_FILE="$DATA_DIR/$(basename "$SNAP_PATH")"
[ -f "$SNAP_FILE" ] || SNAP_FILE="$DATA_DIR/backups/$(basename "$SNAP_PATH")"

echo "Uploading DB snapshot -> s3://$BUCKET/$PREFIX/db.sqlite"
aws --endpoint-url "$ENDPOINT" s3 cp "$SNAP_FILE" "s3://$BUCKET/$PREFIX/db.sqlite"

echo "Syncing assets -> s3://$BUCKET/$PREFIX/assets/"
aws --endpoint-url "$ENDPOINT" s3 sync "$DATA_DIR/assets" "s3://$BUCKET/$PREFIX/assets/"

echo "Backup complete: $PREFIX"
# Object Lock on the bucket makes these objects immutable for the retention window — a
# ransomware/operator-error safety net. Verify periodically with restore.sh (restore drill).
