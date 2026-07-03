from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
import json, time, asyncio, sys, os, threading, collections
from pathlib import Path
from contextlib import asynccontextmanager

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

STATE_DIR = BASE_DIR / "shared" / "state"
CONFIG_PATH = BASE_DIR / "config.json"
FOLIO = STATE_DIR / "portfolio.json"
BRIEF = STATE_DIR / "briefing.json"
LOGS = STATE_DIR / "logs.jsonl"
RUNS = STATE_DIR / "runs.json"
DECISIONS_PATH = STATE_DIR / "pending_decisions.json"
METRICS_PATH = STATE_DIR / "metrics.json"

@asynccontextmanager
async def lifespan(app):
    try:
        import agents.research.index as research_mod
        research_mod.start_live_mode()
    except Exception:
        pass
    yield

app = FastAPI(title="Operator Control Window", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory=BASE_DIR / "control"), name="control-static")

html_path = Path(__file__).parent / "index.html"
HTML_PAGE = html_path.read_text() if html_path.exists() else "<h1>missing dashboard</h1>"


@app.get("/")
async def root():
    return HTMLResponse(HTML_PAGE)


@app.post("/api/login")
async def login(request: Request):
    return JSONResponse({"token": "open-access", "expires_in": 0})


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/api/healthz")
async def api_healthz():
    try:
        from shared.decisions import get_pending_decisions
        pending_count = len([d for d in get_pending_decisions() if d.get("status") == "pending"])
    except Exception:
        pending_count = -1
    disk = _disk_usage()
    return {
        "status": "ok",
        "pending_decisions": pending_count,
        "disk": disk,
    }


@app.get("/api/status")
async def api_status():
    try:
        folio = load_json(FOLIO)
        brief = load_json(BRIEF)
        runs = get_runs()
        from shared.decisions import get_pending_decisions, get_accuracy
        pending = [d for d in get_pending_decisions() if d.get("status") == "pending"]
        acc = {a: get_accuracy(a) for a in [
            "research", "dividend", "daytrader", "capital",
            "gold_stocks", "gold_bars", "oil_stocks", "oil_opportunity",
            "it", "master", "trumpgov",
        ]}
    except Exception:
        folio = {}
        brief = {}
        runs = []
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
        },
    }


@app.post("/api/run/{agent}")
async def api_run_agent(agent: str):
    allowed = {
        "research", "dividend", "daytrader", "capital",
        "gold_stocks", "gold_bars", "oil_stocks", "oil_opportunity",
        "it", "master", "trumpgov",
    }
    if agent not in allowed:
        return JSONResponse({"error": "unknown agent"}, status_code=404)
    payload, err = _invoke_agent(agent)
    if err:
        return JSONResponse({"success": False, "agent": agent, "error": str(err)}, status_code=500)
    return JSONResponse({"success": True, "agent": agent, "result": payload})


@app.post("/api/approve/{decision_id}")
async def api_approve(decision_id: str):
    try:
        from shared.decisions import approve_decision
        ok = approve_decision(decision_id.strip(), "approved")
        return JSONResponse({"ok": ok, "decision_id": decision_id, "action": "approved" if ok else "not_found"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/reject/{decision_id}")
async def api_reject(decision_id: str):
    try:
        from shared.decisions import approve_decision
        ok = approve_decision(decision_id.strip(), "rejected")
        return JSONResponse({"ok": ok, "decision_id": decision_id, "action": "rejected" if ok else "not_found"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/decisions")
async def api_decisions():
    try:
        from shared.decisions import get_pending_decisions
        pending = [d for d in get_pending_decisions() if d.get("status") == "pending"]
        return JSONResponse({"ok": True, "pending": pending})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                data = {"text": msg}
            try:
                from control.cmd_router import CommandRouter
                router = CommandRouter()
                result = router.route(data.get("text", ""))
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            try:
                await websocket.send_json(result)
            except Exception:
                break
    except WebSocketDisconnect:
        pass


@app.get("/api/metrics")
async def api_metrics():
    try:
        txt = METRICS_PATH.read_text()
        data = json.loads(txt)
    except Exception:
        data = {}
    return JSONResponse(data)


@app.get("/api/logs")
async def api_logs():
    try:
        lines = LOGS.read_text(errors="ignore").splitlines()[-200:]
    except Exception:
        lines = []
    return JSONResponse({"logs": lines})


@app.get("/api/integrations")
async def api_integrations():
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        cfg = {}
    return JSONResponse(cfg.get("brokers", {}))


@app.post("/api/integrations")
async def api_integrations_save(request: Request):
    body = await request.json()
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        cfg = {"brokers": {}}
    cfg.setdefault("brokers", {}).update(body)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return JSONResponse({"ok": True, "brokers": cfg.get("brokers", {})})


def _invoke_agent(agent: str):
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
    mod_path = mapping.get(agent)
    if not mod_path:
        return None, RuntimeError(f"unknown agent '{agent}'")
    sys.path.insert(0, str(BASE_DIR))
    try:
        modname, funcname = mod_path.rsplit(".", 1)
        mod = __import__(modname, fromlist=[funcname])
        fn = getattr(mod, funcname)
        result = fn()
        return result, None
    except Exception as e:
        return None, e


# Helpers used by endpoints above
def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_json(path: Path, data):
    try:
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def get_runs():
    try:
        return load_json(RUNS)
    except Exception:
        return []


def _disk_usage():
    try:
        usage = os.statvfs(str(BASE_DIR))
        return {
            "free": usage.f_bavail * usage.f_frsize,
            "total": usage.f_blocks * usage.f_frsize,
        }
    except Exception:
        return {"free": 0, "total": 0}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
