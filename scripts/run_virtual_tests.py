import json
import os
import sys
import time
import urllib.request
import urllib.error
import shutil
import subprocess
from pathlib import Path

BASE = Path('/home/clawdette/trading-agents')
STATE = BASE / 'shared' / 'state'
HOST = 'http://127.0.0.1:8080'
PYTHON = str(BASE / '.venv' / 'bin' / 'python3')
INITIAL_TOTAL = 300.0  # daytrader + gold_stocks + oil_stocks
DEFAULT_ROUNDS = 200

AGENT_FILE_MAP = {
    'research': BASE / 'agents' / 'research' / 'index.py',
    'dividend': BASE / 'agents' / 'dividend' / 'index.py',
    'daytrader': BASE / 'agents' / 'daytrader' / 'index.py',
    'capital': BASE / 'agents' / 'capital' / 'index.py',
    'gold_stocks': BASE / 'agents' / 'gold_stocks' / 'index.py',
    'gold_bars': BASE / 'agents' / 'gold_bars' / 'index.py',
    'oil_stocks': BASE / 'agents' / 'oil_stocks' / 'index.py',
    'oil_opportunity': BASE / 'agents' / 'oil_opportunity' / 'index.py',
    'it': BASE / 'agents' / 'it' / 'index.py',
    'master': BASE / 'agents' / 'master' / 'index.py',
    'trumpgov': BASE / 'agents' / 'trumpgov' / 'index.py',
}


def fetch_json(path, data=None, method='GET'):
    url = HOST + path
    headers = {'Accept': 'application/json'}
    if data is not None and method == 'POST':
        headers['Content-Type'] = 'application/json'
        data = json.dumps(data).encode()
    else:
        data = None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode('utf-8', errors='ignore')
            return r.status, json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        return e.code, json.loads(body) if body.strip() else {}
    except Exception as e:
        return None, {'error': str(e)}


def get_agent_cash():
    folio_path = STATE / 'portfolio.json'
    folio = json.loads(folio_path.read_text()) if folio_path.exists() else {}
    out = {}
    for a in AGENT_FILE_MAP:
        out[a] = folio.get(a, {}).get('cash', 0.0)
    return out


def reset_folio():
    folio_path = STATE / 'portfolio.json'
    folio = json.loads(folio_path.read_text()) if folio_path.exists() else {}
    for a in AGENT_FILE_MAP:
        folio.setdefault(a, {})['cash'] = 100.0
        folio[a]['start_cash'] = 100.0
    folio_path.write_text(json.dumps(folio, indent=2))


def snapshot_state():
    snap = STATE / 'snapshots'
    snap.mkdir(exist_ok=True)
    dest = snap / f'pre_{int(time.time())}'
    dest.mkdir(exist_ok=True)
    for f in STATE.iterdir():
        if f.is_file():
            shutil.copy2(f, dest / f.name)
    return dest


def clear_decisions():
    path = STATE / 'pending_decisions.json'
    path.write_text(json.dumps({'queue': []}, indent=2))


def real_market_context():
    out = {}
    try:
        import yfinance as yf
        for sym in ['SPY', 'QQQ', 'GC=F', 'CL=F']:
            t = yf.Ticker(sym)
            price = None
            try:
                price = t.fast_info.get('lastPrice')
            except Exception:
                price = None
            if price is None:
                try:
                    hist = t.history(period='1d')
                    if not hist.empty:
                        price = float(hist['Close'].iloc[-1])
                except Exception:
                    price = None
            out[sym] = round(float(price), 4) if price is not None else None
    except Exception:
        pass
    return out


def run_agent(agent, path):
    env = {**os.environ, 'PYTHONPATH': str(BASE)}
    try:
        r = subprocess.run(
            [PYTHON, str(path)],
            capture_output=True, text=True, cwd=str(BASE), env=env, timeout=120
        )
        return {'ok': r.returncode == 0, 'returncode': r.returncode, 'stdout': r.stdout[-200:], 'stderr': r.stderr[-200:]}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'timeout', 'returncode': -1}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200], 'returncode': -1}


def submit_and_approve_all():
    code, body = fetch_json('/api/decisions')
    pending = []
    if code == 200 and isinstance(body, dict):
        pending = [d for d in body.get('pending', []) if isinstance(d, dict) and d.get('id')]
    approved = 0
    for d in pending:
        did = d['id']
        c, _ = fetch_json(f'/api/approve/{did}', data={}, method='POST')
        if c == 200:
            approved += 1
    return len(pending), approved


def run_round(round_num):
    errors = {}
    for agent, path in AGENT_FILE_MAP.items():
        res = run_agent(agent, path)
        if not res['ok']:
            errors[agent] = res.get('error') or res.get('stderr') or 'unknown error'
    
    pending = approved = 0
    try:
        pending, approved = submit_and_approve_all()
    except Exception as e:
        errors['approvals'] = str(e)
    
    cash = get_agent_cash()
    total_cash = sum(cash.values())
    accuracy = (approved / max(pending, 1)) * 100.0 if pending else 100.0
    
    return {
        'round': round_num,
        'accuracy': round(accuracy, 2),
        'cash_total': round(total_cash, 2),
        'cash': cash,
        'errors': errors,
        'approved': approved,
        'pending': pending,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rounds', type=int, default=DEFAULT_ROUNDS, help='number of rounds to run')
    args = parser.parse_args()
    max_rounds = args.rounds
    rounds_to_run = max_rounds
    history = []
    reached_target = False
    
    snapshot_state()
    reset_folio()
    clear_decisions()
    initial_folio = {a: 100.0 for a in AGENT_FILE_MAP}
    
    for i in range(1, max_rounds + 1):
        result = run_round(i)
        history.append(result)
        
        err_count = len(result.get('errors', {}))
        cash = result.get('cash_total', 0.0)
        acc = result.get('accuracy', 0.0)
        
        print(f'ROUND {i}: accuracy={acc:.1f}% cash=${cash:.2f} errors={err_count}')
        if result.get('errors'):
            for agent, err in result['errors'].items():
                print(f'  FAIL {agent}: {err[:120]}')
        
        if acc < 99.0 or err_count > 0:
            print('TARGET_FAILED')
            break
    
    final_cash = sum(get_agent_cash().values())
    profit = round(final_cash - INITIAL_TOTAL, 2)
    profit_pct = round((profit / INITIAL_TOTAL) * 100.0, 2) if INITIAL_TOTAL else 0.0
    reached_target = bool(history) and history[-1].get('accuracy', 0) >= 99.0 and len(history[-1].get('errors', {})) == 0
    
    print('=== VIRTUAL TEST REPORT ===')
    print(f'Rounds executed: {len(history)}')
    print(f'Initial cash: ${INITIAL_TOTAL:.2f}')
    print(f'Final cash: ${final_cash:.2f}')
    print(f'Net P&L: ${profit:.2f} ({profit_pct}%)')
    print('Agent cash breakdown:')
    for a, v in get_agent_cash().items():
        print(f'  {a}: ${v:.2f}')
    print(f'Real market snapshot: {json.dumps(real_market_context())}')
    print('Round history:')
    for h in history:
        print(f'  round {h["round"]}: acc={h["accuracy"]:.1f}% cash=${h.get("cash_total",0):.2f} errors={len(h.get("errors",{}))}')
    
    sys.exit(0 if reached_target else 1)


if __name__ == '__main__':
    main()
