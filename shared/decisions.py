import json, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

DECISIONS_PATH = STATE_DIR / "pending_decisions.json"
APPROVED_PATH = STATE_DIR / "approved_decisions.json"
METRICS_PATH = STATE_DIR / "metrics.json"

def load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))

def submit_decision(agent, decision_type, payload, auto_approve=False):
    """Agents call this to queue a decision for operator approval.
    If auto_approve=True, the decision is immediately approved and logged.
    """
    decisions = load_json(DECISIONS_PATH)
    queue = decisions.setdefault("queue", [])
    # Deduplicate: skip if an identical pending decision already exists
    for d in queue:
        if (
            d.get("agent") == agent
            and d.get("type") == decision_type
            and d.get("payload") == payload
            and d.get("status") == "pending"
        ):
            return d["id"]
    decision = {
        "id": f"{agent}_{int(time.time()*1000)}",
        "agent": agent,
        "type": decision_type,
        "payload": payload,
        "status": "pending",
        "submitted_at": time.time(),
        "decided_at": None,
        "operator_action": None,
    }
    queue.append(decision)
    if auto_approve:
        approve_decision(decision["id"], action="auto_approved")
        return decision["id"]
    save_json(DECISIONS_PATH, decisions)
    return decision["id"]

def approve_decision(decision_id, action="approved"):
    decisions = load_json(DECISIONS_PATH)
    queue = decisions.get("queue", [])
    for d in queue:
        if d.get("id") == decision_id:
            d["status"] = "resolved"
            d["decided_at"] = time.time()
            d["operator_action"] = action
            # move to approved log
            approved = load_json(APPROVED_PATH)
            approved.setdefault("history", []).append(d)
            save_json(APPROVED_PATH, approved)
            save_json(DECISIONS_PATH, decisions)
            return True
    return False

def get_pending_decisions():
    decisions = load_json(DECISIONS_PATH).get("queue", [])
    return [d for d in decisions if d.get("status") == "pending"]

def record_metric(agent, metric, value):
    metrics = load_json(METRICS_PATH)
    agent_metrics = metrics.setdefault(agent, {})
    history = agent_metrics.setdefault(metric, [])
    history.append({"ts": time.time(), "value": value})
    # keep last 500
    agent_metrics[metric] = history[-500:]
    metrics[agent] = agent_metrics
    save_json(METRICS_PATH, metrics)

def get_accuracy(agent):
    metrics = load_json(METRICS_PATH)
    agent_metrics = metrics.get(agent, {})
    # simple rolling accuracy from decisions approved/rejected
    decisions = load_json(APPROVED_PATH).get("history", [])
    agent_decisions = [d for d in decisions if d.get("agent") == agent]
    if not agent_decisions:
        return None
    approved = sum(1 for d in agent_decisions if d.get("operator_action") == "approved")
    return approved / max(len(agent_decisions), 1)
