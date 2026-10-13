#!/usr/bin/env python3
"""Best-effort pre-open collector with prewarming + repeated retrieval.

On scheduled or external workflow_dispatch early runs, wait for 09:18 America/New_York, then retry ES and NQ
until both are saved or NYSE 09:29:15. This reduces dependence on GitHub's
exact dispatch minute; it does not guarantee GitHub will dispatch the job.
Never generate a retrospective prediction after market opening.
"""
import json
import os
import time as sleeplib
from datetime import datetime, time, timezone, date
from pathlib import Path

from update_signal import NY, LATEST, nyse_open, main as es_main
from update_shadow import SHADOW, main as shadow_main

def clock_et():
    return datetime.now(timezone.utc).astimezone(NY)

def is_ready(path, today):
    try:
        obj=json.loads(Path(path).read_text(encoding="utf-8"))
        return obj.get("status")=="ready" and obj.get("date")==today.isoformat()
    except (OSError, ValueError):
        return False

def allowed_to_wait(local, event):
    if not nyse_open(local.date()):
        return False
    t=local.time().replace(tzinfo=None)
    # Never hold a runner open for non-scheduled pushes / manual runs early in day.
    return event in ("schedule","workflow_dispatch") and time(8,30)<=t<time(9,18)

def collect(event="push", get_now=clock_et, wait=sleeplib.sleep,
            collect_es=es_main, collect_shadow=shadow_main,
            check_ready=is_ready, max_loops=100):
    """Returns (status, attempts). Dependencies injectable for tests."""
    attempts=0
    for _ in range(max_loops):
        now=get_now()
        today=now.date()
        tm=now.time().replace(tzinfo=None)
        if not nyse_open(today):
            return ("market_closed",attempts)
        if tm>=time(9,29,15):
            # No after-the-fact 'pre-open' signals even if cron arrives late.
            return ("window_expired",attempts)
        if tm<time(9,18):
            if not allowed_to_wait(now,event):
                return ("too_early",attempts)
            remaining=((9*60+18)-(tm.hour*60+tm.minute))*60-tm.second
            wait(max(1,min(remaining,60)))
            continue

        if check_ready(LATEST,today) and check_ready(SHADOW,today):
            return ("already_ready",attempts)
        # If only ES or only NQ missing, these functions are idempotent.
        collect_es()
        collect_shadow()
        attempts+=1
        if check_ready(LATEST,today) and check_ready(SHADOW,today):
            return ("captured",attempts)
        wait(45)
    return ("retry_limit",attempts)

def main():
    event=os.environ.get("GITHUB_EVENT_NAME","push")
    outcome,n=collect(event=event)
    print("Premarket collector:",outcome,"attempts:",n,flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
