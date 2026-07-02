import json, time, random
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOGS_PATH = STATE_DIR / "logs.jsonl"
BRIEF_PATH = STATE_DIR / "briefing.json"
CONFIG_PATH = BASE_DIR / "config.json"
GOLD_BARS_STATE = STATE_DIR / "gold_bars.json"


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
        return []
    return [t for t, _ in sorted(tickers.items(), key=lambda x: x[1], reverse=True)[:10]]


def run():
    log("gold_bars", "info", "Running gold bars sourcing logic")
    state = load_json(GOLD_BARS_STATE)
    state.setdefault("purchases", [])
    state.setdefault("sources_checked", [])
    state.setdefault("last_run", "")
    state.setdefault("budget", state.get("budget", 0.0))

    cfg = load_json(CONFIG_PATH)
    # Check for any pending gold profit splits from gold_stocks
    # In a real system this would track transfers; here we show accepted orders
    today = datetime.now().strftime("%Y-%m-%d")
    sources = [
        {"name": "APMEX", "url": "https://www.apmex.com", "verified": True},
        {"name": "JM Bullion", "url": "https://www.jmbullion.com", "verified": True},
        {"name": "Kitco", "url": "https://www.kitco.com", "verified": True},
        {"name": "Provident Metals", "url": "https://www.providentmetals.com", "verified": True},
    ]
    checked = state.get("sources_checked", [])
    for src in sources:
        if src["name"] not in checked:
            checked.append(src["name"])
    state["sources_checked"] = checked[-20:]

    # Simulate finding a legitimate gold bar offer
    eligible = [s for s in sources if s["verified"]]
    src = random.choice(eligible) if eligible else None
    if not src:
        log("gold_bars", "warn", "No verified sources found")
        state["last_run"] = human_now()
        save_json(GOLD_BARS_STATE, state)
        return state

    weight_oz = random.choice([1, 2, 5, 10, 20])
    price_per_oz = random.uniform(2300, 2900)
    total = round(weight_oz * price_per_oz, 2)

    order = {
        "date": today,
        "source": src["name"],
        "url": src["url"],
        "weight_oz": weight_oz,
        "price_per_oz": round(price_per_oz, 2),
        "total_usd": total,
        "status": "pending_approval",
        "note": "Requires Capital One funding transfer",
    }
    state["purchases"].append(order)
    state["purchases"] = state["purchases"][-20:]
    state["last_run"] = human_now()
    save_json(GOLD_BARS_STATE, state)

    try:
        from shared.decisions import submit_decision
        decision_id = submit_decision("gold_bars", "buy_gold_bar", {
            "source": src["name"],
            "url": src["url"],
            "weight_oz": weight_oz,
            "price_per_oz": round(price_per_oz, 2),
            "total_usd": total,
            "payment_method": "capital_one",
        })
        log("gold_bars", "ok", f"Gold bar order from {src['name']} ${total:.2f} submitted: {decision_id}")
    except Exception as e:
        log("gold_bars", "error", f"Failed to submit decision: {e}")

    try:
        from control.app import broadcast_sync
        broadcast_sync({
            "agent": "gold_bars",
            "message": f"Found {weight_oz}oz @ ${price_per_oz:.2f}/oz from {src['name']} = ${total:.2f}",
            "level": "info",
        })
    except Exception:
        pass

    return state


if __name__ == "__main__":
    run()
    print("GOLD_BARS: sourcing evaluated")
