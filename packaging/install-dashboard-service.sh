#!/bin/bash
set -euo pipefail

PI_SSH_KEY="${PI_SSH_KEY:-$HOME/.ssh/id_ed25519}"
PI_HOST="${PI_HOST:-192.168.1.81}"
REMOTE="${PI_USER:-clawdette}@${PI_HOST}"
UNIT_SRC="${UNIT_SRC:-/home/clawdette/trading-agents/packaging/trading-dashboard.service}"
UNIT_DEST="/etc/systemd/system/trading-dashboard.service"

if [ ! -f "$UNIT_SRC" ]; then
  echo "Missing unit file at $UNIT_SRC" >&2
  exit 1
fi

ssh -o BatchMode=yes -o ConnectTimeout=5 "${REMOTE}" "bash -lc 'sudo cp ${UNIT_SRC} ${UNIT_DEST} && sudo chown root:root ${UNIT_DEST} && sudo chmod 644 ${UNIT_DEST} && sudo systemctl daemon-reload && sudo systemctl enable --now trading-dashboard && sleep 2 && sudo systemctl status trading-dashboard --no-pager'"
