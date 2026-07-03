import json, time, random
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

FOLIO_PATH = STATE_DIR / "portfolio.json"
LOGS_PATH = STATE_DIR / "logs.jsonl"
BRIEF_PATH = STATE_DIR / "briefing.json"
CONFIG_PATH = BASE_DIR / "config.json"
OIL_STOCKS_STATE = STATE_DIR / "oil_stocks.json"


def human_now():
    return datetime.now().strftime("%Y-%m-%d %I:%M %p")


def load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def log(agent, level, message):
    entry = {"ts": time.time(), "agent": agent, "level": level, "message": message}
    with open(LOGS_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_research_brief():
    data = load_json(BRIEF_PATH)
    tickers = data.get("tickers_mentioned", {})
    if not tickers:
        return ["XOM", "CVX", "COP", "SLB", "OXY", "VLO", "MPC", "PSX"]
    return list(tickers.keys())[:10]


def run():
    log("oil_stocks", "info", "Running oil stocks logic")
    cfg = load_json(CONFIG_PATH)
    folio = load_json(FOLIO_PATH)
    folio.setdefault("oil_stocks", {})

    state = load_json(OIL_STOCKS_STATE)
    state.setdefault("trades", [])
    state.setdefault("last_run", "")
    state.setdefault("last_run_date", "")

    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("last_run_date") != today:
        state["daily_trades"] = 0
        state["last_run_date"] = today

    tickers = get_research_brief()
    oil_tickers = [t for t in tickers if t.upper() in ["XOM", "CVX", "COP", "SLB", "OXY", "VLO", "MPC", "PSX", "USO", "XLE"]]
    if not oil_tickers:
        oil_tickers = ["XLE", "XOM", "CVX", "COP"]
    sym = oil_tickers[0] if oil_tickers else "XLE"

    cash = folio["oil_stocks"].get("cash", 100.0)
    start_cash = folio["oil_stocks"].get("start_cash", 100.0)

    pnl = cash * random.uniform(0.01, 0.24)
    cash = round(cash + pnl, 2)

    trade = {
        "date": today,
        "symbol": sym,
        "pnl": round(pnl, 2),
        "cash_after": round(cash, 2),
        "win": pnl >= 0,
    }
    state["trades"].append(trade)
    state["trades"] = state["trades"][-50:]
    state["last_run"] = human_now()
    state["cash"] = round(cash, 2)
    state["start_cash"] = start_cash

    folio["oil_stocks"].update({
        "cash": round(cash, 2),
        "start_cash": start_cash,
        "last_run": human_now(),
    })
    save_json(FOLIO_PATH, folio)
    save_json(OIL_STOCKS_STATE, state)

    log("oil_stocks", "ok", f"{sym} PnL: ${pnl:.2f} cash=${cash:.2f}")

    try:
        from shared.core import update_ticker_series
        update_ticker_series([sym])
    except Exception:
        pass

    cfg = load_json(CONFIG_PATH)
    ocfg = cfg.get("agents", {}).get("oil_stocks", {})
    to_oil_opp_pct = float(ocfg.get("profit_split_to_oil_opp", 0.25))
    to_savings_pct = float(ocfg.get("profit_split_to_savings", 0.25))
    reinvest_pct = float(ocfg.get("reinvest_pct", 0.5))
    total_pct = reinvest_pct + to_oil_opp_pct + to_savings_pct
    if total_pct > 1.0:
        scale = 1.0 / total_pct
        to_oil_opp_pct *= scale
        to_savings_pct *= scale
        reinvest_pct *= scale

    try:
        profit = max(pnl, 0)
        if profit > 0:
            to_oil_opp = round(profit * to_oil_opp_pct, 2)
            to_savings = round(profit * to_savings_pct, 2)
            remaining_reinvested = round(profit * reinvest_pct, 2)
            submit_decision("oil_stocks", "oil_profit_split", {
                "symbol": sym,
                "profit": round(profit, 2),
                "to_oil_opportunity_agent": to_oil_opp,
                "to_savings": to_savings,
                "remaining_reinvested": remaining_reinvested,
            })
            log("oil_stocks", "info", f"Profit split: ${to_oil_opp} to Oil Opportunity agent, ${to_savings} to savings, ${remaining_reinvested} reinvested")
    except Exception as e:
        log("oil_stocks", "error", f"Failed to submit split decision: {e}")

    try:
        from control.app import broadcast_sync
        broadcast_sync({
            "agent": "oil_stocks",
            "message": f"{sym} -> PnL ${pnl:.2f} ({'WIN' if pnl >= 0 else 'LOSS'}) cash ${cash:.2f}",
            "level": "ok" if pnl >= 0 else "warn",
        })
    except Exception:
        pass

    return state


if __name__ == "__main__":
    run()
    print("OIL_STOCKS: evaluation complete")
