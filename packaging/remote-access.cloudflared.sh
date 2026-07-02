#!/bin/bash
set -euo pipefail

PI_HOST="${PI_HOST:-192.168.1.81}"
PI_SSH_KEY="${PI_SSH_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE="${PI_USER:-clawdette}@${PI_HOST}"
LOCAL_PORT="${LOCAL_PORT:-8080}"
TUNNEL_NAME="${TUNNEL_NAME:-trading-agents-dashboard}"

echo "[1/3] Ensuring dashboard is running locally on :${LOCAL_PORT}..."
ssh -o BatchMode=yes -o ConnectTimeout=5 "${REMOTE}" "bash -lc 'if ! ss -ltnp | grep -q :${LOCAL_PORT}; then cd /home/clawdette/trading-agents && nohup .venv/bin/python3 start-ui.py > shared/state/start-ui.log 2>&1 & disown; fi'" || true
sleep 3

echo "[2/3] Installing cloudflared (if missing)..."
ssh -o BatchMode=yes -o ConnectTimeout=5 "${REMOTE}" "bash -lc 'command -v cloudflared >/dev/null 2>&1 || (curl -fsSL https://pkg.cloudflare.com/cloudflare/gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null && echo deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null && sudo apt-get update -qq && sudo apt-get install -y -qq cloudflared || true)'" || true

cat <<"EOD"
[3/3] HEADLESS TUNNEL (Quick Tunnel)
Alternative #1:
  ssh ${REMOTE} "bash -lc 'cloudflared tunnel --url http://localhost:${LOCAL_PORT}'"
This prints a trycloudflare.com URL. Press Ctrl+C to stop.

Alternative #2: Named tunnel (persistent URL)
  ssh ${REMOTE} "bash -lc 'cloudflared tunnel create ${TUNNEL_NAME}"
  ssh ${REMOTE} "bash -lc 'cloudflared tunnel route dns ${TUNNEL_NAME} dashboard.example.com'"
  ssh ${REMOTE} "bash -lc 'cat > ~/.cloudflared/${TUNNEL_NAME}.yml <<EOF
tunnel: $(cloudflared tunnel list | grep ${TUNNEL_NAME} | awk "{print \$1}")
credentials-file: ~/.cloudflared/$(cloudflared tunnel list | grep ${TUNNEL_NAME} | awk "{print \$1}").json
ingress:
  - hostname: dashboard.example.com
    service: http://localhost:${LOCAL_PORT}
  - service: http_status:404
EOF"
  ssh ${REMOTE} "bash -lc 'sudo cloudflared service install ${TUNNEL_NAME} && sudo systemctl enable --now cloudflared'"
EOD
