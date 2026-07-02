import json, os, sys, time, importlib, importlib.util, traceback
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

_shared_spec = importlib.util.spec_from_file_location(
    "trading_agents_shared_core",
    BASE_DIR / "shared" / "core.py",
)
_core = importlib.util.module_from_spec(_shared_spec)
sys.modules.setdefault("trading_agents_shared_core", _core)
_shared_spec.loader.exec_module(_core)

set_run_status = _core.set_run_status
get_runs = _core.get_runs
load_json = _core.load_json
save_json = _core.save_json
log = _core.log

def stable_id(text):
    import hashlib
    return hashlib.sha1(text.encode()).hexdigest()[:10]

def terminal_exec(command: str) -> str:
    try:
        from hermes_tools import terminal as hermes_terminal
        cwd = str(Path(__file__).resolve().parent.parent)
        r = hermes_terminal(command=command, workdir=cwd, timeout=120)
        if not isinstance(r, dict):
            return str(r)
        return r.get("output") or str(r)
    except Exception as e:
        return f"ERR: {e}"

class CommandRouter:
    def __init__(self):
        self.handlers = {
            "run": self.cmd_run,
            "status": self.cmd_status,
            "cmd": self.cmd_shell,
            "help": self.cmd_help,
            "approve": self.cmd_approve,
            "reject": self.cmd_reject,
            "decisions": self.cmd_decisions,
        }

    def route(self, text: str):
        parts = [p.strip() for p in text.split(" ", 1)]
        if not parts:
            return {"ok": False, "error": "empty command"}
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        fn = self.handlers.get(cmd)
        if not fn:
            return {"ok": False, "error": f"unknown command '{cmd}'. try 'help'."}
        return fn(rest)

    def cmd_run(self, target):
        target = (target or "research").lower().strip()
        mapping = {
            "research": "agents.research.index.build_briefing",
            "dividend": "agents.dividend.index.run",
            "daytrader": "agents.daytrader.index.run",
            "capital": "agents.capital.index.run",
            "gold_stocks": "agents.gold_stocks.index.run",
            "gold_bars": "agents.gold_bars.index.run",
            "oil_stocks": "agents.oil_stocks.index.run",
            "oil_opportunity": "agents.oil_opportunity.index.run",
            "it": "agents.it.index.run",
            "master": "agents.master.index.run",
            "trumpgov": "agents.trumpgov.index.run",
        }
        mod_path = mapping.get(target)
        if not mod_path:
            return {"ok": False, "error": f"unknown target '{target}'"}
        set_run_status(target, "running", "queued")
        log("operator", "info", f"manual run -> {target}")
        payload, err = _invoke(mod_path)
        if err:
            set_run_status(target, "error", str(err))
            return {"ok": False, "error": str(err)}
        set_run_status(target, "done", "completed")
        return {"ok": True, "agent": target, "output": payload}

    def cmd_status(self, _):
        folio = load_json(BASE_DIR / "shared" / "state" / "portfolio.json")
        brief = load_json(BASE_DIR / "shared" / "state" / "briefing.json")
        runs = get_runs()
        try:
            from shared.decisions import get_pending_decisions, get_accuracy
            pending = [d for d in get_pending_decisions() if d.get("status") == "pending"]
            acc = {a: get_accuracy(a) for a in ["research", "dividend", "daytrader", "capital", "gold_stocks", "gold_bars", "oil_stocks", "oil_opportunity", "it", "master", "trumpgov"]}
        except Exception:
            pending = []
            acc = {}
        return {
            "ok": True,
            "data": {
                "portfolio": folio,
                "briefing_ts": brief.get("generated_at"),
                "runs": runs,
                "pending_decisions": pending,
                "accuracy": acc,
                "memory": self._memory_summary(),
            },
        }

    def cmd_shell(self, cmdline):
        cmdline = cmdline.strip().strip("'\"")
        if not cmdline:
            return {"ok": True, "output": ""}
        parts = cmdline.split()
        base = parts[0]
        allowed = {"ls", "cat", "find", "wc", "echo", "head", "pwd", "id"}
        if base not in allowed:
            return {"ok": False, "error": "allowed: ls|cat|find|wc|echo|head|pwd|id"}
        if base == "wc" and (len(parts) < 2 or parts[1] != "-l"):
            return {"ok": False, "error": "wc requires -l"}
        out = terminal_exec(cmdline)
        return {"ok": True, "output": out}

    def cmd_help(self, _):
        return {
            "ok": True,
            "help": [
                "run research|dividend|daytrader|capital|gold_stocks|gold_bars|oil_stocks|oil_opportunity|trumpgov",
                "status",
                "decisions",
                "approve <decision_id>",
                "reject <decision_id>",
                "cmd <safe shell limited to ls|cat|wc -l|echo|head|find|pwd|id>",
                "help",
            ],
        }

    def cmd_decisions(self, _):
        try:
            from shared.decisions import get_pending_decisions
            pending = [d for d in get_pending_decisions() if d.get("status") == "pending"]
            return {"ok": True, "pending": pending}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def cmd_approve(self, decision_id):
        decision_id = decision_id.strip()
        if not decision_id:
            return {"ok": False, "error": "usage: approve <decision_id>"}
        try:
            from shared.decisions import approve_decision
            ok = approve_decision(decision_id, "approved")
            return {"ok": ok, "decision_id": decision_id, "action": "approved" if ok else "not_found"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def cmd_reject(self, decision_id):
        decision_id = decision_id.strip()
        if not decision_id:
            return {"ok": False, "error": "usage: reject <decision_id>"}
        try:
            from shared.decisions import approve_decision
            ok = approve_decision(decision_id, "rejected")
            return {"ok": ok, "decision_id": decision_id, "action": "rejected" if ok else "not_found"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _memory_summary(self):
        return {
            "learned": [
                "hCaptcha/submit blocks on Lever/Greenhouse/Ashby/Workable",
                "resume uploads use DataTransfer/File input",
                "stable ids via SHA-1",
                "no reliable SMTP transport on the Pi",
            ]
        }


def _invoke(mod_path: str):
    sys.path.insert(0, str(BASE_DIR))
    try:
        modname, funcname = mod_path.rsplit(".", 1)
        agent = modname.split(".")[1]
        set_run_status(agent, "running", funcname)
        log(agent, "info", f"run {funcname}")
        try:
            from control.app import broadcast_sync
            broadcast_sync({"agent": agent, "message": f"{funcname} started", "level": "info"})
        except Exception:
            pass
        mod = importlib.import_module(modname)
        fn = getattr(mod, funcname)
        result = fn()
        set_run_status(agent, "done", "completed")
        try:
            from control.app import broadcast_sync
            broadcast_sync({"agent": agent, "message": f"{funcname} completed", "level": "ok"})
        except Exception:
            pass
        return result, None
    except Exception as e:
        detail = traceback.format_exc()
        label = locals().get("agent", "unknown")
        set_run_status(label, "error", str(e))
        log("operator", "error", detail)
        try:
            from control.app import broadcast_sync
            broadcast_sync({"agent": label, "message": str(e), "level": "error"})
        except Exception:
            pass
        return None, e
