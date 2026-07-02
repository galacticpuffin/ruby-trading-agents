import json, time, os, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
CONFIG_PATH = BASE_DIR / "config.json"

def _load(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}

def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))

def _now():
    return datetime.now().strftime("%Y-%m-%d %I:%M %p")

def _slack_conf():
    cfg = _load(CONFIG_PATH).get("slack", {})
    return cfg.get("webhook_url", ""), cfg.get("enabled", False)

def _post(text):
    url, enabled = _slack_conf()
    if not enabled or not url:
        return False
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status == 200
    except Exception:
        return False

def alert(agent, message, level="info"):
    entry = {
        "ts": time.time(),
        "agent": agent,
        "level": level,
        "message": message,
        "slack_sent": False,
    }
    try:
        path = STATE_DIR / "slack_queue.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        if level in ("error", "warn", "info"):
            prefix = {"error": "🚨", "warn": "⚠️", "info": "ℹ️"}.get(level, "ℹ️")
            ok = _post(f"{prefix} [{agent}] {message}")
            entry["slack_sent"] = ok
    except Exception:
        pass

def broadcast_decision(decision):
    try:
        d = decision if isinstance(decision, dict) else {}
        text = (
            f"*New Trading Decision*\n"
            f"ID: `{d.get('id', '')}`\n"
            f"Agent: {d.get('agent', '')}\n"
            f"Type: {d.get('type', '')}\n"
            f"Status: {d.get('status', 'pending')}\n"
            f"Time: {_now()}"
        )
        _post(text)
    except Exception:
        pass

def broadcast_approval(decision_id, action):
    try:
        text = (
            f"*Decision {action.title()}*\n"
            f"ID: `{decision_id}`\n"
            f"By operator at {_now()}"
        )
        _post(text)
    except Exception:
        pass

def flush_queue():
    try:
        path = STATE_DIR / "slack_queue.jsonl"
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("slack_sent"):
                continue
            agent = obj.get("agent", "system")
            msg = obj.get("message", "")
            level = obj.get("level", "info")
            prefix = {"error": "🚨", "warn": "⚠️", "info": "ℹ️"}.get(level, "ℹ️")
            if _post(f"{prefix} [{agent}] {msg}"):
                obj["slack_sent"] = True
    except Exception:
        pass
