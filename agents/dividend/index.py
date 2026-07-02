import json, time, random
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
SCRIPT_DIR = Path(__file__).resolve().parent

FOLIO_PATH = STATE_DIR / "portfolio.json"
BRIEF_PATH = STATE_DIR / "briefing.json"
LOGS_PATH = STATE_DIR / "logs.jsonl"
CONFIG_PATH = BASE_DIR / "config.json"

UNIVERSE = {
    "high_yield_dividends": [
        {"symbol":"SCHD","name":"Schwab US Dividend Equity","yield":3.5,"category":"ETF"},
        {"symbol":"VYM","name":"Vanguard High Dividend","yield":3.2,"category":"ETF"},
        {"symbol":"JEPI","name":"JPMorgan Equity Premium Income","yield":7.8,"category":"ETF"},
        {"symbol":"JEPQ","name":"JPMorgan Nasdaq Equity Premium","yield":9.5,"category":"ETF"},
        {"symbol":"DIVO","name":"Amplify CWS Dividend Enhanced","yield":5.8,"category":"ETF"},
        {"symbol":"O","name":"Realty Income","yield":5.6,"category":"REIT"},
        {"symbol":"T","name":"AT&T","yield":6.4,"category":"TELECOM"},
        {"symbol":"VZ","name":"Verizon","yield":7.0,"category":"TELECOM"},
        {"symbol":"KO","name":"Coca-Cola","yield":3.1,"category":"CONSUMER"},
        {"symbol":"PEP","name":"PepsiCo","yield":2.9,"category":"CONSUMER"},
        {"symbol":"MCD","name":"McDonald's","yield":2.3,"category":"CONSUMER"},
        {"symbol":"NUSI","name":"Nationwide Negative Duration","yield":8.2,"category":"ETF"},
        {"symbol":"QYLD","name":"Global X Nasdaq 100 Covered Call","yield":11.5,"category":"ETF"},
    ]
}

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

def get_briefing():
    data = load_json(BRIEF_PATH)
    return data.get("tickers_mentioned", {})

def score_positions(brief_mentions):
    scored = []
    for p in UNIVERSE["high_yield_dividends"]:
        sym = p["symbol"]
        mention = brief_mentions.get(sym, 0)
        score = p["yield"] * 1.0 + (mention * 2)
        scored.append({**p, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored

def allocate(ranked, monthly_budget):
    allocations = []
    remaining = monthly_budget
    for i, p in enumerate(ranked):
        if i >= 5:
            break
        weight = 1.0 / (i + 1)
        amt = round(monthly_budget * weight / 100.0) * 100.0
        if amt <= 0:
            continue
        if amt > remaining:
            amt = remaining
        allocations.append({"symbol": p["symbol"], "amount": amt, "yield": p["yield"], "name": p["name"]})
        remaining -= amt
        if remaining <= 0:
            break
    return allocations

def run():
    log("dividend", "info", "Running allocation and weekly investment")
    folio = load_json(FOLIO_PATH)
    cfg = load_json(CONFIG_PATH)
    brief = get_briefing()
    ranked = score_positions(brief)
    weekly_budget = cfg.get("dividend", {}).get("weekly_investment_usd", 100)
    allocs = allocate(ranked, weekly_budget)

    # Try weekly broker-funded purchase when linked brokers are available
    brokers = cfg.get("brokers", {})
    linked_brokers = [k for k, v in brokers.items() if v.get("linked")]
    trade_executed = False
    if linked_brokers and allocs:
        sym = allocs[0]["symbol"]
        amt = allocs[0]["amount"]
        folio.setdefault("dividend", {})
        history = folio["dividend"].setdefault("weekly_investments", [])
        history.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "symbol": sym,
            "amount": amt,
            "broker": linked_brokers[0],
            "status": "submitted",
        })
        folio["dividend"]["last_weekly_investment"] = sym
        folio["dividend"]["weekly_investment_amount"] = amt
        folio["dividend"]["annualized_income"] = folio["dividend"].get("annualized_income", 0.0) + (amt * allocs[0]["yield"] / 100.0 / 52.0) * 52
        save_json(FOLIO_PATH, folio)
        log("dividend", "ok", f"Weekly ${amt:.2f} into {sym} via {linked_brokers[0]}")
        trade_executed = True

    # Submit decision for tracking
    try:
        from shared.decisions import submit_decision
        annualized = sum(a["amount"] * (a["yield"]/100) for a in allocs) * 52 if allocs else 0
        decision_id = submit_decision("dividend", "weekly_dividend_investment", {
            "allocations": allocs,
            "weekly_budget": weekly_budget,
            "broker": linked_brokers[0] if linked_brokers else None,
            "annualized_project": annualized,
            "status": "submitted" if trade_executed else "pending_broker_link",
        })
        log("dividend", "info", f"Weekly investment decision submitted: {decision_id}")
    except Exception as e:
        log("dividend", "error", f"Failed to submit weekly investment decision: {e}")
    
    # Fallback tracking if broker not linked
    if not trade_executed:
        folio.setdefault("dividend", {})
        folio["dividend"].update({
            "last_run": human_now(),
            "allocations": allocs,
            "weekly_budget": weekly_budget,
            "annualized_project": sum(a["amount"] * (a["yield"]/100) for a in allocs) * 52,
            "blended_yield": sum(a["yield"] for a in allocs) / max(len(allocs), 1),
        })
        save_json(FOLIO_PATH, folio)
    
    return folio

if __name__ == "__main__":
    run()
    print("DIVIDEND: allocation updated")
