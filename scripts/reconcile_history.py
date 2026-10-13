#!/usr/bin/env python3
"""Catch up on previously saved pre-open predictions and publish one dashboard.

Forecasts must already exist in history.json / shadow_history.json. This module
never reconstructs missed forecasts after 09:30 ET. If scheduled grading fails,
a later run can grade older, genuinely archived predictions from daily SPX OHLC.
"""
import json
import math
import sys
from datetime import datetime, date, time, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_signal import ROOT, NY, nyse_open, previous_session
from verify_open import daily_ohlc

ES_HISTORY=ROOT/"data/history.json"
NQ_HISTORY=ROOT/"data/shadow_history.json"
DASHBOARD=ROOT/"data/dashboard.json"
LATEST_VERIFICATION=ROOT/"data/verification.json"

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return default

def save(path, value):
    text=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if path.exists() and path.read_text(encoding="utf-8")==text:
        return False
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding="utf-8")
    return True

def fetch_spx_history():
    # Enough history for late runs to reconcile previous days, not just today.
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+quote("^GSPC",safe="")+"?"+urlencode({
        "interval":"1d","range":"2y","events":"false"})
    req=Request(url,headers={"User-Agent":"Mozilla/5.0",
                              "Accept":"application/json","Cache-Control":"no-cache"})
    with urlopen(req,timeout=22) as response:
        payload=json.load(response)
    if payload.get("chart",{}).get("error"):
        raise ValueError("S&P500 chart returned error")
    data=payload.get("chart",{}).get("result") or []
    if not data:
        raise ValueError("S&P500 chart missing result")
    return daily_ohlc(data[0])

def opening_result(day,bars,now,is_open=nyse_open):
    """No result unless the day actually arrived AND the 10:00 ET hold elapsed."""
    target=date.fromisoformat(day)
    local=now.astimezone(NY)
    if local.date()<target:
        return None
    if local.date()==target and local.time().replace(tzinfo=None)<time(10,0):
        return None
    prior=previous_session(target,is_open)
    if target not in bars or prior not in bars:
        return None
    op=bars[target]["open"]
    close=bars[prior]["close"]
    if not (op>0 and close>0 and math.isfinite(op) and math.isfinite(close)):
        return None
    delta=100*(op/close-1)
    actual="up" if delta>0 else "down" if delta<0 else "flat"
    return {"previous_session":prior.isoformat(),
            "previous_close":round(close,4),"spx_open":round(op,4),
            "actual_direction":actual,"actual_gap_pct":round(delta,5)}

def reconcile(es, shadow, bars, now, is_open=nyse_open):
    """Mutate only already-archived ES and NQ records."""
    changed_es=changed_shadow=0
    for row in es:
        if row.get("direction") not in ("up","down"):
            continue
        if row.get("correct") is True or row.get("correct") is False:
            continue
        try:
            outcome=opening_result(row["date"],bars,now,is_open)
        except (ValueError, KeyError,TypeError):
            continue
        if outcome is None: continue
        row.update(outcome)
        row["correct"]=row["direction"]==outcome["actual_direction"]
        row["verified_at_utc"]=now.isoformat()
        changed_es+=1

    for row in shadow:
        if row.get("status")!="ready" or row.get("graded") is True:
            continue
        try:
            outcome=opening_result(row["date"],bars,now,is_open)
        except (ValueError,KeyError,TypeError):
            continue
        if outcome is None: continue
        row.update({"graded":True,"actual_direction":outcome["actual_direction"],
                    "actual_gap_pct":outcome["actual_gap_pct"],
                    "verified_at_utc":now.isoformat()})
        row["correct"]=(row["decision"]==outcome["actual_direction"]
                        if row.get("decision") in ("up","down") else None)
        changed_shadow+=1
    return changed_es,changed_shadow

def scored_stats(rows, model):
    if model=="es":
        eligible=[r for r in rows if r.get("direction") in ("up","down")]
    else:
        eligible=[r for r in rows if r.get("decision") in ("up","down")]
    scored=[r for r in eligible if r.get("correct") is True or r.get("correct") is False]
    hits=sum(r["correct"] is True for r in scored)
    return {
        "predictions":len(eligible),"scored":len(scored),
        "correct":hits,"incorrect":len(scored)-hits,
        "pending":len(eligible)-len(scored),
        "accuracy_pct":round(hits/len(scored)*100,1) if scored else None,
        "holds":(sum(r.get("decision")=="hold" for r in rows) if model=="nq" else 0),
        "recorded":len(rows)
    }

def build_dashboard(es, shadow, now):
    es_by={x["date"]:x for x in es if x.get("date")}
    nq_by={x["date"]:x for x in shadow if x.get("date")}
    days=sorted(set(es_by)|set(nq_by),reverse=True)
    timeline=[]
    for d in days:
        a=es_by.get(d,{}); b=nq_by.get(d,{})
        gap=a.get("actual_gap_pct",b.get("actual_gap_pct"))
        actual=a.get("actual_direction",b.get("actual_direction"))
        v1_status="hit" if a.get("correct") is True else "miss" if a.get("correct") is False else "pending" if a.get("direction") in ("up","down") else "unrecorded"
        v2_status=("hold" if b.get("decision")=="hold" else
                   "hit" if b.get("correct") is True else
                   "miss" if b.get("correct") is False else
                   "pending" if b.get("decision") in ("up","down") else "unrecorded")
        timeline.append({
            "date":d,
            "es_direction":a.get("direction"),
            "es_change_pct":a.get("change_pct"),
            "es_predicted_at_utc":a.get("calculated_at_utc"),
            "nq_direction":b.get("nq_direction"),
            "nq_change_pct":b.get("nq_change_pct"),
            "v2_decision":b.get("decision"),
            "spx_previous_close":a.get("previous_close"),
            "spx_open":a.get("spx_open"),
            "spx_gap_pct":gap,
            "actual_direction":actual,
            "v1_status":v1_status,
            "v2_status":v2_status,
            "v2_graded":b.get("graded") is True
        })
    return {
        "schema_version":1,
        "created_at_utc":now.isoformat(),
        "source":"GitHub archived before-open predictions + delayed Yahoo Finance ^GSPC",
        "notes":"Missed pre-open runs are never filled retrospectively. Non-prediction holds are not counted as hits.",
        "es":scored_stats(es,"es"),
        "es_nq":scored_stats(shadow,"nq"),
        "timeline":timeline
    }

def main():
    now=datetime.now(timezone.utc)
    es=load(ES_HISTORY,[])
    shadow=load(NQ_HISTORY,[])
    if not isinstance(es,list) or not isinstance(shadow,list):
        raise ValueError("History data was not a list; refusing to overwrite records.")
    try:
        bars=fetch_spx_history()
        a,b=reconcile(es,shadow,bars,now)
        print("Reconciled stored predictions: ES",a,"ES+NQ",b)
        if a:save(ES_HISTORY,es)
        if b:save(NQ_HISTORY,shadow)
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError) as err:
        print("Historical SPX unavailable, keep existing archive:",type(err).__name__,str(err)[:120])
    dashboard=build_dashboard(es,shadow,now)
    save(DASHBOARD,dashboard)
    print("Dashboard: ES",dashboard["es"]["scored"],"verified; NQ",
          dashboard["es_nq"]["scored"],"verified; timeline",len(dashboard["timeline"]))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
