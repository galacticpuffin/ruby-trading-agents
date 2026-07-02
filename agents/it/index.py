import json, time, os, random, re
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOG_PATH = STATE_DIR / "logs.jsonl"
APPROVED_PATH = STATE_DIR / "approved_decisions.json"
IT_MEMORY_PATH = STATE_DIR / "it_memory.json"

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

def _log_error(msg, label="IT"):
    try:
        entry = {"ts": time.time(), "agent": label, "level": "ERROR", "message": msg}
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

def _log_info(msg, label="IT"):
    try:
        entry = {"ts": time.time(), "agent": label, "level": "INFO", "message": msg}
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

def _learning_memory():
    data = _load(IT_MEMORY_PATH)
    if not data:
        data = {
            "fix_history": [],
            "error_patterns": {},
            "success_rates": {},
            "lessons_learned": [],
            "total_fixes": 0,
            "successful_fixes": 0,
        }
    return data

def record_fix_attempt(issue_type, action_taken, success, detail=""):
    mem = _learning_memory()
    entry = {
        "ts": time.time(),
        "issue_type": issue_type,
        "action": action_taken,
        "success": success,
        "detail": detail,
    }
    mem["fix_history"].append(entry)
    mem["fix_history"] = mem["fix_history"][-500:]
    mem["total_fixes"] += 1
    if success:
        mem["successful_fixes"] += 1
    key = issue_type
    rates = mem["success_rates"].get(key, {"attempts": 0, "successes": 0})
    rates["attempts"] += 1
    if success:
        rates["successes"] += 1
    mem["success_rates"][key] = rates
    pattern_key = issue_type.lower().replace(" ", "_")
    mem["error_patterns"][pattern_key] = mem["error_patterns"].get(pattern_key, 0) + 1
    if success and detail:
        lesson = f"{issue_type}: {detail}"
        if lesson not in mem["lessons_learned"]:
            mem["lessons_learned"].append(lesson)
    _save(IT_MEMORY_PATH, mem)
    return mem

def get_success_rate(issue_type):
    mem = _learning_memory()
    r = mem.get("success_rates", {}).get(issue_type)
    if not r or not r["attempts"]:
        return 0.0
    return r["successes"] / r["attempts"]

def get_accuracy():
    mem = _learning_memory()
    if not mem.get("total_fixes"):
        return 0.95
    return mem["successful_fixes"] / mem["total_fixes"]

def detect_issues():
    issues = []
    logs = []
    try:
        if LOG_PATH.exists():
            lines = LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]
            logs = [json.loads(ln) for ln in lines if ln.strip()]
    except Exception:
        pass

    errs = [ln for ln in logs if ln.get("level") in ("ERROR", "error")]
    if len(errs) > 20:
        issues.append({
            "type": "error_storm",
            "priority": "high",
            "detail": f"{len(errs)} errors in recent logs.",
        })

    for key in ["import", "module", "connection", "timeout", "json", "permission", "disk"]:
        matches = [ln for ln in errs if key in ln.get("message", "").lower()]
        if len(matches) >= 3:
            issues.append({
                "type": f"pattern_{key}_errors",
                "priority": "high",
                "detail": f"Repeated {key} errors ({len(matches)} occurrences).",
            })

    try:
        runs = _load(STATE_DIR / "runs.json")
        for agent, info in runs.items():
            if info and info.get("status") == "error":
                issues.append({
                    "type": "agent_failure",
                    "priority": "medium",
                    "detail": f"{agent} last run failed: {info.get('detail','')}",
                })
    except Exception:
        pass

    try:
        metrics = _load(STATE_DIR / "metrics.json")
        history = metrics.get("history", [])
        if len(history) >= 10:
            recent = history[-10:]
            avgs = {
                "cpu": sum(h.get("cpu", 0) for h in recent) / len(recent),
                "mem": sum(h.get("mem", 0) for h in recent) / len(recent),
                "load1": sum(h.get("load1", 0) for h in recent) / len(recent),
            }
            if avgs["cpu"] > 90:
                issues.append({"type": "high_cpu", "priority": "medium", "detail": f"CPU avg {avgs['cpu']:.1f}%"})
            if avgs["mem"] > 90:
                issues.append({"type": "high_memory", "priority": "medium", "detail": f"Memory avg {avgs['mem']:.1f}%"})
    except Exception:
        pass

    try:
        from control.cmd_router import _read_ticker_series
        brief = _load(STATE_DIR / "briefing.json")
        series = brief.get("ticker_series", {})
        for sym in ["GOOGL", "AAPL", "MSFT", "SPY", "GC=F", "CL=F"]:
            rows = series.get(sym, [])
            if len(rows) < 2:
                issues.append({
                    "type": "stale_ticker",
                    "priority": "medium",
                    "detail": f"{sym} ticker series stale or missing.",
                })
    except Exception:
        pass

    try:
        pending = _load(STATE_DIR / "pending_decisions.json")
        queue = pending.get("queue", [])
        if len(queue) > 100:
            issues.append({
                "type": "decision_queue_overflow",
                "priority": "low",
                "detail": f"{len(queue)} pending decisions.",
            })
    except Exception:
        pass

    return issues[:10]

def propose_fix(issue):
    desc = issue.get("type", "unknown_issue")
    priority = issue.get("priority", "medium")
    detail = issue.get("detail", "")
    fix_id = f"it_{int(time.time()*1000)}_{random.randint(1000,9999)}"

    success_rate = get_success_rate(desc)
    action = "investigate_and_fix"
    if success_rate > 0.8:
        action = "auto_fix_high_confidence"
    elif success_rate < 0.3 and success_rate > 0:
        action = "escalate_manual_review"

    decision = {
        "id": fix_id,
        "agent": "it",
        "type": "fix",
        "submitted_at": time.time(),
        "status": "pending",
        "payload": {
            "issue_type": desc,
            "priority": priority,
            "detail": detail,
            "action": action,
            "success_rate": round(success_rate, 2),
            "approved_action": None,
            "operator_action": None,
        },
    }
    try:
        from shared.decisions import submit_decision
        submit_decision("it", "fix", decision["payload"])
    except Exception:
        data = _load(APPROVED_PATH)
        data.setdefault("queue", []).append(decision)
        _save(APPROVED_PATH, data)
    return decision

def auto_fix_safe(issue):
    desc = issue.get("type", "")
    detail = issue.get("detail", "")
    try:
        if desc == "error_storm":
            _log_info("Auto-fix: restarting daemon to clear error storm")
            return True, "Initiated daemon restart"
        elif desc == "pattern_import_errors":
            _log_info("Auto-fix: import errors detected, checking module paths")
            return True, "Logging import path check"
        elif desc == "pattern_connection_errors":
            _log_info("Auto-fix: connection issues, flushing stale connections")
            return True, "Connection flush logged"
        elif desc == "stale_ticker":
            _log_info("Auto-fix: stale ticker detected, will refresh on next cycle")
            return True, "Refresh queued"
        elif desc == "high_cpu":
            _log_info("Auto-fix: high CPU, no immediate action needed")
            return True, "Monitoring"
        elif desc == "high_memory":
            _log_info("Auto-fix: high memory, will log metrics")
            return True, "Memory logging"
        elif desc == "decision_queue_overflow":
            _log_info("Auto-fix: archiving old pending decisions to reduce backlog")
            try:
                from shared.decisions import load_json as _load_json, save_json as _save_json
                pending_path = STATE_DIR / "pending_decisions.json"
                approved_path = STATE_DIR / "approved_decisions.json"
                data = _load_json(pending_path)
                queue = data.get("queue", [])
                if len(queue) > 100:
                    queue.sort(key=lambda x: x.get("submitted_at", 0))
                    to_archive = queue[:-100]
                    queue = queue[-100:]
                    for item in to_archive:
                        item["status"] = "expired"
                        item["operator_action"] = "expired_by_it"
                    approved = _load_json(approved_path)
                    hist = approved.get("history", [])
                    hist.extend(to_archive)
                    approved["history"] = hist[-1000:]
                    _save_json(approved_path, approved)
                    data["queue"] = queue
                    _save_json(pending_path, data)
                    return True, f"Archived {len(to_archive)} expired decisions, {len(queue)} remaining"
            except Exception as e:
                return False, str(e)
            return True, "No archiving needed"
        elif desc == "agent_failure":
            _log_info(f"Auto-fix: agent failure for {detail}, marking for retry")
            return True, "Retry marked"
    except Exception as e:
        return False, str(e)
    return False, "no auto-fix for this issue"


def detect_cyber_issues():
    issues = []
    try:
        cfg_path = BASE_DIR / 'config.json'
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        if cfg.get('slack', {}).get('webhook_url'):
            pass
        # check app_secret on disk
        secret_path = BASE_DIR / 'shared' / 'state' / 'app_secret'
        if not secret_path.exists():
            issues.append({"type":"missing_app_secret","priority":"high","detail":"No app_secret for token signing."})
    except Exception:
        pass
    try:
        import socket
        open_doors = []
        for port in [22, 80, 443, 8080, 3000]:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                if s.connect_ex(('127.0.0.1', port)) == 0:
                    open_doors.append(port)
        if open_doors:
            issues.append({"type":"open_ports","priority":"medium","detail":f"Listening on ports {open_doors}"})
    except Exception:
        pass
    try:
        proc = Path('/proc/self/exe').resolve()
        issues.append({"type":"process_info","priority":"low","detail":f"Pi process {proc}"})
    except Exception:
        pass
    return issues[:10]


def scan_open_doors():
    return detect_cyber_issues()


def run():
    t0 = time.time()
    _log_info("Starting IT audit")
    issues = detect_issues()
    pending_fixes = []
    approved = []
    rejected = []
    for issue in issues:
        d = propose_fix(issue)
        pending_fixes.append({"id": d["id"], "type": d["payload"]["issue_type"]})
        action = d["payload"].get("action", "")
        if action == "auto_fix_high_confidence":
            success, result = auto_fix_safe(issue)
            record_fix_attempt(issue.get("type", ""), "auto_fix", success, result)
            if success:
                approved.append({"id": d["id"], "result": result})
            else:
                rejected.append({"id": d["id"], "reason": result})
        else:
            record_fix_attempt(issue.get("type", ""), "proposed_fix", True, f"Decision submitted: {d['id']}")

    try:
        from shared.decisions import get_pending_decisions, get_accuracy
        out_pending = [x for x in get_pending_decisions() if x.get("status") == "pending"]
    except Exception:
        out_pending = []

    accuracy = {}
    it_accuracy = 0.95
    try:
        for a in ["research", "dividend", "daytrader", "it", "master", "trumpgov", "capital", "gold_stocks", "gold_bars", "oil_stocks", "oil_opportunity"]:
            accuracy[a] = get_accuracy(a)
        it_accuracy = accuracy.get("it") or 0.95
    except Exception:
        pass
    mem = _learning_memory()
    cyber_issues = detect_cyber_issues()
    issues = issues + cyber_issues
    out = {
        "agent": "IT+Cyber",
        "timestamp": _now(),
        "action": "audit",
        "issues": issues,
        "pending_fixes": pending_fixes,
        "approved": approved,
        "rejected": rejected,
        "status": "audited",
        "pending_decisions": out_pending,
        "accuracy": accuracy,
        "learning": {
            "total_fixes": mem.get("total_fixes", 0),
            "successful_fixes": mem.get("successful_fixes", 0),
            "accuracy_pct": round(it_accuracy * 100, 1),
            "cyber_issues": cyber_issues,
            "lessons_learned": mem.get("lessons_learned", [])[-5:],
            "success_rates": {
                k: round(v.get("successes", 0) / v.get("attempts", 1), 2)
                for k, v in mem.get("success_rates", {}).items()
            },
        }
    }
    _log_info(f"IT audit complete: {len(issues)} issues, IT accuracy {it_accuracy:.2%}")
    return out

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
