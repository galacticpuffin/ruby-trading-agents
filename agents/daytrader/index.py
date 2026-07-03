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
    entry = {"ts":time.time(),"agent":agent,"level":level,"message":message}
    with open(LOGS_PATH,"a") as f:
        f.write(json.dumps(entry)+"\n")

def get_research_brief():
    data = load_json(BRIEF_PATH)
    tickers = data.get("tickers_mentioned", {})
    if not tickers:
        return ["SPY","QQQ","IWM","SOXX","NVDA","AAPL"]
    ranked = sorted(tickers.items(), key=lambda x: x[1], reverse=True)
    return [t for t,_ in ranked[:10]]

def run():
    log("daytrader", "info", "Running daytrader logic")
    cfg = load_json(CONFIG_PATH)
    folio = load_json(FOLIO_PATH)
    folio.setdefault("daytrader", {})

    budget_cfg = cfg.get("portfolio", {}).get("daytrader_budget", {
        "starting_cash": 100,
        "target_total": 1100,
        "minimum_profit_target": 1000,
        "extra_buffer": 100,
        "reinvestment_amount": 100,
        "reinvest_daily": True,
    })

    cash = folio["daytrader"].get("cash", budget_cfg["starting_cash"])
    start_cash = folio["daytrader"].get("start_cash", budget_cfg["starting_cash"])
    daily_wins = folio["daytrader"].get("daily_wins", 0)
    daily_losses = folio["daytrader"].get("daily_losses", 0)
    max_cash = folio["daytrader"].get("max_cash", start_cash)

    tickers = get_research_brief()
    tr = folio["daytrader"].get("trades", [])
    last_trade_date = tr[-1]["date"] if tr else None
    today = datetime.now().strftime("%Y-%m-%d")

    if folio["daytrader"].get("active_trade") is None and last_trade_date != today:
        sym = tickers[0] if tickers else "SPY"
        pnl = cash * (random.random() * 0.50 - 0.15)
        cash = max(cash + pnl, 1.0)
        if cash > max_cash:
            max_cash = cash

        trade = {
            "date": today,
            "symbol": sym,
            "pnl": round(pnl, 2),
            "cash_after": round(cash, 2),
            "win": pnl >= 0,
        }
        tr.append(trade)
        folio["daytrader"]["trades"] = tr[-100:]

        if budget_cfg.get("reinvest_daily"):
            if cash < budget_cfg["target_total"]:
                reinvest = min(budget_cfg.get("reinvestment_amount", 100), budget_cfg["target_total"] - cash)
                if reinvest > 0:
                    cash += reinvest
                    trade["reinvested"] = round(reinvest, 2)
                    trade["cash_after"] = round(cash, 2)

        try:
            from shared.decisions import submit_decision
            decision_id = submit_decision("daytrader", "trade", {
                "symbol": sym,
                "side": "buy",
                "pnl_estimate": round(pnl, 2),
                "confidence": 1.0,
                "cash_after": round(cash, 2),
                "budget_target": budget_cfg["target_total"],
            })
            log("daytrader", "info", f"Trade decision submitted: {decision_id}")
        except Exception as e:
            log("daytrader", "error", f"Failed to submit decision: {e}")

    folio["daytrader"].update({
        "cash": round(cash, 2),
        "start_cash": start_cash,
        "max_cash": round(max_cash, 2),
        "daily_wins": daily_wins,
        "daily_losses": daily_losses,
        "current_bias": get_research_brief()[0],
        "last_run": human_now(),
        "budget": budget_cfg,
    })

    save_json(FOLIO_PATH, folio)
    log("daytrader", "ok", f"Cash: ${cash:.2f} | Wins:{daily_wins} Losses:{daily_losses} | Max:${max_cash:.2f}")
    progress = round((cash - start_cash) / (budget_cfg["target_total"] - start_cash) * 100, 1)
    log("daytrader", "ok", f"Budget progress: {progress}% toward ${budget_cfg['target_total']}")
    try:
        from shared.core import update_ticker_series
        bias = folio["daytrader"].get("current_bias") or budget_cfg.get("reinvestment_amount")
        if bias:
            update_ticker_series([str(bias)])
    except Exception:
        pass
    return folio

if __name__ == "__main__":
    run()
    print("DAYTRADER: simulation updated")
