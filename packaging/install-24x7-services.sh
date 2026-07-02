#!/bin/bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DASH="${BASE_DIR}/packaging/trading-dashboard.service"
UNIT_DAEMON="${BASE_DIR}/packaging/trading-agents-daemon.service"

if [ ! -f "$UNIT_DASH" ] || [ ! -f "$UNIT_DAEMON" ]; then
  echo "Missing service files in packaging/" >&2
  ls -la "$BASE_DIR/packaging/" 2>/dev/null || true
  exit 1
fi

for unit in trading-dashboard.service trading-agents-daemon.service; do
  src="${BASE_DIR}/packaging/${unit}"
  dest="/etc/systemd/system/${unit}"
  echo "Installing ${unit}..."
  sudo cp "$src" "$dest"
  sudo chown root:root "$dest"
  sudo chmod 644 "$dest"
  sudo systemctl daemon-reload
  sudo systemctl enable --now "$unit"
  sleep 2
  sudo systemctl status "$unit" --no-pager || true
  echo "---"
done

echo "Verifying runtime..."
ss -ltnp | grep ':8080' || true
ps -ef | grep -E '(start-ui|daemon)' | grep -v grep || true
