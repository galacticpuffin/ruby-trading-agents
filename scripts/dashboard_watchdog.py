#!/bin/bin python3
import time
import urllib.request
import os
import subprocess
from pathlib import Path

PORT = 8080
URL = 'http://127.0.0.1:8080/api/healthz'
BASE = Path('/home/clawdette/trading-agents')
VENV_PY = str(BASE / '.venv' / 'bin' / 'python3')
APP = str(BASE / 'control' / 'app.py')
LOG_OUT = BASE / 'shared' / 'state' / 'dashboard.out.log'
LOG_ERR = BASE / 'shared' / 'state' / 'dashboard.err.log'


def alive():
    try:
        with urllib.request.urlopen(URL, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start():
    if alive():
        return
    # kill any stale if present
    try:
        subprocess.run(['pkill', '-f', f'tcp:{PORT}'], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except Exception:
        pass
    time.sleep(0.3)
    LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
    out = LOG_OUT.open('a')
    err = LOG_ERR.open('a')
    try:
        p = subprocess.Popen([VENV_PY, APP], cwd=str(BASE), stdout=out, stderr=err, close_fds=True)
        for _ in range(20):
            if alive():
                return p
            time.sleep(0.5)
        return p
    except Exception:
        return None


def main():
    import sys
    # immediate start
    start()
    print('watchdog active')
    while True:
        time.sleep(20)
        start()


if __name__ == '__main__':
    main()
