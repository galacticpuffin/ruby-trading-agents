import json, time, os, urllib.request
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOGS_PATH = STATE_DIR / "logs.jsonl"
BRIEF_PATH = STATE_DIR / "briefing.json"
FOLIO_PATH = STATE_DIR / "portfolio.json"
RUNS_PATH = STATE_DIR / "runs.json"
CONFIG_PATH = BASE_DIR / "config.json"

def ensure_runs():
    if not RUNS_PATH.exists():
        save_json(RUNS_PATH, {
            "research": None,
            "dividend": None,
            "daytrader": None,
            "capital": None,
            "gold_stocks": None,
            "gold_bars": None,
            "oil_stocks": None,
            "oil_opportunity": None,
            "it": None,
            "master": None,
            "trumpgov": None,
        })

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
    entry = {"ts":time.time(),"agent":agent,"level":level,"message":message}
    with open(LOGS_PATH,"a") as f:
        f.write(json.dumps(entry)+"\n")

def set_run_status(agent, status, detail=None):
    ensure_runs()
    data = load_json(RUNS_PATH)
    data[agent] = {"status":status,"detail":detail,"updated_at":time.time()}
    save_json(RUNS_PATH, data)

def get_runs():
    ensure_runs()
    return load_json(RUNS_PATH)

def teams_notify(title, text, webhook_url=None):
    try:
        cfg = load_json(CONFIG_PATH)
        teams = cfg.get("teams", {})
        url = webhook_url or teams.get("webhook_url")
        if not url or not teams.get("enabled"):
            return False
        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "0076D7",
            "summary": title,
            "sections": [{"activityTitle": title, "activitySubtitle": datetime.now().strftime("%I:%M %p"), "text": text}],
        }
        req = urllib.request.Request(url, data=json.dumps(card).encode("utf-8"), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False

def update_ticker_series(symbols=None):
    """Append real market prices for the given tickers into briefing.json."""
    try:
        brief = load_json(BRIEF_PATH)
        tickers = list((brief.get("tickers_mentioned", {}) or {}).keys())[:12]
        if symbols:
            tickers = list(set(tickers + list(symbols)))[:12]
        if not tickers:
            return
        series = brief.get("ticker_series", {})
        now = time.time()
        add = []
        try:
            import yfinance as yf
            yf_tickers = yf.Tickers(" ".join(tickers))
            for sym in tickers:
                try:
                    info = yf_tickers.tickers.get(sym, {}).info
                    price = info.get("currentPrice") or info.get("regularMarketPrice")
                    if not price:
                        hist = yf_tickers.tickers.get(sym, {}).history(period="1d")
                        if not hist.empty:
                            price = float(hist["Close"].iloc[-1])
                    if not price:
                        continue
                    price = round(float(price), 2)
                    rows = series.get(sym, [])
                    prev = rows[-1]["price"] if rows else price
                    delta = round(price - prev, 2)
                    rows.append({"ts": now, "price": price, "delta": delta})
                    series[sym] = rows[-120:]
                    add.append(sym)
                except Exception:
                    pass
        except Exception:
            # yfinance unavailable; keep series unchanged to avoid synthetic noise
            return
        brief["ticker_series"] = series
        save_json(BRIEF_PATH, brief)
    except Exception:
        pass
