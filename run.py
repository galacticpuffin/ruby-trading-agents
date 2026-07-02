#!/usr/bin/env python3
"""Trading Agents Launcher"""
import sys, time, signal, threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from shared.core import log

def run_loop():
    from agents.research.index import build_briefing as research_run
    from agents.dividend.index import run as dividend_run
    from agents.daytrader.index import run as daytrader_run
    step = 0
    while True:
        try:
            if step % 3 == 0:
                research_run()
            if step % 3 == 1:
                dividend_run()
            if step % 3 == 2:
                daytrader_run()
            step += 1
            time.sleep(60)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log("launcher", "error", f"Loop error: {e}")
            time.sleep(10)

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--ui", action="store_true", help="Start operator window")
    p.add_argument("--agent", choices=["research","dividend","daytrader"], help="Run single agent loop")
    p.add_argument("--run-now", action="store_true", help="Run all agents once then exit")
    args = p.parse_args()

    if args.ui:
        log("launcher", "info", "Starting control window on :8080")
        from control.app import app
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8080)
        return

    if args.agent:
        if args.agent == "research":
            from agents.research.index import build_briefing as run
        elif args.agent == "dividend":
            from agents.dividend.index import run as run
        else:
            from agents.daytrader.index import run as run
        while True:
            try:
                run()
            except KeyboardInterrupt:
                break
            except Exception as e:
                log(args.agent, "error", str(e))
            time.sleep(60)
        return

    if args.run_now:
        log("launcher", "info", "Running all agents once")
        from agents.research.index import build_briefing as research_run
        from agents.dividend.index import run as dividend_run
        from agents.daytrader.index import run as daytrader_run
        research_run()
        dividend_run()
        daytrader_run()
        print("All agents ran once.")
        return

    log("launcher", "info", "Starting agent loop")
    run_loop()

if __name__ == "__main__":
    main()
