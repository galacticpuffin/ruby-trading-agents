#!/usr/bin/env python3
"""Backup trading-agents state to a local archive."""
import os, tarfile, time
from pathlib import Path
from datetime import datetime

BASE = Path("/home/clawdette/trading-agents")
STATE = BASE / "shared" / "state"
BACKUP_DIR = BASE / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

def prune_old(max_files=30):
    files = sorted(BACKUP_DIR.glob("state-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[max_files:]:
        try:
            old.unlink()
        except Exception:
            pass

def main():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"state-{stamp}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        for child in STATE.iterdir():
            try:
                tar.add(child, arcname=child.name)
            except Exception:
                pass
    prune_old()
    print(f"backup -> {out}")

if __name__ == "__main__":
    main()
