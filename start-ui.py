#!/usr/bin/env python3
"""Idempotent launcher for the trading control panel."""
import subprocess
import os
import sys
import time

PORT = 8080

def kill_stale_ui():
    cmds = [
        (["ss", "-ltnp"], "ss"),
        (["lsof", "-ti", f"tcp:{PORT}"], "lsof"),
    ]
    pids = set()
    for cmd, tool in cmds:
        try:
            out = subprocess.check_output(cmd, text=True)
            for line in out.splitlines():
                if f":{PORT}" in line:
                    parts = line.strip().split()
                    for p in parts:
                        if p.isdigit() and int(p) > 1:
                            pids.add(p)
        except FileNotFoundError:
            pass
        except subprocess.CalledProcessError:
            pass
    for pid in pids:
        try:
            os.kill(int(pid), 9)
        except ProcessLookupError:
            pass
    if pids:
        time.sleep(0.5)

def port_in_use(port=8080):
    for cmd in (["ss", "-ltnp"], ["lsof", "-ti", f"tcp:{port}"]):
        try:
            out = subprocess.check_output(cmd, text=True)
            if f":{port}" in out:
                return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
    return False


if __name__ == "__main__":
    if port_in_use(PORT):
        print(f"[*] Dashboard already on :{PORT}, skipping launch")
        sys.exit(0)
    kill_stale_ui()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    venv = os.path.join(os.getcwd(), ".venv", "bin", "python3")
    cmd = [venv, "control/app.py"]
    print(f"[*] Starting control panel on :{PORT}")
    os.execvp(cmd[0], cmd)
