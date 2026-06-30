#!/usr/bin/env bash
# Native (no Docker) install for Raspberry Pi OS / Debian (arm64 or amd64).
#
# EASIEST — run this ONE line in the Pi's Terminal (do NOT add 'sudo' in front):
#   bash <(curl -fsSL https://raw.githubusercontent.com/KisaesDevLab/Vibe-Printer/main/deploy/install-native.sh)
# It will ask for your password when it needs admin rights.
#
# Sets up: system libs (WeasyPrint/CUPS/USB), Python 3.12 venv (via uv), the built admin UI,
# a systemd service, and a generated secret. Uses the host's system CUPS for office printers.
# Docker remains the primary/tested path; this is the native alternative.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/KisaesDevLab/Vibe-Printer.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/vibe-print}"
RUN_USER="${SUDO_USER:-$(id -un)}"
DATA_DIR="${VIBE_PRINT_DATA_DIR:-/var/lib/vibe-print}"
ENV_FILE="/etc/vibe-print.env"
PORT="${PORT:-8080}"

# Locate the code. If this script lives inside a checkout, use it; otherwise (the curl one-liner)
# clone the repo automatically so the user doesn't have to download anything first.
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || true)"
if [ -n "${SRC_DIR:-}" ] && [ -f "$SRC_DIR/app/main.py" ]; then
  REPO_ROOT="$SRC_DIR"
else
  echo "==> [0/7] Fetching Vibe Print into $INSTALL_DIR"
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends git ca-certificates
  if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only
  else
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  fi
  REPO_ROOT="$INSTALL_DIR"
fi
cd "$REPO_ROOT"
echo "Installing Vibe Print (native) from $REPO_ROOT as user '$RUN_USER' on port $PORT"

echo "==> [1/7] System packages (WeasyPrint, fonts, libusb, CUPS, build deps)"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 \
  fonts-dejavu fonts-liberation libusb-1.0-0 \
  cups cups-client libcups2 libcups2-dev gcc python3-dev \
  curl ca-certificates git

echo "==> [2/7] Node.js (>=20) for the admin UI build"
NODE_MAJOR="$(node -v 2>/dev/null | sed 's/v\([0-9]*\).*/\1/' || echo 0)"
if [ "${NODE_MAJOR:-0}" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

echo "==> [3/7] uv + Python 3.12 venv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
uv venv --python 3.12 .venv

echo "==> [4/7] Python dependencies"
# encrypt extra (sqlcipher3-binary) has no arm64 wheel — install best-effort.
uv pip install --python .venv -e ".[pdf,cups,usb,access]"
uv pip install --python .venv "sqlcipher3-binary>=0.5" 2>/dev/null \
  || echo "    (SQLCipher-at-rest unavailable on this arch — host/volume encryption is the alternative)"

echo "==> [5/7] Build the admin UI into app/static"
( cd web && (npm ci || npm install) && npm run build )

echo "==> [6/7] Data dir, secret, CUPS/USB group membership"
sudo mkdir -p "$DATA_DIR"
sudo chown "$RUN_USER" "$DATA_DIR"
sudo usermod -aG lp,lpadmin,plugdev "$RUN_USER" || true   # CUPS admin + USB access
if [ ! -f "$ENV_FILE" ]; then
  SECRET="$(head -c 36 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 48)"
  printf 'VIBE_PRINT_SECRET=%s\nVIBE_PRINT_DATA_DIR=%s\n' "$SECRET" "$DATA_DIR" | sudo tee "$ENV_FILE" >/dev/null
  sudo chmod 600 "$ENV_FILE"
  echo "    generated $ENV_FILE with a new secret"
else
  echo "    keeping existing $ENV_FILE (secret unchanged)"
fi

echo "==> [7/7] systemd service"
sudo tee /etc/systemd/system/vibe-print.service >/dev/null <<UNIT
[Unit]
Description=Vibe Print — LAN print routing gateway
After=network-online.target cups.service
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$REPO_ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$REPO_ROOT/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now vibe-print.service

echo "Waiting for readiness…"
for _ in $(seq 1 30); do curl -fsS "http://localhost:$PORT/readyz" >/dev/null 2>&1 && break; sleep 1; done

echo
echo "✅ Vibe Print is running (native)."
echo "   URL:    http://$(hostname -I | awk '{print $1}'):$PORT   (admin UI at /admin)"
echo "   Secret: $(sudo grep -oE 'VIBE_PRINT_SECRET=.*' "$ENV_FILE" | cut -d= -f2-)"
echo "   Logs:   journalctl -u vibe-print -f"
echo "   Update: bash $REPO_ROOT/deploy/update-native.sh"
echo
echo "Office printers use the Pi's system CUPS — add queues with the CUPS web UI"
echo "(http://localhost:631) or 'lpadmin', then register them as type 'cups' in Vibe Print."
echo "If you just got added to the lp/lpadmin groups, log out/in (or reboot) for it to take effect."
