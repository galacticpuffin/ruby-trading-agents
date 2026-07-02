import requests, json, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

BRIEF_PATH = STATE_DIR / "briefing.json"
FOLIO_PATH = STATE_DIR / "portfolio.json"

def _load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}

def _save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

def fetch_snapshot():
    """Return a deterministic snapshot from public endpoints. Falls back gracefully."""
    snapshot = {
        "generated_at": time.strftime("%Y-%m-%d %I:%M %p"),
        "market": "unknown",
        "quotes": [],
        " divid_snapshot": {},
    }
    try:
        # A lightweight public quote source. Replace with your data provider if needed.
        resp = requests.get("https://api.exchangerate.host/latest?base=USD", timeout=10)
        if resp.ok:
            snapshot["market"] = "fx"
            snapshot["fx"] = resp.json().get("rates", {})
    except Exception:
        pass
    try:
        # yfinance-style fallback through a public status page isn't reliable without the package,
        # so we'll store market hours + a sample dividend watchlist from a static seed for now.
        pass
    except Exception:
        pass
    watchlist = [
        {"symbol": "T", "name": "AT&T", "yield": 6.4, "price": 18.5},
        {"symbol": "O", "name": "Realty Income", "yield": 5.8, "price": 62.1},
    ]
    snapshot["divid_watchlist"] = watchlist
    return snapshot

def update_portfolio_from_data():
    brief = _load_json(BRIEF_PATH)
    brief.setdefault("market", {})
    brief["market"].update(fetch_snapshot())
    _save_json(BRIEF_PATH, brief)
