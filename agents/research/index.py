import json, time, socket, os, urllib.request
from pathlib import Path
from datetime import datetime
from control.cmd_router import set_run_status

BASE_DIR = Path(__file__).resolve().parent.parent.parent

STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
BRIEF_PATH = STATE_DIR / "briefing.json"
LOGS_PATH = STATE_DIR / "logs.jsonl"
CONN_PATH = STATE_DIR / "research_conn.json"
RESEARCH_LIVE = STATE_DIR / "research_live.jsonl"

WATCHLIST = [
    "federal reserve interest rate decision today",
    "treasury yield 10 year",
    "inflation CPI latest",
    "congress senate market legislation",
    "sector rotation technology healthcare",
    "oil price OPEC",
    "bitcoin correlation equities",
    "dividend aristocrats 2025",
    "NVDA MSFT AAPL earnings",
    "VIX fear index",
    "small cap Russell 2000",
    "Semiconductor sector SOXX",
]

def human_now():
    return datetime.now().strftime("%Y-%m-%d %I:%M %p")

def log(agent, level, message):
    entry = {"ts": time.time(), "agent": agent, "level": level, "message": message}
    with open(LOGS_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

def load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))

def net_is_up(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False

def wait_for_net(max_wait_seconds=120):
    deadline = time.time() + max_wait_seconds
    last = None
    while time.time() < deadline:
        ok = net_is_up()
        if ok:
            return True
        last = time.strftime("%H:%M:%S")
        log("research", "warn", f"No internet connectivity, retrying. last_check={last}")
        time.sleep(5)
    log("research", "error", f"Internet remained down for {max_wait_seconds}s")
    return False

def fetch_sources(max_retries=3, wait_timeout=120):
    assert wait_for_net(wait_timeout), f"Research requires internet connectivity; aborting fetch after {wait_timeout}s."

    results = []
    seen_urls = set()

    # 1) Try hermes_tools web_search (works in Hermes execute_code sandbox)
    try:
        from hermes_tools import web_search
        for q in WATCHLIST:
            for attempt in range(1, max_retries + 1):
                try:
                    if not wait_for_net(30):
                        break
                    r = web_search(query=q, limit=3, timeout=20)
                    items = r.get("data", {}).get("web", []) or []
                    for it in items:
                        url = it.get("url")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            results.append(it)
                    break
                except Exception as e:
                    log("research", "error", f"web_search failed on '{q}' attempt {attempt}: {e}")
                    time.sleep(3 * attempt)
    except Exception as e:
        log("research", "warn", f"hermes_tools.web_search unavailable: {e}")

    # 2) If web_search yielded nothing, fall back to yfinance ticker news + RSS
    if not results:
        try:
            import yfinance as yf
            watchlist_syms = ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","SPY","QQQ","GC=F","GLD","XLE","OXY","LMT","RTX","XOM","CVX","JPM","BAC"]
            tickers = yf.Tickers(" ".join(watchlist_syms))
            for sym in watchlist_syms:
                try:
                    info = tickers.tickers.get(sym)
                    if not info:
                        continue
                    news_list = getattr(info, "news", []) or []
                    for n in news_list[:3]:
                        content = n.get("content") or {}
                        title = (content.get("title") or "").strip()
                        link = (content.get("canonicalUrl") or {}).get("url") or ""
                        desc = (content.get("summary") or "").strip()
                        pub = content.get("pubDate")
                        if title and link and link not in seen_urls:
                            seen_urls.add(link)
                            results.append({
                                "title": title,
                                "url": link,
                                "description": desc,
                                "date": datetime.fromisoformat(pub.replace("Z", "+00:00")).isoformat() if pub else None,
                            })
                except Exception:
                    pass
        except Exception as e:
            log("research", "warn", f"yfinance fallback failed: {e}")

    # 3) Final fallback: urllib RSS from reliable public endpoints
    if not results:
        rss_urls = [
            "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ]
        for url in rss_urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read().decode("utf-8", errors="ignore")
                import re
                for m in re.finditer(r'<item[^>]*>.*?<title>(.*?)</title>.*?<description>(.*?)</description>.*?<link>(.*?)</link>', raw, re.DOTALL):
                    title = re.sub(r'<.*?>', '', m.group(1)).strip()
                    link = m.group(3).strip()
                    desc = re.sub(r'<.*?>', '', m.group(2)).strip()
                    if title and link and link not in seen_urls:
                        seen_urls.add(link)
                        results.append({"title": title, "url": link, "description": desc})
                if results:
                    break
            except Exception as e:
                log("research", "warn", f"RSS fetch failed for {url}: {e}")

    return results

def summarize_sources(items):
    tickers = ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","SPY","QQQ","IWM","SOXX","XLE","XLF","JEPI","JEPQ","SCHD","VYM","VTI","T","VZ","KO","PEP","MCD","O","REALTY","NUSI"]
    hits = []
    for it in items:
        text = (it.get("title","") + " " + it.get("description","")).upper()
        score = sum(1 for t in tickers if t in text)
        freshness = _freshness_score(it)
        if score or freshness >= 2:
            hits.append({**it, "score": score + freshness})
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:25]

def _freshness_score(item):
    boost = 0
    for key in ("date", "published", "pubDate"):
        val = item.get(key)
        if val:
            try:
                ts = datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp()
                age_h = max(0, (time.time() - ts) / 3600.0)
                if age_h < 1:
                    boost += 2
                elif age_h < 6:
                    boost += 1
                elif age_h < 24:
                    boost += 0
            except Exception:
                pass
    return boost

def validate_sources(items):
    invalid = []
    for idx, it in enumerate(items):
        title = (it.get("title") or "").strip()
        url = (it.get("url") or "").strip()
        if not title or not url.startswith("http"):
            invalid.append(idx)
    for idx in sorted(invalid, reverse=True):
        del items[idx]
    return items

def save_conn_state(connected, source_count, duration_s):
    save_json(CONN_PATH, {
        "ts": time.time(),
        "human": human_now(),
        "connected": connected,
        "source_count": source_count,
        "duration_s": duration_s,
    })

def build_briefing():
    t0 = time.time()
    set_run_status("research", "running", "connectivity check")
    connected = net_is_up()
    if not connected:
        log("research", "warn", "Initial connectivity check failed; waiting for network.")

    items = fetch_sources(max_retries=3)
    validated = validate_sources(items)
    ranked = summarize_sources(validated)

    brief = {
        "generated_at": human_now(),
        "agent": "research",
        "connectivity": {
            "connected": connected,
            "fetched": len(validated),
            "validated": len(ranked),
            "duration_s": round(time.time() - t0, 2),
        },
        "top_stories": ranked,
        "tickers_mentioned": {},
    }
    for it in ranked:
        text = (it.get("title","") + " " + it.get("description","")).upper()
        for t in ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","SPY","QQQ","IWM","SOXX","JEPI","JEPQ","SCHD","VYM","O","T"]:
            if t in text:
                brief["tickers_mentioned"][t] = brief["tickers_mentioned"].get(t, 0) + 1

    save_json(BRIEF_PATH, brief)
    save_conn_state(bool(connected and validated), len(validated), round(time.time() - t0, 2))
    try:
        from shared.core import update_ticker_series
        update_ticker_series()
    except Exception:
        pass
    log("research", "ok", f"Briefing built: {len(ranked)} validated items, connected={bool(connected and validated)}")
    set_run_status("research", "done", f"{len(ranked)} items, connectivity={bool(connected and validated)}")
    return brief


if __name__ == "__main__":
    build_briefing()
    print("RESEARCH: briefing updated")

def start_live_mode():
    import threading
    def _live_loop():
        watchlist = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "SPY", "QQQ", "GC=F", "GLD", "XLE", "OXY"]
        last_broadcast = ""
        while True:
            try:
                if net_is_up():
                    items = fetch_sources(max_retries=1, wait_timeout=10)
                    validated = validate_sources(items)
                    tickers = []
                    try:
                        from shared.core import load_json, update_ticker_series
                        brief = load_json(BRIEF_PATH)
                        tickers = list((brief.get("tickers_mentioned", {}) or {}).keys())
                    except Exception:
                        pass
                    if not tickers:
                        tickers = watchlist
                    update_ticker_series(tickers)
                    try:
                        msgs = []
                        for it in validated[:3]:
                            title = (it.get("title") or "").strip()
                            if title:
                                msgs.append(title[:120])
                        if not msgs and watchlist:
                            msgs.append(f"Live scan: {len(validated)} items; tracking {tickers[:4]}")
                        msg = " | ".join(msgs) if msgs else "Live scan complete"
                        if msg != last_broadcast:
                            try:
                                from control.app import broadcast_sync
                                broadcast_sync({
                                    "agent": "research",
                                    "message": msg,
                                    "level": "info",
                                })
                            except Exception:
                                pass
                            try:
                                entry = {
                                    "ts": time.time(),
                                    "agent": "research",
                                    "level": "info",
                                    "message": msg,
                                    "validated": len(validated),
                                    "tickers": tickers[:8],
                                }
                                with open(RESEARCH_LIVE, "a", encoding="utf-8") as f:
                                    f.write(json.dumps(entry) + "\n")
                                lines = []
                                try:
                                    with open(RESEARCH_LIVE, "r", encoding="utf-8") as f:
                                        lines = f.readlines()
                                except Exception:
                                    pass
                                while len(lines) > 200:
                                    lines.pop(0)
                                if lines:
                                    with open(RESEARCH_LIVE, "w", encoding="utf-8") as f:
                                        f.writelines(lines)
                            except Exception:
                                pass
                            last_broadcast = msg
                    except Exception:
                        pass
                else:
                    if last_broadcast != "NET DOWN":
                        try:
                            from control.app import broadcast_sync
                            broadcast_sync({"agent": "research", "message": "NET DOWN — retrying", "level": "warn"})
                        except Exception:
                            pass
                        last_broadcast = "NET DOWN"
            except Exception:
                pass
            time.sleep(30)
    threading.Thread(target=_live_loop, daemon=True).start()
