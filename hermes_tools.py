"""
Minimal compatibility shim for hermes_tools in the trading-agents venv.

Provides web_search as a no-op fallback so imports succeed and the
research agent cleanly falls back to yfinance/RSS.
"""

def web_search(*args, **kwargs):
    return {"data": {"web": []}}
