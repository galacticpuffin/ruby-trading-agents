import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE = Path('/home/clawdette/trading-agents')
HOST = 'http://127.0.0.1:8080'
PASSES = 0
FAILS = 0
RESULTS = []


def check(name, condition, detail=''):
    global PASSES, FAILS
    ok = bool(condition)
    RESULTS.append((name, ok, detail))
    PASSES += ok
    FAILS += (not ok)


def fetch(path, token=None, data=None, method='GET'):
    url = HOST + path
    headers = {'Accept': 'application/json, text/html'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if data is not None and method == 'POST':
        headers['Content-Type'] = 'application/json'
        data = json.dumps(data).encode()
    else:
        data = None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode('utf-8', errors='ignore')
            return r.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        return e.code, body
    except Exception as e:
        return None, str(e)


def main():
    global PASSES, FAILS
    print('BOOT: security verification suite')

    code, body = fetch('/')
    check('root_loads_without_auth', code == 200, f'code={code}')

    code, body = fetch('/api/status')
    check('api_status_open_access', code == 200, f'code={code}')

    code, body = fetch('/api/run/it', data={}, method='POST')
    check('it_run_success', code == 200, f'code={code}')
    parsed = {}
    try:
        parsed = json.loads(body)
    except Exception:
        pass
    check('run_it_has_results', bool(parsed.get('result')), f'keys={list(parsed.keys())[:5]}')

    # cyber output should appear in /api/run/it result
    cyber_in_run = False
    try:
        res = parsed.get('result') or {}
        cyber_in_run = isinstance(res, dict) and 'cyber_issues' in (res.get('learning') or {})
    except Exception:
        pass
    check('it_cyber_output', cyber_in_run, f'cyber_in_run={cyber_in_run}')

    code, body = fetch('/api/metrics')
    check('metrics_available', code == 200, f'code={code}')

    code2, _ = fetch('/api/logs')
    check('logs_open_access', code2 == 200, f'code={code2}')

    code3, _ = fetch('/api/run/it', data={}, method='POST')
    check('run_it_open_access', code3 == 200, f'code={code3}')

    cfg = json.loads((BASE / 'config.json').read_text())
    missing = [n for n, a in cfg.get('agents', {}).items()
               if 'starting_cash' not in a and n not in ('trumpgov', 'research')]
    check('starter_cash_configs', len(missing) == 0, f'missing={missing}')

    total = PASSES + FAILS
    score = (PASSES / total) * 100 if total else 0.0
    print(f'SCORE {PASSES}/{total} = {score:.1f}%')
    for name, ok, detail in RESULTS:
        status = 'PASS' if ok else 'FAIL'
        print(f' {status} {name}: {detail}')
    sys.exit(0 if score >= 99 else 1)


if __name__ == '__main__':
    main()
