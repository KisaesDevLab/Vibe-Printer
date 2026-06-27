#!/usr/bin/env bash
# vibe upgrade — operator-run, manual update with health-gate + rollback (P27.3).
# No auto-update timers (by design). Usage:
#   ./upgrade.sh <new-image-ref>      e.g. ./upgrade.sh ghcr.io/kisaes/vibe-print@sha256:abc...
#
# Steps: record current image -> pull pinned digest -> compose up -> wait /readyz ->
# rollback to the previous image if readiness fails. The app itself takes a DB backup
# before applying any migration (see app/db.py), so this is a clean forward/rollback.
set -euo pipefail

NEW_IMAGE="${1:?usage: upgrade.sh <new-image-ref (pin to a @sha256 digest)>}"
COMPOSE="docker compose -f docker-compose.yml"
SERVICE="vibe-print"
HEALTH_URL="http://localhost:8080/readyz"
TIMEOUT="${UPGRADE_TIMEOUT:-90}"

current_image() { $COMPOSE images -q "$SERVICE" >/dev/null 2>&1 || true; docker inspect --format '{{.Config.Image}}' "$($COMPOSE ps -q "$SERVICE")" 2>/dev/null || echo ""; }

PREV_IMAGE="$(current_image)"
echo "Current image: ${PREV_IMAGE:-<none>}"
echo "Target image:  $NEW_IMAGE"

echo "Pulling $NEW_IMAGE ..."
docker pull "$NEW_IMAGE"

echo "Applying ..."
VIBE_PRINT_IMAGE="$NEW_IMAGE" $COMPOSE up -d "$SERVICE"

echo "Waiting for readiness (${TIMEOUT}s) ..."
deadline=$(( $(date +%s) + TIMEOUT ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "Healthy. Upgrade complete: $NEW_IMAGE"
    exit 0
  fi
  sleep 2
done

echo "!! Readiness check failed — rolling back to ${PREV_IMAGE:-previous}" >&2
if [ -n "$PREV_IMAGE" ]; then
  VIBE_PRINT_IMAGE="$PREV_IMAGE" $COMPOSE up -d "$SERVICE"
  echo "Rolled back to $PREV_IMAGE" >&2
fi
exit 1
