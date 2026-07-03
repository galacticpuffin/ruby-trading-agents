from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request, HTTPException
import secrets
import json, time, asyncio, sys, urllib.request, os, threading, collections
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
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost","http://localhost:8080","http://127.0.0.1","http://127.0.0.1:8080","http://192.168.1.108","http://192.168.1.108:8080"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory=BASE_DIR / "control"), name="control-static")

html_path = Path(__file__).parent / "index.html"
HTML_PAGE = html_path.read_text() if html_path.exists() else "<h1>missing dashboard</h1>"

# ---------- AUTH ----------
import os as _os
_AUTH_USER = _os.environ.get("TRADING_DASH_USER", "operator")
_AUTH_PASS = _os.environ.get("TRADING_DASH_PASS", "change-me")

from starlette.middleware.base import BaseHTTPMiddleware
import base64, hmac, hashlib, json, time, secrets

_DASH_USER = _os.environ.get("TRADING_DASH_USER", "operator")
_DASH_PASS = _os.environ.get("TRADING_DASH_PASS", "TACOSTAND86!")

_SECRET_PATH = STATE_DIR / "app_secret"
if _SECRET_PATH.exists():
    _APP_SECRET = _SECRET_PATH.read_text().strip()
else:
    _APP_SECRET = secrets.token_hex(32)
    try:
        _SECRET_PATH.write_text(_APP_SECRET)
    except Exception:
        pass


def _sign_token(payload: dict) -> str:
    payload["iat"] = int(time.time())
    payload["exp"] = int(time.time()) + 8 * 3600
    payload["sub"] = _DASH_USER
    payload_data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(_APP_SECRET.encode(), payload_data, hashlib.sha256).hexdigest()[:16]
    payload["sig"] = sig
    token = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return token


def _verify_token(token: str):
    if not token:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded)
        payload = json.loads(raw.decode())
        if payload.get("exp", 0) < time.time():
            return False
        mem = {k: v for k, v in payload.items() if k != "sig"}
        expected_sig = hmac.new(
            _APP_SECRET.encode(),
            json.dumps(mem, separators=(",", ":"), sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()[:16]
        return hmac.compare_digest(expected_sig, payload.get("sig", ""))
    except Exception:
        return False


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in (
            "/",
            "/static",
            "/healthz",
            "/api/healthz",
            "/api/login",
            "/favicon.ico",
        ) or path.startswith("/static/"):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            if _verify_token(auth.split(" ", 1)[1]):
                return await call_next(request)
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8", errors="ignore")
                user, _, pwd = decoded.partition(":")
                if user == _DASH_USER and pwd == _DASH_PASS:
                    return await call_next(request)
            except Exception:
                pass
        return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": 'Basic realm="Operator"'})

app.add_middleware(BasicAuthMiddleware)


@app.post("/api/login")
async def login(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    user = (body.get("username") or "").strip()
    pwd = body.get("password") or ""
    if not user or not pwd:
        return JSONResponse({"error": "missing fields"}, status_code=400)
    if user != _DASH_USER or pwd != _DASH_PASS:
        return JSONResponse({"error": "invalid credentials"}, status_code=401)
    payload = {"sub": _DASH_USER}
    token = _sign_token(payload)
    return {"token": token, "expires_in": 8 * 3600}


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
        "ts": time.strftime("%Y-%m-%d %I:%M %p"),
    }

def _disk_usage():
    try:
        st = os.statvfs(str(STATE_DIR))
        total = st.f_blocks * st.f_frsize
        free = st.f_bfree * st.f_frsize
        used = total - free
        return {"total": total, "used": used, "free": free, "pct_used": (used / total) if total else 0}
    except Exception:
        return {}

def _get_system_metrics():
    cpu = 0.0
    mem = 0.0
    load1 = 0.0
    try:
        with open("/proc/stat") as f:
            first = f.readline().split()
        idle = float(first[4])
        total = sum(float(x) for x in first[1:])
        cpu = round(100 * (total - idle) / total, 2) if total else 0.0
        with open("/proc/loadavg") as f:
            load1 = float(f.read().split()[0])
        with open("/proc/meminfo") as f:
            avail = 0
            total_mem = 0
            for line in f:
                if line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) * 1024
                elif line.startswith("MemTotal:"):
                    total_mem = int(line.split()[1]) * 1024
            mem = round(100 * (1 - avail / total_mem), 2) if total_mem else 0.0
    except Exception:
        pass
    return {"cpu": cpu, "mem": mem, "load1": load1}

def _read_ticker_series(path):
    data = _load(path)
    series = data.get("ticker_series", {})
    out = {}
    for sym, rows in series.items():
        if isinstance(rows, list):
            out[sym] = rows[-120:]
    return out

def _save_metrics_snapshot():
    m = _get_system_metrics()
    brief = _load(BRIEF)
    tickers = {k: v for k, v in list(brief.get("tickers_mentioned", {}).items())[:15]}
    series = brief.get("ticker_series", {})
    for sym in ["GC=F", "CL=F", "GLD", "XLE"]:
        rows = series.get(sym)
        if rows and sym not in tickers:
            tickers[sym] = rows[-1]["price"] if rows else None
    entry = {
        "ts": time.time(),
        "cpu": m["cpu"],
        "mem": m["mem"],
        "load1": m["load1"],
        "tickers": tickers,
    }
    _append_metrics(entry)
    return entry

def _append_metrics(entry):
    if not METRICS_PATH.exists():
        data = {"history": []}
    else:
        try:
            data = json.loads(METRICS_PATH.read_text())
        except Exception:
            data = {"history": []}
    history = data.get("history", [])
    history.append(entry)
    data["history"] = history[-2000:]
    METRICS_PATH.write_text(json.dumps(data, indent=2, default=str))

@app.get("/api/metrics")
async def metrics():
    headers = {"Cache-Control": "no-store"}
    return JSONResponse({
        "system": _get_system_metrics(),
        "history": _load(METRICS_PATH).get("history", [])[-180:],
        "tickers": _read_ticker_series(BRIEF),
    }, headers=headers)

# ---------- ROUTES ----------
@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(HTML_PAGE, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

def _load(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

@app.get("/api/status")
async def status():
    try:
        from shared.decisions import get_accuracy, get_pending_decisions
        accuracy = {a: get_accuracy(a) for a in ["research", "dividend", "daytrader", "capital", "gold_stocks", "gold_bars", "oil_stocks", "oil_opportunity", "it", "master", "trumpgov"]}
        pending = [d for d in get_pending_decisions() if d.get("status") == "pending"]
    except Exception:
        accuracy = {}
        pending = []
    return JSONResponse({
        "agents": [
            {"name": "research", "status": "live"},
            {"name": "dividend", "status": "live"},
            {"name": "daytrader", "status": "live"},
            {"name": "capital", "status": "live"},
            {"name": "gold_stocks", "status": "live"},
            {"name": "gold_bars", "status": "live"},
            {"name": "oil_stocks", "status": "live"},
            {"name": "oil_opportunity", "status": "live"},
            {"name": "it", "status": "live"},
            {"name": "master", "status": "live"},
            {"name": "trumpgov", "status": "live"},
        ],
        "portfolio": _load(FOLIO),
        "runs": _load(RUNS),
        "pending_decisions": pending,
        "accuracy": accuracy,
    }, headers={"Cache-Control": "no-store"})

@app.get("/api/integrations")
async def integrations():
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        cfg = {}
    out = []
    for bkey, bval in cfg.get("brokers", {}).items():
        linked = bool(bval.get("linked"))
        note = bval.get("note", "") if linked else "Configure via dashboard"
        out.append({
            "type": "broker",
            "key": bkey,
            "label": bval.get("label", bkey),
            "base_url": bval.get("base_url"),
            "linked": linked,
            "note": note,
        })
    c1 = cfg.get("banking", {}).get("capital_one", {})
    c1_linked = bool(c1.get("access_token") or c1.get("enabled"))
    c1_note = c1.get("note", "") if c1_linked else "Configure via dashboard"
    out.append({
        "type": "bank",
        "key": "capital_one",
        "label": "Capital One",
        "base_url": "https://developer.capitalone.com",
        "linked": c1_linked,
        "note": c1_note,
    })
    return {"integrations": out}

@app.post("/api/integrations/{key}/link")
async def link_integration(key: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)
    api_key = (body.get("api_key") or "").strip()
    api_secret = (body.get("api_secret") or "").strip()
    redirect_uri = (body.get("redirect_uri") or "").strip()
    if not api_key and not api_secret and not redirect_uri:
        return JSONResponse({"ok": False, "error": "missing credentials"}, status_code=400)
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        cfg = {}
    brokers = cfg.setdefault("brokers", {})
    broker = brokers.get(key)
    if not broker:
        return JSONResponse({"ok": False, "error": "unknown integration"}, status_code=404)
    broker["linked"] = True
    if api_key:
        broker["api_key"] = api_key
    if api_secret:
        broker["api_secret"] = api_secret
    if redirect_uri:
        broker["redirect_uri"] = redirect_uri
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return {
        "ok": True,
        "key": key,
        "label": broker.get("label", key),
        "base_url": broker.get("base_url"),
        "linked": True,
    }

@app.post("/api/slack/notify")
async def slack_notify(request: Request):
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        cfg = {}
    slack = cfg.get("slack", {})
    url = slack.get("webhook_url") or os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return JSONResponse({"ok": False, "error": "no webhook_url configured"}, status_code=400)
    body = await request.json()
    text = body.get("text") or body.get("message") or ""
    payload = {"text": text}
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"ok": True, "status": resp.status}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.get("/api/briefing")
async def briefing():
    return {"brief": _load(BRIEF)}

@app.get("/api/agent/{name}")
async def agent_state(name: str):
    mapping = {
        "research": BRIEF,
        "dividend": FOLIO,
        "daytrader": FOLIO,
        "capital": STATE_DIR / "capital.json",
        "gold_stocks": STATE_DIR / "gold_stocks.json",
        "gold_bars": STATE_DIR / "gold_bars.json",
        "oil_stocks": STATE_DIR / "oil_stocks.json",
        "oil_opportunity": STATE_DIR / "oil_opportunity.json",
        "trumpgov": STATE_DIR / "trumpgov.json",
        "it": STATE_DIR / "approved_decisions.json",
        "master": RUNS,
    }
    path = mapping.get(name)
    if not path or not path.exists():
        return JSONResponse({"detail": "not found"}, status_code=404)
    data = _load(path)
    if name in ("dividend", "daytrader"):
        data = data.get(name, data)
    if name == "it":
        learn_path = STATE_DIR / "it_memory.json"
        learn = _load(learn_path)
        data = {
            "approved": data.get("history", []),
            "queue": data.get("queue", []),
            "learning": {
                "total_fixes": learn.get("total_fixes", 0),
                "successful_fixes": learn.get("successful_fixes", 0),
                "accuracy_pct": round(learn.get("successful_fixes", 0) / max(learn.get("total_fixes", 1), 1) * 100, 1),
                "lessons_learned": learn.get("lessons_learned", [])[-5:],
            },
        }
    if name == "master":
        data = {"runs": data}
    if name == "research":
        live_path = STATE_DIR / "research_live.jsonl"
        live_entries = []
        try:
            if live_path.exists():
                lines = live_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                for line in lines[-20:]:
                    try:
                        obj = json.loads(line)
                        if obj.get("message"):
                            live_entries.append({"message": obj["message"], "ts": obj.get("ts"), "level": obj.get("level", "info")})
                    except Exception:
                        pass
        except Exception:
            pass
        data = {**data, "live_feed": live_entries}
    return data

@app.get("/api/gold")
async def gold_status():
    price = None
    try:
        import yfinance as yf
        ticker = yf.Ticker("GC=F")
        try:
            price = ticker.fast_info.get("lastPrice")
        except Exception:
            pass
        if price is None:
            try:
                hist = ticker.history(period="1d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            except Exception:
                pass
    except Exception:
        pass
    gs = _load(STATE_DIR / "gold_stocks.json")
    gb = _load(STATE_DIR / "gold_bars.json")
    return {
        "price": price,
        "gold_stocks": {"cash": gs.get("cash"), "trades": gs.get("trades", [])[-5:]},
        "gold_bars": {"purchases": gb.get("purchases", [])[-5:]},
    }

@app.get("/api/oil")
async def oil_status():
    price = None
    try:
        import yfinance as yf
        ticker = yf.Ticker("CL=F")
        try:
            price = ticker.fast_info.get("lastPrice")
        except Exception:
            pass
        if price is None:
            try:
                hist = ticker.history(period="1d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            except Exception:
                pass
    except Exception:
        pass
    os = _load(STATE_DIR / "oil_stocks.json")
    oo = _load(STATE_DIR / "oil_opportunity.json")
    return {
        "price": price,
        "oil_stocks": {"cash": os.get("cash"), "trades": os.get("trades", [])[-5:]},
        "oil_opportunity": {"opportunities": oo.get("opportunities", [])[-5:]},
    }

@app.get("/api/politics")
async def politics_status():
    tv = _load(STATE_DIR / "trumpgov.json")
    brief = _load(BRIEF)
    stories = brief.get("top_stories", [])
    # Filter for political/macro impact items
    political = []
    for s in stories:
        desc = (s.get("description") or s.get("title") or "").lower()
        if any(k in desc for k in ["fed", "treasury", "congress", "trump", "biden", "policy", "regulation", "white house", "senate", "house"]):
            political.append(s)
    if not political and stories:
        political = stories[:5]
    return {
        "suggestions": tv.get("suggestions_made", 0),
        "high_impact": tv.get("high_impact_count", 0),
        "daily_suggestions": tv.get("daily_suggestions", 0),
        "top_political_stories": political[:8],
        "last_items_analyzed": tv.get("last_items_analyzed", 0),
    }

@app.get("/api/decisions")
async def decisions():
    try:
        from shared.decisions import get_pending_decisions
        return JSONResponse({"pending": [d for d in get_pending_decisions() if d.get("status") == "pending"]}, headers={"Cache-Control": "no-store"})
    except Exception as e:
        return JSONResponse({"pending": [], "error": str(e)}, status_code=500, headers={"Cache-Control": "no-store"})

@app.get("/api/logs")
async def logs(tail: int = 300):
    if not LOGS.exists():
        return {"lines": []}
    lines = LOGS.read_text().splitlines()[-tail:]
    out = []
    for ln in lines:
        try:
            obj = json.loads(ln)
            out.append({
                "time": time.strftime("%H:%M:%S", time.localtime(float(obj.get("ts", time.time())))),
                "agent": obj.get("agent", "?"),
                "level": obj.get("level", "?"),
                "msg": obj.get("message", ""),
            })
        except Exception:
            pass
    return JSONResponse({"lines": out}, headers={"Cache-Control": "no-store"})

@app.post("/api/run/{agent}")
async def run_agent(agent: str):
    try:
        from control.cmd_router import _invoke
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
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
        return JSONResponse({"success": False, "error": "unknown agent"}, status_code=400)
    result, err = _invoke(mod_path)
    if err:
        return JSONResponse({"success": False, "error": str(err)}, status_code=500)
    _save_metrics_snapshot()
    return {"success": True, "agent": agent, "result": result}

@app.post("/api/approve/{decision_id}")
async def approve_decision_api(decision_id: str):
    try:
        from shared.decisions import approve_decision
        ok = approve_decision(decision_id, "approved")
        return {"ok": ok, "decision_id": decision_id, "action": "approved" if ok else "not_found"}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/api/reject/{decision_id}")
async def reject_decision_api(decision_id: str):
    try:
        from shared.decisions import approve_decision
        ok = approve_decision(decision_id, "rejected")
        return {"ok": ok, "decision_id": decision_id, "action": "rejected" if ok else "not_found"}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

class WSManager:
    def __init__(self):
        self.active = []
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
    def disconnect(self, ws: WebSocket):
        try:
            self.active.remove(ws)
        except ValueError:
            pass
    async def broadcast(self, msg: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = WSManager()

def broadcast_sync(msg: dict):
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(manager.broadcast(msg))
        else:
            loop.run_until_complete(manager.broadcast(msg))
    except Exception:
        pass

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    token = ws.query_params.get("token")
    if not _verify_token(token):
        await ws.close(code=1008)
        return
    await manager.connect(ws)
    send_queue: asyncio.Queue = asyncio.Queue()
    async def reader():
        while True:
            try:
                msg = await ws.receive_text()
                await send_queue.put(msg)
            except WebSocketDisconnect:
                break
            except Exception:
                break
    async def writer():
        while True:
            msg = await send_queue.get()
            try:
                from control.cmd_router import CommandRouter
            except Exception:
                from cmd_router import CommandRouter
            reply = CommandRouter().route(msg)
            await ws.send_text(json.dumps(reply))
    await asyncio.gather(reader(), writer())

def _metrics_loop(interval=5):
    while True:
        try:
            _save_metrics_snapshot()
        except Exception:
            pass
        time.sleep(interval)

threading.Thread(target=_metrics_loop, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
