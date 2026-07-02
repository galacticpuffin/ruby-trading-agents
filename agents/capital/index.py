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
CAPITAL_PATH = STATE_DIR / "capital.json"


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


def get_daytrader_profit():
    folio = load_json(FOLIO_PATH)
    dt = folio.get("daytrader", {})
    return dt.get("cash", 0) - dt.get("start_cash", 0)


def get_research_brief():
    data = load_json(BRIEF_PATH)
    tickers = data.get("tickers_mentioned", {})
    if not tickers:
        return ["SPY", "QQQ", "IWM", "SOXX", "NVDA", "AAPL", "TSLA", "META"]
    ranked = sorted(tickers.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in ranked[:12]]


def run():
    log("capital", "info", "Running capital allocation logic")

    cfg = load_json(CONFIG_PATH)
    capital_cfg = cfg.get("agents", {}).get("capital", {
        "profit_share_pct": 0.25,
        "min_trade_profit": 50,
        "max_daily_trades": 2,
        "interval_minutes": 120,
    })

    portfolio_cfg = cfg.get("portfolio", {}).get("capital_agent", {
        "profit_share_pct": 0.25,
        "min_trade_profit": 50,
    })
    profit_share_pct = capital_cfg.get("profit_share_pct", portfolio_cfg.get("profit_share_pct", 0.25))
    min_trade_profit = capital_cfg.get("min_trade_profit", portfolio_cfg.get("min_trade_profit", 50))

    daytrader_profit = max(get_daytrader_profit(), 0)
    capital_funds = round(daytrader_profit * profit_share_pct, 2)
    state = load_json(CAPITAL_PATH)
    state.setdefault("history", [])
    state.setdefault("trades", [])
    state.setdefault("daily_trades", 0)
    state.setdefault("last_run", "")

    last_run_date = state.get("last_run_date")
    today = datetime.now().strftime("%Y-%m-%d")

    if last_run_date != today:
        state["daily_trades"] = 0
        state["last_run_date"] = today

    if state["daily_trades"] >= capital_cfg.get("max_daily_trades", 2):
        log("capital", "info", "Daily capital trade limit reached; skipping")
        state["last_run"] = human_now()
        save_json(CAPITAL_PATH, state)
        return state

    tickers = get_research_brief()
    sym = tickers[0] if tickers else "SPY"

    est_profit = round(capital_funds * (1.5 + random.random() * 5.0), 2)

    if est_profit < min_trade_profit:
        log("capital", "info", f"Estimated profit ${est_profit:.2f} below threshold ${min_trade_profit:.2f}; skipping")
        state["last_run"] = human_now()
        save_json(CAPITAL_PATH, state)
        return state

    trade = {
        "date": today,
        "symbol": sym,
        "capital_deployed": capital_funds,
        "est_profit": est_profit,
        "min_target": min_trade_profit,
        "profit_share_pct": profit_share_pct,
        "source_profit": daytrader_profit,
        "result": "pending",
    }
    state["trades"].append(trade)
    state["trades"] = state["trades"][-20:]
    state["daily_trades"] += 1
    state["last_run"] = human_now()
    save_json(CAPITAL_PATH, state)

    try:
        from shared.decisions import submit_decision
        decision_id = submit_decision("capital", "trade", {
            "symbol": sym,
            "side": "buy" if random.random() > 0.35 else "sell",
            "est_profit": est_profit,
            "capital_deployed": capital_funds,
            "min_target": min_trade_profit,
            "source_profit": daytrader_profit,
            "profit_share_pct": profit_share_pct,
        })
        log("capital", "info", f"Capital trade decision submitted: {decision_id}")
    except Exception as e:
        log("capital", "error", f"Failed to submit decision: {e}")

    log("capital", "ok", f"Analyzed {sym}: deployed ${capital_funds:.2f} | est profit ${est_profit:.2f} | target ${min_trade_profit:.2f}")
    state["history"].append({"ts": time.time(), "funds": capital_funds, "est_profit": est_profit, "symbol": sym})
    state["history"] = state["history"][-100:]

    try:
        from control.app import broadcast_sync
        broadcast_sync({"agent": "capital", "message": f"Allocated ${capital_funds:.2f} toward {sym} (target ${est_profit:.2f})", "level": "ok"})
    except Exception:
        pass

    save_json(CAPITAL_PATH, state)
    return state


if __name__ == "__main__":
    run()
    print("CAPITAL: allocation evaluated")
