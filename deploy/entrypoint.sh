#!/usr/bin/env bash
set -euo pipefail

# Start in-container CUPS bound to localhost only (no remote admin surface; P6.1 / P30.3).
if command -v cupsd >/dev/null 2>&1; then
  # cupsd.conf shipped in the image restricts Listen to 127.0.0.1:631.
  cupsd || echo "cupsd failed to start (CUPS printers will be unavailable)" >&2
fi

exec "$@"
