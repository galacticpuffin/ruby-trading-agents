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
        from shared.decisions import approve_decision, get_pending_decisions
        ok = approve_decision(decision_id.strip(), "approved")
        if ok:
            try:
                pending = get_pending_decisions()
                target = next((d for d in pending if d.get("id") == decision_id), None)
                if target and target.get("type") == "capital_injection":
                    agent_name = target.get("agent")
                    amount = float((target.get("payload") or {}).get("amount", 0))
                    if agent_name and amount > 0:
                        portfolio_path = STATE_DIR / "portfolio.json"
                        portfolio = load_json(portfolio_path) if portfolio_path.exists() else {}
                        agent_state = portfolio.get(agent_name, {})
                        if not isinstance(agent_state, dict):
                            agent_state = {}
                        current = float(agent_state.get("cash", 0))
                        agent_state["cash"] = round(current + amount, 2)
                        agent_state["starting_cash"] = agent_state.get("starting_cash", amount)
                        portfolio[agent_name] = agent_state
                        portfolio.setdefault("current_cash", 0)
                        portfolio["current_cash"] = round(float(portfolio.get("current_cash", 0)) + amount, 2)
                        save_json(portfolio_path, portfolio)
            except Exception:
                pass
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


@app.get("/api/agent/{agent}")
async def api_agent_detail(agent: str):
    try:
        if agent == "research":
            try:
                brief = load_json(BRIEF)
                validated = ((brief.get("connectivity") or {}).get("validated") if isinstance(brief, dict) else None)
                stories = (brief.get("top_stories") or [])[:12] if isinstance(brief, dict) else []
                tickers = (brief.get("tickers_mentioned") or {}) if isinstance(brief, dict) else {}
                live_feed = []
                research_live = STATE_DIR / "research_live.jsonl"
                if research_live.exists():
                    try:
                        lines = research_live.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                live_feed.append(json.loads(line))
                            except Exception:
                                pass
                    except Exception:
                        pass
                data = {
                    "agent": "research",
                    "connectivity": (brief.get("connectivity") if isinstance(brief, dict) else {}),
                    "top_stories": stories,
                    "tickers_mentioned": tickers,
                    "live_feed": sorted(live_feed, key=lambda x: x.get("ts", 0))[-50:],
                }
            except Exception:
                data = {}
            return JSONResponse(data)
        data = load_json(STATE_DIR / f"{agent}.json")
        if not data:
            return JSONResponse({})
        return JSONResponse(data)
    except Exception:
        return JSONResponse({})


@app.get("/api/briefing")
async def api_briefing():
    try:
        data = load_json(BRIEF)
        return JSONResponse(data)
    except Exception:
        return JSONResponse({})


@app.get("/api/gold")
async def api_gold():
    try:
        prices = _price_fallback(["GC=F", "GDX", "GLD", "NEM", "ABX", "AU", "GOLD", "KGC"])
        return JSONResponse({"prices": prices})
    except Exception:
        return JSONResponse({"prices": {"GC=F": 0, "GLD": 0}})


@app.get("/api/oil")
async def api_oil():
    try:
        prices = _price_fallback(["CL=F", "BZ=F", "XOM", "CVX", "COP", "SLB", "OXY", "VLO", "MPC", "PSX", "USO", "XLE"])
        return JSONResponse({"prices": prices})
    except Exception:
        return JSONResponse({"prices": {"CL=F": 0, "XLE": 0}})


def _price_fallback(symbols):
    out = {}
    try:
        brief = load_json(BRIEF)
        series = ((brief.get("ticker_series") or {}))
        for sym in symbols:
            val = series.get(sym)
            if val is None:
                val = series.get(sym.upper())
            if val is None and "=" not in sym:
                val = series.get(sym.upper() + "=F")
            if isinstance(val, list) and val:
                val = val[-1].get("price")
            out[sym] = val if isinstance(val, (int, float)) else 0
    except Exception:
        out = {sym: 0 for sym in symbols}
    if not any(v for v in out.values()):
        try:
            import yfinance as yf
            yf_tickers = yf.Tickers(" ".join(symbols))
            for sym in symbols:
                try:
                    info = yf_tickers.tickers.get(sym, {})
                    price = ((info.info or {}).get("currentPrice") or (info.info or {}).get("regularMarketPrice"))
                    if not price:
                        hist = info.history(period="1d")
                        if not hist.empty:
                            price = float(hist["Close"].iloc[-1])
                    out[sym] = round(float(price), 2) if price else 0
                except Exception:
                    out[sym] = 0
        except Exception:
            pass
    if not any(v for v in out.values()):
        return {symbols[0]: 0, symbols[-1]: 0}
    return out


@app.get("/api/politics")
async def api_politics():
    try:
        brief = load_json(BRIEF)
        impact = brief.get("political_impact", {})
        return JSONResponse(impact if impact else {"high_impact": 0, "suggestions": []})
    except Exception:
        return JSONResponse({"high_impact": 0, "suggestions": []})


def broadcast_sync(data: dict):
    try:
        log("broadcast", data.get("level", "info"), f"{data.get('agent','?')}: {data.get('message','')}")
    except Exception:
        pass


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
    items = []
    for k, v in cfg.get("brokers", {}).items():
        it = dict(v, key=k)
        it["type"] = "broker"
        items.append(it)
    for k, v in cfg.get("banking", {}).items():
        it = dict(v, key=k)
        it["type"] = "bank"
        items.append(it)
    return JSONResponse({"integrations": items})


@app.post("/api/integrations")
async def api_integrations_save(request: Request):
    body = await request.json()
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        cfg = {"brokers": {}, "banking": {}}
    itype = (body or {}).get("type", "broker")
    key = body.get("key")
    if not key:
        return JSONResponse({"ok": False, "error": "missing key"}, status_code=400)
    section_key = "banking" if itype == "bank" else "brokers"
    section = cfg.setdefault(section_key, {})
    section[key] = {k: v for k, v in body.items() if k not in ("type", "key")}
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return JSONResponse({"ok": True, "integrations": _normalize_integrations(cfg)})


@app.post("/api/integrations/{key}/link")
async def api_integrations_link(key: str, request: Request):
    body = await request.json()
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        cfg = {"brokers": {}, "banking": {}}
    # Support both broker and bank keys
    section = cfg.get("brokers", {}).get(key)
    if section is None:
        section = cfg.setdefault("banking", {}).setdefault(key, {})
    else:
        cfg.setdefault("brokers", {})[key] = section
    section.update({
        "linked": True,
        "api_key": body.get("api_key", section.get("api_key", "") if isinstance(section, dict) else ""),
        "api_secret": body.get("api_secret", section.get("api_secret", "") if isinstance(section, dict) else ""),
        "redirect_uri": body.get("redirect_uri", section.get("redirect_uri", "") if isinstance(section, dict) else ""),
        "client_id": body.get("client_id", section.get("client_id", "") if isinstance(section, dict) else ""),
        "client_secret": body.get("client_secret", section.get("client_secret", "") if isinstance(section, dict) else ""),
        "access_token": body.get("access_token", section.get("access_token", "") if isinstance(section, dict) else ""),
        "refresh_token": body.get("refresh_token", section.get("refresh_token", "") if isinstance(section, dict) else ""),
        "account_id": body.get("account_id", section.get("account_id", "") if isinstance(section, dict) else ""),
        "enabled": True,
    })
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return JSONResponse({"ok": True, "key": key})


def _normalize_integrations(cfg):
    items = []
    for k, v in cfg.get("brokers", {}).items():
        it = dict(v, key=k)
        it["type"] = "broker"
        items.append(it)
    for k, v in cfg.get("banking", {}).items():
        it = dict(v, key=k)
        it["type"] = "bank"
        items.append(it)
    return items


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
