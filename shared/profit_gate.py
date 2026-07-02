import json, time
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

FOLIO_PATH = STATE_DIR / "portfolio.json"
METRICS_PATH = STATE_DIR / "metrics.json"
PROFIT_GATE_PATH = STATE_DIR / "profit_gate.json"

def _load(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}

def _save(path, data):
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

def evaluate_trade_eligibility(symbol, side, qty, estimated_price, expected_pnl, risk_reward):
    """Hard gate for order approval, enforces profitability before submission."""
    reasons = []
    ok = True
    if expected_pnl is None or float(expected_pnl) <= 0:
        ok = False
        reasons.append("non-positive expected PnL")
    try:
        rr = float(risk_reward)
        if rr < 2.0:
            ok = False
            reasons.append(f"risk:reward {rr:.2f} below 2:1")
    except Exception:
        ok = False
        reasons.append("invalid risk:reward")
    try:
        if float(estimated_price) <= 0:
            ok = False
            reasons.append("invalid price")
    except Exception:
        ok = False
        reasons.append("missing price")

    decision = {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "estimated_price": estimated_price,
        "expected_pnl": expected_pnl,
        "risk_reward": risk_reward,
        "eligible": ok,
        "reasons": reasons,
        "ts": time.time(),
        "local_ts": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
    }
    data = _load(PROFIT_GATE_PATH)
    data.setdefault("history", []).append(decision)
    _save(PROFIT_GATE_PATH, data)
    return decision
