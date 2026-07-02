import json
import sys
from pathlib import Path

BASE = Path('/home/clawdette/trading-agents')
STATE = BASE / 'shared' / 'state'
CFG = BASE / 'config.json'

AGENT_STATE_MAP = {
    'research': None,
    'dividend': 'portfolio.json',
    'daytrader': 'portfolio.json',
    'capital': 'capital.json',
    'gold_stocks': 'gold_stocks.json',
    'gold_bars': 'gold_bars.json',
    'oil_stocks': 'oil_stocks.json',
    'oil_opportunity': 'oil_opportunity.json',
    'it': None,
    'master': None,
    'trumpgov': 'trumpgov.json',
}


def ensure(path: Path, cash: float, key: str = None):
    if not path.exists():
        data = {"cash": cash, "trades": [], "starting_cash": cash, "status": "initialized"}
        if key:
            data = {key: data}
        path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return True
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    if key and path.name == 'portfolio.json':
        section = data.get(key, {})
        section['cash'] = cash
        section['starting_cash'] = cash
        section.pop('trades', None)
        section.pop('pending_approvals', None)
        section.pop('weekly_investments', None)
        section.pop('purchases', None)
        section.pop('opportunities', None)
        data[key] = section
    else:
        data['cash'] = cash
        data['starting_cash'] = cash
        data.pop('trades', None)
        data.pop('pending_approvals', None)
        data.pop('weekly_investments', None)
        data.pop('purchases', None)
        data.pop('opportunities', None)
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return True


def main():
    if not CFG.exists():
        print('missing config.json')
        sys.exit(1)
    cfg = json.loads(CFG.read_text())
    agents = cfg.get('agents', {})
    updated = []
    for name, agent in agents.items():
        cash = agent.get('starting_cash', 100)
        if cash is None:
            cash = 100
        state_file = AGENT_STATE_MAP.get(name)
        if state_file is None:
            # no dedicated state file
            continue
        path = STATE / state_file
        key = name if path.name == 'portfolio.json' else None
        if ensure(path, cash, key=key):
            updated.append((name, str(path), cash))
    print(f'INIT_COMPLETE updated={len(updated)}')
    for u in updated:
        print(f' {u[0]} -> {u[1]} cash={u[2]}')
    sys.exit(0)


if __name__ == '__main__':
    main()
