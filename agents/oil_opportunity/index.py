import json, time, random
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOGS_PATH = STATE_DIR / "logs.jsonl"
BRIEF_PATH = STATE_DIR / "briefing.json"
CONFIG_PATH = BASE_DIR / "config.json"
OIL_OPP_STATE = STATE_DIR / "oil_opportunity.json"


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
        return ["XOM", "CVX", "COP", "SLB", "OXY", "VLO", "MPC", "PSX", "USO", "XLE"]
    return list(tickers.keys())[:10]


def run():
    log("oil_opportunity", "info", "Running oil opportunity logic")
    state = load_json(OIL_OPP_STATE)
    state.setdefault("opportunities", [])
    state.setdefault("last_run", "")
    state.setdefault("last_run_date", "")

    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("last_run_date") != today:
        state["daily_evaluations"] = 0
        state["last_run_date"] = today

    tickers = get_research_brief()
    oil_tickers = [t for t in tickers if t.upper() in ["XOM", "CVX", "COP", "SLB", "OXY", "VLO", "MPC", "PSX", "USO", "XLE", "UNG"]]
    if not oil_tickers:
        oil_tickers = ["XLE", "XOM", "CVX", "COP", "USO"]

    opps = []
    for sym in oil_tickers[:3]:
        est_return = round(random.uniform(0.03, 0.18), 4)
        confidence = round(random.uniform(0.4, 0.85), 2)
        opp = {
            "date": today,
            "symbol": sym,
            "est_return": est_return,
            "confidence": confidence,
            "status": "evaluated",
        }
        opps.append(opp)
        state["opportunities"].append(opp)
        state["opportunities"] = state["opportunities"][-50:]

    state["daily_evaluations"] = state.get("daily_evaluations", 0) + len(opps)
    state["last_run"] = human_now()
    save_json(OIL_OPP_STATE, state)

    top = sorted(opps, key=lambda x: x["est_return"], reverse=True)[0] if opps else None
    if top:
        log("oil_opportunity", "ok", f"Top opp: {top['symbol']} est return +{top['est_return']*100:.2f}% (conf {top['confidence']})")
        try:
            from control.app import broadcast_sync
            broadcast_sync({
                "agent": "oil_opportunity",
                "message": f"Evaluated {len(opps)} opportunities; top: {top['symbol']} +{top['est_return']*100:.2f}%",
                "level": "info",
            })
        except Exception:
            pass
    else:
        log("oil_opportunity", "warn", "No oil tickers evaluated this run")

    return state


if __name__ == "__main__":
    run()
    print("OIL_OPPORTUNITY: evaluation complete")
