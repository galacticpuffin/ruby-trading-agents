import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE = Path('/home/clawdette/trading-agents')
HOST = 'http://127.0.0.1:8080'
CREDS = ('operator', 'Tacostand86!')


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
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.code, r.read().decode('utf-8', errors='ignore')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='ignore')
    except Exception as e:
        return None, str(e)


def login():
    code, body = fetch('/api/login', data={'username': CREDS[0], 'password': CREDS[1]}, method='POST')
    if code == 200:
        try:
            obj = json.loads(body)
            return obj.get('token')
        except Exception:
            return None
    return None


def main():
    print('BOOT: virtual lab runner')
    token = login()
    if not token:
        print('FAIL login failed')
        sys.exit(1)

    checks = []

    code, body = fetch('/', token=token)
    checks.append(('root_loads', code == 200 and 'OPERATOR // CONTROL CENTER' in body, f'code={code}'))

    code, _ = fetch('/api/status', token=token)
    checks.append(('api_status', code == 200, f'code={code}'))

    code, _ = fetch('/api/decisions', token=token)
    checks.append(('decisions_api', code == 200, f'code={code}'))

    code, _ = fetch('/api/integrations', token=token)
    checks.append(('integrations_api', code == 200, f'code={code}'))

    code, _ = fetch('/api/metrics', token=token)
    checks.append(('metrics_api', code == 200, f'code={code}'))

    code, _ = fetch('/api/logs', token=token)
    checks.append(('logs_api', code == 200, f'code={code}'))

    code, _ = fetch('/api/gold', token=token)
    checks.append(('gold_api', code == 200, f'code={code}'))

    code, _ = fetch('/api/oil', token=token)
    checks.append(('oil_api', code == 200, f'code={code}'))

    code, _ = fetch('/api/politics', token=token)
    checks.append(('politics_api', code == 200, f'code={code}'))

    code, body = fetch('/api/run/it', token=token, data={}, method='POST')
    checks.append(('it_run', code == 200, f'code={code}'))
    result = {}
    try:
        result = json.loads(body).get('result') or {}
    except Exception:
        pass
    checks.append(('it_cyber_issues', isinstance(result, dict) and 'cyber_issues' in (result.get('learning') or {}), 'present=learning'))

    # security checks
    cfg = json.loads((BASE / 'config.json').read_text())
    missing = [n for n, a in cfg.get('agents', {}).items() if 'starting_cash' not in a and n != 'trumpgov']
    checks.append(('starter_cash', len(missing) == 0, f'missing={missing}'))

    source = (BASE / 'control/cmd_router.py').read_text(encoding='utf-8', errors='ignore')
    checks.append(('shell_whitelist', 'allowed = {"ls"' in source or 'allowed_prefixes' in source, 'strict whitelist'))

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    score = (passed / total) * 100 if total else 0.0
    print(f'LAB_ROUND {passed}/{total} = {score:.1f}%')
    for name, ok, detail in checks:
        print(f' {"PASS" if ok else "FAIL"} {name}: {detail}')
    sys.exit(0 if score >= 99 else 1)


if __name__ == '__main__':
    main()
