import json, time, random, urllib.request, sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "shared" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOGS_PATH = STATE_DIR / "logs.jsonl"
BRIEF_PATH = STATE_DIR / "briefing.json"
CONFIG_PATH = BASE_DIR / "config.json"
TRUMPGOV_STATE = STATE_DIR / "trumpgov.json"

POLICY_QUERIES = [
    "Trump administration executive order today",
    "Trump policy tariffs steel aluminum 2026",
    "government contracts awarded defense 2026",
    "DOGE federal efficiency cuts agencies",
    "defense spending budget increase contractors",
    "infrastructure bill funding 2026",
    "energy policy oil gas drilling permits",
    "healthcare policy pharma FDA regulation",
    "technology AI semiconductor export controls",
    "agriculture subsidies trade war",
    "federal reserve interest rate politics",
    "congress market legislation today",
]

DIVIDEND_THEMES = ["utilities", "consumer staples", "telecom", "real estate investment trust", "preferred stock", "ETN", "covered call"]
FLIP_THEMES = ["defense", "aerospace", "infrastructure", "technology", "semiconductor", "energy", "healthcare", "banking"]

def human_now():
    return datetime.now().strftime("%Y-%m-%d %I:%M %p")

def load_json(path):
    if path.exists():
        try: return json.loads(path.read_text())
        except Exception: return {}
    return {}

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))

def log(agent, level, message):
    try:
        entry = {"ts": time.time(), "agent": agent, "level": level, "message": message}
        with open(LOGS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        print(f"[trumpgov][{level}] {message}", file=sys.stderr)

def wait_for_net(max_wait=60):
    import socket
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            socket.setdefaulttimeout(3)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
            return True
        except Exception:
            time.sleep(3)
    return False

def fetch_policy_news():
    if not wait_for_net(60):
        log("trumpgov", "warn", "No internet; using briefing cache only")
        return []
    results = []
    seen = set()

    # 1) Try hermes_tools web_search (Hermes execute_code sandbox)
    try:
        from hermes_tools import web_search
        for q in POLICY_QUERIES:
            try:
                r = web_search(query=q, limit=3)
                items = r.get("data", {}).get("web", []) or []
                for it in items:
                    url = it.get("url")
                    if url and url not in seen:
                        seen.add(url)
                        results.append(it)
            except Exception as e:
                log("trumpgov", "error", f"search failed on '{q}': {e}")
                time.sleep(1)
    except Exception as e:
        log("trumpgov", "warn", f"hermes_tools.web_search unavailable: {e}")

    # 2) Fallback: yfinance ticker news for policy-relevant symbols
    if not results:
        try:
            import yfinance as yf
            syms = ["LMT","RTX","NOC","GD","BA","XOM","CVX","COP","SLB","JPM","BAC","CAT","DE","UNH","PFE","NVDA","AMD","AVGO"]
            tickers = yf.Tickers(" ".join(syms))
            for sym in syms:
                try:
                    info = tickers.tickers.get(sym)
                    if not info:
                        continue
                    news_list = getattr(info, "news", []) or []
                    for n in news_list[:2]:
                        content = n.get("content") or {}
                        title = (content.get("title") or "").strip()
                        link = (content.get("canonicalUrl") or {}).get("url") or ""
                        desc = (content.get("summary") or "").strip()
                        pub = content.get("pubDate")
                        if title and link and link not in seen:
                            seen.add(link)
                            results.append({
                                "title": title,
                                "url": link,
                                "description": desc,
                                "date": datetime.fromisoformat(pub.replace("Z", "+00:00")).isoformat() if pub else None,
                            })
                except Exception:
                    pass
        except Exception as e:
            log("trumpgov", "warn", f"yfinance fallback failed: {e}")

    # 3) Final fallback: RSS
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
                    if title and link and link not in seen:
                        seen.add(link)
                        results.append({"title": title, "url": link, "description": desc})
                if results:
                    break
            except Exception as e:
                log("trumpgov", "warn", f"RSS fetch failed for {url}: {e}")

    return results

def classify_impact(text):
    text_lower = text.lower()
    score = 0
    sectors = []
    if any(w in text_lower for w in ["defense", "military", "weapons", "lockheed", "raytheon", "northrop"]):
        score += 2; sectors.append("defense")
    if any(w in text_lower for w in ["tariff", "trade war", "import duty", "export control"]):
        score += 2; sectors.append("trade")
    if any(w in text_lower for w in ["energy", "oil", "gas", "drilling", "pipeline", "nuclear"]):
        score += 2; sectors.append("energy")
    if any(w in text_lower for w in ["healthcare", "pharma", "fda", "medicare"]):
        score += 1; sectors.append("healthcare")
    if any(w in text_lower for w in ["technology", "ai", "semiconductor", "chip", "software"]):
        score += 2; sectors.append("technology")
    if any(w in text_lower for w in ["infrastructure", "construction", "bridge", "road", "rail"]):
        score += 1; sectors.append("infrastructure")
    if any(w in text_lower for w in ["agriculture", "farm", "soybean", "corn", "crop"]):
        score += 1; sectors.append("agriculture")
    if any(w in text_lower for w in ["rate", "fed", "federal reserve", "inflation"]):
        score += 1; sectors.append("macro")
    return score, sectors

def find_ticker_for_sector(sectors, tickers):
    tickers = tickers or []
    mapping = {
        "defense": ["LMT", "RTX", "NOC", "GD", "BA"],
        "technology": ["NVDA", "AMD", "AVGO", "INTC"],
        "energy": ["XOM", "CVX", "COP", "SLB"],
        "healthcare": ["UNH", "PFE", "JNJ", "ABBV"],
        "infrastructure": ["CAT", "DE", "VMC", "BLD"],
        "agriculture": ["ADM", "BG", "CARG", "MOS"],
        "finance": ["JPM", "BAC", "WFC", "GS"],
    }
    for sec in sectors:
        for t in mapping.get(sec, []):
            if t in tickers:
                return t
    for t in tickers:
        return t
    return "SPY"

def run():
    cfg = load_json(CONFIG_PATH)
    trump_cfg = cfg.get("agents", {}).get("trumpgov", {})
    profit_target = int(trump_cfg.get("yearly_profit_target", 1000000))
    reinvest_pct = float(trump_cfg.get("reinvest_pct", 0.45))
    min_trade = int(trump_cfg.get("min_trade_size", 5000))

    state = load_json(TRUMPGOV_STATE)
    state.setdefault("trades", [])
    state.setdefault("last_run", "")
    state.setdefault("last_run_date", "")
    state.setdefault("virtual_cash", float(trump_cfg.get("starting_cash", 50000)))
    state.setdefault("realized_profit", 0.0)
    state.setdefault("suggestions_made", 0)

    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("last_run_date") != today:
        state["daily_suggestions"] = 0
        state["last_run_date"] = today

    log("trumpgov", "info", "Starting policy+contract research cycle")
    set_run_status = None
    try:
        from shared.core import set_run_status as srs
        set_run_status = srs
    except Exception:
        log("trumpgov", "warn", "set_run_status import unavailable")
    if set_run_status:
        set_run_status("trumpgov", "running", "fetching policy data")

    items = fetch_policy_news()
    validated = [it for it in items if (it.get("title") or "").strip() and (it.get("url") or "").startswith("http")]
    brief = load_json(BRIEF_PATH)
    market_tickers = list((brief.get("tickers_mentioned", {}) or {}).keys())

    high_impact = []
    for it in validated:
        text = (it.get("title", "") + " " + it.get("description", "")).strip()
        score, sectors = classify_impact(text)
        if score >= 2:
            high_impact.append({**it, "score": score, "sectors": sectors, "text": text})

    high_impact.sort(key=lambda x: x["score"], reverse=True)

    suggestions = []
    for item in high_impact[:3]:
        sym = find_ticker_for_sector(item["sectors"], market_tickers)
        is_dividend = any(t in item["text"].lower() for t in DIVIDEND_THEMES)
        s_type = "dividend_buy" if is_dividend else "quick_flip"
        reason = f"Policy impact: {item['sectors']} | {item['title'][:120]}"
        payload = {
            "symbol": sym,
            "type": s_type,
            "reason": reason,
            "source_url": item.get("url", ""),
            "source_title": item.get("title", ""),
            "sectors": item["sectors"],
            "impact_score": item["score"],
            "suggested_allocation_pct": 0.05 if is_dividend else 0.10,
            "expected_hold": "30-90 days" if not is_dividend else "12+ months",
            "target_return_pct": 8.0 if is_dividend else 15.0,
        }
        suggestions.append(payload)

    submitted_ids = []
    for sug in suggestions:
        try:
            from shared.decisions import submit_decision
            did = submit_decision("trumpgov", "investment_suggestion", sug)
            submitted_ids.append(did)
            state["suggestions_made"] = state.get("suggestions_made", 0) + 1
            state["daily_suggestions"] = state.get("daily_suggestions", 0) + 1
        except Exception as e:
            log("trumpgov", "error", f"submit_decision failed: {e}")

    state["last_run"] = human_now()
    state["last_items_analyzed"] = len(validated)
    state["high_impact_count"] = len(high_impact)
    state["suggestions_submitted"] = len(submitted_ids)
    save_json(TRUMPGOV_STATE, state)

    summary = f"Analyzed {len(validated)} sources, {len(high_impact)} high-impact, {len(submitted_ids)} suggestions submitted"
    log("trumpgov", "ok", summary)

    try:
        from control.app import broadcast_sync
        for item in high_impact[:2]:
            broadcast_sync({
                "agent": "trumpgov",
                "message": f"[{item['sectors']}] {item['title'][:80]}",
                "level": "info",
            })
        broadcast_sync({
            "agent": "trumpgov",
            "message": f"Cycle complete: {summary}",
            "level": "ok",
        })
    except Exception:
        log("trumpgov", "warn", "dashboard broadcast unavailable")

    if set_run_status:
        set_run_status("trumpgov", "done", summary)

    return {
        "agent": "trumpgov",
        "timestamp": human_now(),
        "sources_analyzed": len(validated),
        "high_impact": len(high_impact),
        "suggestions": suggestions,
        "submitted_ids": submitted_ids,
        "state": state,
    }

if __name__ == "__main__":
    result = run()
    print(f"TRUMPGOV: {result['sources_analyzed']} sources, {result['high_impact']} high-impact, {len(result['suggestions'])} suggestions")
