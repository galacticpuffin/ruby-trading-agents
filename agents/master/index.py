import json, time, os, random
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOG_PATH = STATE_DIR / "logs.jsonl"
DECISIONS_PATH = STATE_DIR / "pending_decisions.json"

def _load(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

def _save(path, data):
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

def _now():
    return datetime.now().strftime("%Y-%m-%d %I:%M %p")

def _log(agent, level, message):
    try:
        entry = {"ts": time.time(), "agent": agent, "level": level, "message": message}
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

def scan_state():
    out = {
        "agents": _load(STATE_DIR / "runs.json"),
        "portfolio": _load(STATE_DIR / "portfolio.json"),
        "decisions": _load(DECISIONS_PATH),
        "briefing": _load(STATE_DIR / "briefing.json"),
        "banking": _load(STATE_DIR.parent / "config.json").get("banking", {}),
    }
    return out

def propose_integrated_action(state):
    proposals = []
    issues = []
    try:
        runs = state.get("agents", {})
        research = runs.get("research", {})
        dividend = runs.get("dividend", {})
        daytrader = runs.get("daytrader", {})
        it = runs.get("it", {})

        if (research.get("status") or "unknown") == "error":
            issues.append("research_agent_error")
        if (dividend.get("status") or "unknown") == "error":
            issues.append("dividend_agent_error")
        if (daytrader.get("status") or "unknown") == "error":
            issues.append("daytrader_agent_error")
        if (it.get("status") or "unknown") == "error":
            issues.append("it_agent_error")

        if issues:
            proposals.append({
                "type": "agent_health_check",
                "issues": issues,
                "required_approval": True,
                "priority": "high",
                "action": "review_agent_logs_and_restart_if_needed",
            })

        portfolio = state.get("portfolio", {})
        dividend_alloc = portfolio.get("dividend", {})
        daytrader_state = portfolio.get("daytrader", {})
        if isinstance(dividend_alloc, dict) and dividend_alloc.get("monthly_budget") and isinstance(daytrader_state, dict) and daytrader_state.get("cash") is not None:
            proposals.append({
                "type": "rebalance",
                "allocations": [{"symbol": "T", "amount": float(dividend_alloc.get("monthly_budget", 100)), "yield": 6.4, "name": "AT&T"}],
                "monthly_budget": float(dividend_alloc.get("monthly_budget", 100)),
                "required_approval": True,
                "priority": "medium",
                "action": "rebalance_dividend_and_daytrader",
            })

        banking = state.get("banking", {})
        capital_one = banking.get("capital_one", {})
        if isinstance(capital_one, dict) and capital_one.get("enabled") and capital_one.get("access_token"):
            proposals.append({
                "type": "bank_verification",
                "provider": "capital_one",
                "account_id": capital_one.get("account_id"),
                "required_approval": True,
                "priority": "high",
                "action": "verify_capital_one_connection_and_sync",
            })
        elif isinstance(capital_one, dict) and not capital_one.get("enabled"):
            proposals.append({
                "type": "bank_setup",
                "provider": "capital_one",
                "required_approval": True,
                "priority": "medium",
                "action": "enable_capital_one_bank_integration",
            })

        # Propose funding injections for agents below starting cash when bank is enabled
        if isinstance(capital_one, dict) and capital_one.get("enabled") and capital_one.get("access_token"):
            agent_cash_map = {
                "daytrader": portfolio.get("daytrader", {}).get("cash"),
                "gold_stocks": portfolio.get("gold_stocks", {}).get("cash"),
                "oil_stocks": portfolio.get("oil_stocks", {}).get("cash"),
                "gold_bars": portfolio.get("gold_bars", {}).get("cash"),
                "capital": portfolio.get("capital", {}).get("cash"),
                "oil_opportunity": portfolio.get("oil_opportunity", {}).get("cash"),
            }
            for agent_name, cash in agent_cash_map.items():
                if not isinstance(cash, (int, float)) or cash < 100:
                    proposals.append({
                        "type": "capital_injection",
                        "agent": agent_name,
                        "amount": 100,
                        "provider": "capital_one",
                        "required_approval": True,
                        "priority": "medium",
                        "action": "fund_agent_starting_capital",
                    })
    except Exception as e:
        proposals.append({
            "type": "error",
            "detail": str(e),
            "required_approval": True,
            "priority": "high",
            "action": "investigate_master_agent_failure",
        })
    return proposals

def submit_decisions(proposals):
    submitted = []
    data = _load(DECISIONS_PATH)
    queue = data.setdefault("queue", [])
    for p in proposals:
        exists = any(
            d.get("agent") == "master"
            and d.get("type") == p.get("type")
            and d.get("payload") == p
            and d.get("status") == "pending"
            for d in queue
        )
        if exists:
            continue
        fix_id = f"master_{int(time.time()*1000)}_{random.randint(1000,9999)}"
        decision = {
            "id": fix_id,
            "agent": "master",
            "type": p.get("type", "action"),
            "submitted_at": time.time(),
            "status": "pending",
            "payload": p,
        }
        queue.append(decision)
        _save(DECISIONS_PATH, data)
        _log("master", "info", f"submitted decision {fix_id}")
        submitted.append(decision)
    return submitted

def run():
    out = {
        "agent": "MASTER",
        "timestamp": _now(),
        "action": "full_integrated_review",
        "issues": [],
        "proposed_actions": [],
        "status": "completed",
    }
    state = scan_state()
    proposals = propose_integrated_action(state)
    out["issues"] = [p for p in proposals if p.get("type") in ("error", "agent_health_check")]
    submitted = submit_decisions(proposals)
    out["proposed_actions"] = [{"id": d["id"], "type": d["type"]} for d in submitted]
    try:
        from shared.decisions import get_accuracy
        out["accuracy"] = {a: get_accuracy(a) for a in ["research", "dividend", "daytrader", "it", "master", "trumpgov", "capital", "gold_stocks", "gold_bars", "oil_stocks", "oil_opportunity"]}
    except Exception:
        out["accuracy"] = {}
    return out
