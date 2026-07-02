import time, json, sys, importlib, traceback
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

CONFIG_PATH = BASE_DIR / "config.json"
cfg = {}
try:
    cfg = json.loads(CONFIG_PATH.read_text())
except Exception:
    pass

STATE_DIR = BASE_DIR / "shared" / "state"
RUNS_PATH = STATE_DIR / "runs.json"
LOGS_PATH = STATE_DIR / "logs.jsonl"
STATE_DIR.mkdir(parents=True, exist_ok=True)

try:
    from agents.slack_integration.index import alert as slack_alert
except Exception:
    slack_alert = None

import agents.research.index as research_mod
import agents.dividend.index as dividend_mod
import agents.daytrader.index as daytrader_mod
import agents.capital.index as capital_mod
import agents.gold_stocks.index as gold_stocks_mod
import agents.gold_bars.index as gold_bars_mod
import agents.oil_stocks.index as oil_stocks_mod
import agents.oil_opportunity.index as oil_opp_mod
import agents.it.index as it_mod
import agents.master.index as master_mod
import agents.trumpgov.index as trumpgov_mod

def _load(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}

def _save(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))

def _set_run(agent, status, detail=None):
    data = _load(RUNS_PATH)
    data[agent] = {"status": status, "detail": detail, "updated_at": time.time()}
    _save(RUNS_PATH, data)

def _log(agent, level, message):
    try:
        entry = {"ts": time.time(), "agent": agent, "level": level, "message": message}
        with open(LOGS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    if slack_alert and level in ("ERROR", "error", "WARN", "warn", "INFO", "info"):
        try:
            slack_alert(agent, message, level)
        except Exception:
            pass

def _now():
    return datetime.now().strftime("%Y-%m-%d %I:%M %p")

_agents_cfg = cfg.get("agents", {})

_last_research = 0
_last_dividend = 0
_last_daytrader = 0
_last_capital = 0
_last_gold_stocks = 0
_last_gold_bars = 0
_last_oil_stocks = 0
_last_oil_opp = 0
_last_it = 0
_last_master = 0
_last_trumpgov = 0

_interval_research = _agents_cfg.get("research", {}).get("interval_minutes", 30) * 60
_interval_dividend = 24 * 60 * 60
_interval_daytrader = 60 * 60
_interval_capital = int(_agents_cfg.get("capital", {}).get("interval_minutes", 120)) * 60
_interval_gold_stocks = int(_agents_cfg.get("gold_stocks", {}).get("interval_minutes", 180)) * 60
_interval_gold_bars = int(_agents_cfg.get("gold_bars", {}).get("interval_minutes", 240)) * 60
_interval_oil_stocks = int(_agents_cfg.get("oil_stocks", {}).get("interval_minutes", 180)) * 60
_interval_oil_opp = int(_agents_cfg.get("oil_opportunity", {}).get("interval_minutes", 150)) * 60
_interval_it = int(_agents_cfg.get("it", {}).get("scan_interval_minutes", 15)) * 60
_interval_master = 10 * 60
_interval_trumpgov = int(_agents_cfg.get("trumpgov", {}).get("interval_minutes", 30)) * 60

def _safe_run(name, fn):
    try:
        _set_run(name, "running", "started")
        _log(name, "info", f"run -> {fn.__name__}")
        result = fn()
        _set_run(name, "done", "completed")
        _log(name, "info", f"done -> {fn.__name__}")
        return result
    except Exception as e:
        detail = traceback.format_exc()
        _set_run(name, "error", str(e))
        _log(name, "error", detail)
        return None

if __name__ == "__main__":
    _log("daemon", "INFO", "24/7 agent loop started")
    _set_run("research", "idle", "ready")
    _set_run("dividend", "idle", "ready")
    _set_run("daytrader", "idle", "ready")
    _set_run("capital", "idle", "ready")
    _set_run("gold_stocks", "idle", "ready")
    _set_run("gold_bars", "idle", "ready")
    _set_run("oil_stocks", "idle", "ready")
    _set_run("oil_opportunity", "idle", "ready")
    _set_run("it", "idle", "ready")
    _set_run("master", "idle", "ready")
    _set_run("trumpgov", "idle", "ready")
    try:
        research_mod.start_live_mode()
        while True:
            now = time.time()
            if now - _last_research >= _interval_research:
                _last_research = now
                _safe_run("research", research_mod.build_briefing)
            if now - _last_dividend >= _interval_dividend:
                _last_dividend = now
                _safe_run("dividend", dividend_mod.run)
            if now - _last_daytrader >= _interval_daytrader:
                _last_daytrader = now
                _safe_run("daytrader", daytrader_mod.run)
            if now - _last_capital >= _interval_capital:
                _last_capital = now
                _safe_run("capital", capital_mod.run)
            if now - _last_gold_stocks >= _interval_gold_stocks:
                _last_gold_stocks = now
                _safe_run("gold_stocks", gold_stocks_mod.run)
            if now - _last_gold_bars >= _interval_gold_bars:
                _last_gold_bars = now
                _safe_run("gold_bars", gold_bars_mod.run)
            if now - _last_oil_stocks >= _interval_oil_stocks:
                _last_oil_stocks = now
                _safe_run("oil_stocks", oil_stocks_mod.run)
            if now - _last_oil_opp >= _interval_oil_opp:
                _last_oil_opp = now
                _safe_run("oil_opportunity", oil_opp_mod.run)
            if now - _last_it >= _interval_it:
                _last_it = now
                _safe_run("it", it_mod.run)
            if now - _last_master >= _interval_master:
                _last_master = now
                _safe_run("master", master_mod.run)
            if now - _last_trumpgov >= _interval_trumpgov:
                _last_trumpgov = now
                _safe_run("trumpgov", trumpgov_mod.run)
            time.sleep(5)
    except KeyboardInterrupt:
        _log("daemon", "INFO", "stopped by user")
    except Exception as e:
        _log("daemon", "ERROR", traceback.format_exc())
        time.sleep(10)
