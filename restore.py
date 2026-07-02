#!/usr/bin/env python3
"""Restore latest state backup (for disaster recovery)."""
from pathlib import Path
import tarfile

BASE = Path("/home/clawdette/trading-agents")
BACKUP_DIR = BASE / "backups"
STATE = BASE / "shared" / "state"
files = sorted(BACKUP_DIR.glob("state-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
if not files:
    raise SystemExit("No backups found")
latest = files[0]
print(f"restoring {latest}")
with tarfile.open(latest, "r:gz") as tar:
    tar.extractall(STATE)
print("restore complete")
