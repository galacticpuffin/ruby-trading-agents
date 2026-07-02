#!/usr/bin/env python3
"""Install systemd units for trading dashboard + daemon on the Pi."""
import os, subprocess, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
UNIT_DIR = Path("/etc/systemd/system")

def write_unit(name, content):
    target = UNIT_DIR / name
    if target.exists():
        print(f"[skip] {name} exists")
        return
    target.write_text(content, encoding="utf-8")
    print(f"[write] {target}")

dashboard_unit = """[Unit]
Description=Trading Dashboard (FastAPI control panel)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/clawdette/trading-agents
ExecStart=/home/clawdette/trading-agents/.venv/bin/python3 /home/clawdette/trading-agents/control/app.py
Restart=on-failure
RestartSec=2
Environment=TRADING_DASH_USER=operator
Environment=TRADING_DASH_PASS=change-me
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

daemon_unit = """[Unit]
Description=Trading Agents Daemon (24/7 scheduler)
After=network-online.target trading-dashboard.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/clawdette/trading-agents
ExecStart=/home/clawdette/trading-agents/.venv/bin/python3 /home/clawdette/trading-agents/daemon.py
Restart=on-failure
RestartSec=2
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

def main():
    if os.geteuid() != 0:
        raise SystemExit("Run as root: sudo python3 packaging/systemd/install.py")
    write_unit("trading-dashboard.service", dashboard_unit)
    write_unit("trading-daemon.service", daemon_unit)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "trading-dashboard.service"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "trading-daemon.service"], check=True)
    print("[done] services installed and started")

if __name__ == "__main__":
    main()
