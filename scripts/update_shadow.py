#!/usr/bin/env python3
"""Independent ES+NQ agreement shadow test. Never replace the live ES-only signal.

At 09:18-09:29 ET, use the already-saved ES prediction plus the NQ=F 5-minute
closes at previous NYSE 15:55 and today's 09:05 ET. After 10:00 ET grade only
using a separately archived verification from verify_open.py. No look-ahead.
"""
import json
import math
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_signal import (ROOT, NY, chart_data, parse_bars,
                           previous_session, nyse_open)

LATEST = ROOT / "data/latest.json"
SHADOW = ROOT / "data/shadow.json"
HISTORY = ROOT / "data/shadow_history.json"
VERIFIED = ROOT / "data/verification.json"

def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback

def store_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized=json.dumps(obj,ensure_ascii=False,indent=2)+"\n"
    if path.exists() and path.read_text(encoding="utf-8")==serialized:
        return False
    path.write_text(serialized,encoding="utf-8")
    return True

def capture(es_signal, nq_chart, now, is_open=nyse_open):
    today=now.astimezone(NY).date()
    clock=now.astimezone(NY).time().replace(tzinfo=None)
    out={"date":today.isoformat(),"model":"ES_NQ_agreement_delayed_v2",
         "status":"unavailable","source":"Yahoo Finance NQ=F delayed"}
    if clock<time(9,18) or clock>=time(9,30):
        out["reason"]="寄り付き前の09:18〜09:29 ETのみ記録"
        return out
    if not is_open(today):
        out["status"]="market_closed"
        return out
    if es_signal.get("date")!=today.isoformat() or es_signal.get("status")!="ready":
        out["reason"]="ES単独予測がまだ保存されていません"
        return out
    if es_signal.get("direction") not in ("up","down"):
        out["reason"]="ESの方向が判定保留"
        return out
    if nq_chart is None:
        out["reason"]="NQの時刻付きデータがまだ取得できません"
        return out
    try:
        bars=parse_bars(nq_chart)
        previous=previous_session(today,is_open)
        p=bars.get((previous,15,55))
        c=bars.get((today,9,5))
        if not p or not c:
            out["reason"]="NQの前日16:00と当日9:10の足が不足"
            return out
        change=(c/p-1)*100
        if not math.isfinite(change):
            out["reason"]="NQ価格の計算異常"
            return out
    except (ValueError,KeyError,TypeError):
        out["reason"]="NQデータの形式異常"
        return out
    nq_direction="up" if change>0 else "down" if change<0 else "flat"
    es_direction=es_signal["direction"]
    agree=nq_direction==es_direction
    out.update(status="ready",
               decision=es_direction if agree else "hold",
               agreement=agree,
               es_direction=es_direction,
               nq_direction=nq_direction,
               es_change_pct=es_signal["change_pct"],
               nq_change_pct=round(change,4),
               calculated_at_utc=now.isoformat(),
               signal_bar_end_et=today.isoformat()+" 09:10 ET")
    return out

def persist_shadow(out):
    current=read_json(SHADOW,{})
    if current.get("date")==out.get("date") and current.get("status")=="ready":
        return False
    store_json(SHADOW,out)
    if out.get("status")=="ready":
        history=read_json(HISTORY,[])
        history=[x for x in history if x.get("date")!=out["date"]]
        history.append(out)
        store_json(HISTORY,sorted(history,key=lambda r:r["date"])[-260:])
    return True

def grade_shadow(verification):
    if verification.get("status")!="verified":
        return False
    d=verification.get("date")
    history=read_json(HISTORY,[])
    change=False
    for row in history:
        if row.get("date")!=d or row.get("status")!="ready" or "graded" in row:
            continue
        actual=verification.get("actual_direction")
        if actual not in ("up","down","flat"):
            continue
        row["graded"]=True
        row["actual_direction"]=actual
        row["actual_gap_pct"]=verification.get("actual_gap_pct")
        row["correct"]=row["decision"]==actual if row["decision"] in ("up","down") else None
        change=True
    if change:
        store_json(HISTORY,history)
        snap=read_json(SHADOW,{})
        for row in history:
            if row.get("date")==snap.get("date") and row.get("date")==d:
                store_json(SHADOW,row)
                break
    return change

def main():
    now=datetime.now(timezone.utc)
    local=now.astimezone(NY)
    clock=local.time().replace(tzinfo=None)
    if not nyse_open(local.date()):
        print("NYSE holiday / weekend")
        return 0
    if time(9,18)<=clock<time(9,30):
        es=read_json(LATEST,{})
        if es.get("status")!="ready" or es.get("date")!=local.date().isoformat():
            print("ES not available yet; shadow cannot be computed")
            return 0
        prev=read_json(SHADOW,{})
        if prev.get("date")==local.date().isoformat() and prev.get("status")=="ready":
            print("Shadow already captured; do not override")
            return 0
        try:
            from urllib.parse import quote, urlencode
            from urllib.request import Request, urlopen
            url=("https://query1.finance.yahoo.com/v8/finance/chart/" +
                 quote("NQ=F",safe="") + "?" +
                 urlencode({"interval":"5m","range":"7d","includePrePost":"true"}))
            request=Request(url,headers={"User-Agent":"Mozilla/5.0",
                  "Accept":"application/json","Cache-Control":"no-cache"})
            with urlopen(request,timeout=18) as resp:
                payload=json.load(resp)
            results=payload.get("chart",{}).get("result") or []
            if payload.get("chart",{}).get("error") or not results:
                raise ValueError("NQ data unavailable")
            chart=results[0]
        except (HTTPError,URLError,OSError,TimeoutError,ValueError,KeyError) as exc:
            print("NQ source unavailable:",type(exc).__name__)
            chart=None
        obj=capture(es,chart,now)
        persist_shadow(obj)
        print("Shadow:",obj["status"],obj.get("decision"),obj.get("agreement"))
    if clock>=time(10,0):
        verification=read_json(VERIFIED,{})
        print("Shadow grading:", "updated" if grade_shadow(verification) else "waiting")
    return 0

if __name__=="__main__":
    sys.exit(main())
