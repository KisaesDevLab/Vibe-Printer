#!/usr/bin/env bash
# Operator-run update for a native (non-Docker) install. Pulls the latest code,
# refreshes deps + the admin UI, and restarts the service. No auto-update timers.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Updating Python dependencies"
uv pip install --python .venv -e ".[pdf,cups,usb,access]"
uv pip install --python .venv "sqlcipher3-binary>=0.5" 2>/dev/null || true

echo "==> Rebuilding admin UI"
( cd web && (npm ci || npm install) && npm run build )

echo "==> Restarting service"
sudo systemctl restart vibe-print.service

PORT="${PORT:-8080}"
for _ in $(seq 1 30); do curl -fsS "http://localhost:$PORT/readyz" >/dev/null 2>&1 && break; sleep 1; done
echo "✅ Updated. Status: systemctl status vibe-print   Logs: journalctl -u vibe-print -f"
