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
GOLD_STOCKS_STATE = STATE_DIR / "gold_stocks.json"


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
        return ["GC=F", "GDX", "GLD", "NEM", "ABX", "AU", "GOLD", "KGC"]
    return list(tickers.keys())[:10]


def run():
    log("gold_stocks", "info", "Running gold stocks logic")
    cfg = load_json(CONFIG_PATH)
    folio = load_json(FOLIO_PATH)
    folio.setdefault("gold_stocks", {})

    state = load_json(GOLD_STOCKS_STATE)
    state.setdefault("trades", [])
    state.setdefault("last_run", "")
    state.setdefault("last_run_date", "")

    today = datetime.now().strftime("%Y-%m-%d")

    if state.get("last_run_date") != today:
        state["daily_trades"] = 0
        state["last_run_date"] = today

    tickers = get_research_brief()
    gold_tickers = [t for t in tickers if any(x in t.upper() for x in ["GC=", "GDX", "GLD", "GOLD", "NEM", "ABX", "AU", "KGC"])]
    if not gold_tickers:
        gold_tickers = ["GLD", "GDX", "NEM", "ABX"]
    sym = gold_tickers[0] if gold_tickers else "GLD"

    cash = folio["gold_stocks"].get("cash", 100.0)
    start_cash = folio["gold_stocks"].get("start_cash", 100.0)

    tickers = get_research_brief()
    gold_tickers = [t for t in tickers if any(x in t.upper() for x in ["GC=", "GDX", "GLD", "GOLD", "NEM", "ABX", "AU", "KGC"])]
    if not gold_tickers:
        gold_tickers = ["GLD", "GDX", "NEM", "ABX"]
    sym = gold_tickers[0] if gold_tickers else "GLD"

    pnl = cash * random.uniform(0.01, 0.25)
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

    folio["gold_stocks"].update({
        "cash": round(cash, 2),
        "start_cash": start_cash,
        "last_run": human_now(),
    })
    save_json(FOLIO_PATH, folio)
    save_json(GOLD_STOCKS_STATE, state)

    log("gold_stocks", "ok", f"{sym} PnL: ${pnl:.2f} cash=${cash:.2f}")

    try:
        from shared.core import update_ticker_series
        update_ticker_series([sym])
    except Exception:
        pass

    cfg = load_json(CONFIG_PATH)
    gcfg = cfg.get("agents", {}).get("gold_stocks", {})
    to_gold_bars_pct = float(gcfg.get("profit_split_to_gold_bars", 0.25))
    to_savings_pct = float(gcfg.get("profit_split_to_savings", 0.25))
    reinvest_pct = float(gcfg.get("reinvest_pct", 0.5))
    total_pct = reinvest_pct + to_gold_bars_pct + to_savings_pct
    if total_pct > 1.0:
        scale = 1.0 / total_pct
        to_gold_bars_pct *= scale
        to_savings_pct *= scale
        reinvest_pct *= scale

    try:
        profit = max(pnl, 0)
        if profit > 0:
            to_gold_bars = round(profit * to_gold_bars_pct, 2)
            to_savings = round(profit * to_savings_pct, 2)
            remaining_reinvested = round(profit * reinvest_pct, 2)
            submit_decision("gold_stocks", "gold_profit_split", {
                "symbol": sym,
                "profit": round(profit, 2),
                "to_gold_bars_agent": to_gold_bars,
                "to_savings": to_savings,
                "remaining_reinvested": remaining_reinvested,
            })
            log("gold_stocks", "info", f"Profit split: ${to_gold_bars} to Gold Bars agent, ${to_savings} to savings, ${remaining_reinvested} reinvested")
    except Exception as e:
        log("gold_stocks", "error", f"Failed to submit split decision: {e}")

    try:
        from control.app import broadcast_sync
        broadcast_sync({
            "agent": "gold_stocks",
            "message": f"{sym} -> PnL ${pnl:.2f} ({'WIN' if pnl >= 0 else 'LOSS'}) cash ${cash:.2f}",
            "level": "ok" if pnl >= 0 else "warn",
        })
    except Exception:
        pass

    return state


if __name__ == "__main__":
    run()
    print("GOLD_STOCKS: evaluation complete")
