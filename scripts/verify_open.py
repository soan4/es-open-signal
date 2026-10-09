#!/usr/bin/env python3
"""Verify S&P 500 cash opening gap against a previously archived ES signal.

Never construct an ES signal retrospectively; never label missing observations as wins.
Uses Yahoo Finance unofficial/delayed DAILY OHLC for ^GSPC.
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

LATEST = ROOT / "data/latest.json"
HISTORY = ROOT / "data/history.json"
VERIFICATION = ROOT / "data/verification.json"

def fetch_spx_chart():
    url=("https://query1.finance.yahoo.com/v8/finance/chart/" +
         quote("^GSPC",safe="") + "?" +
         urlencode({"interval":"1d","range":"10d","events":"false"}))
    req=Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json",
                             "Cache-Control":"no-cache"})
    with urlopen(req,timeout=18) as resp:
        data=json.load(resp)
    if data.get("chart",{}).get("error"):
        raise ValueError("S&P500 daily data unavailable")
    result=data.get("chart",{}).get("result") or []
    if not result:
        raise ValueError("No S&P500 chart result")
    return result[0]

def daily_ohlc(chart):
    stamps=chart.get("timestamp") or []
    quotes=((chart.get("indicators") or {}).get("quote") or [{}])[0]
    opens=quotes.get("open") or []
    closes=quotes.get("close") or []
    if not stamps or len(stamps)!=len(opens) or len(stamps)!=len(closes):
        raise ValueError("Incorrect S&P500 daily quote dimensions")
    rows={}
    for stamp,op,cl in zip(stamps,opens,closes):
        day=datetime.fromtimestamp(int(stamp),timezone.utc).astimezone(NY).date()
        if op is None or cl is None:
            continue
        op,cl=float(op),float(cl)
        if not (math.isfinite(op) and math.isfinite(cl) and op>0 and cl>0):
            continue
        rows[day]={"open":op,"close":cl}
    return rows

def verify(signal,chart,now,is_open=nyse_open):
    current=now.astimezone(NY)
    target=date.fromisoformat(signal["date"])
    result={"date":target.isoformat(),"status":"pending",
            "model":signal.get("model"),"signal_direction":signal.get("direction"),
            "source":"Yahoo Finance ^GSPC daily OHLC (unofficial, delayed)"}
    if signal.get("status")!="ready" or signal.get("direction") not in ("up","down"):
        result["reason"]="採点可能な寄り付き前予測がありません"
        return result
    if current.date()<target or (current.date()==target and
           current.time().replace(tzinfo=None)<time(10,0)):
        result["reason"]="現物市場の始値の反映待ち（10:00 ET以降）"
        return result
    if chart is None:
        result["reason"]="S&P500始値の取得ができません"
        return result
    bars=daily_ohlc(chart)
    prev=previous_session(target,is_open)
    if prev not in bars or target not in bars:
        result["reason"]="対象日の始値または前営業日の終値が未反映"
        return result
    opening=bars[target]["open"]
    prev_close=bars[prev]["close"]
    gap=100*(opening/prev_close-1)
    direction="up" if gap>0 else "down" if gap<0 else "flat"
    result.update(status="verified",previous_session=prev.isoformat(),
                  previous_close=round(prev_close,4),spx_open=round(opening,4),
                  actual_direction=direction,actual_gap_pct=round(gap,5),
                  correct=(direction==signal["direction"]),
                  verified_at_utc=now.isoformat())
    return result

def save(result):
    VERIFICATION.parent.mkdir(parents=True,exist_ok=True)
    if VERIFICATION.exists():
        try:
            before=json.loads(VERIFICATION.read_text(encoding="utf-8"))
            if before.get("date")==result.get("date") and before.get("status")=="verified":
                print("Existing verified result preserved")
                return False
        except (OSError,ValueError):
            pass
    VERIFICATION.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if result["status"]=="verified":
        try:
            hist=json.loads(HISTORY.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            hist=[]
        for record in hist:
            if record.get("date")==result["date"] and record.get("direction")==result["signal_direction"]:
                for key in ("previous_close","spx_open","actual_direction","actual_gap_pct",
                            "correct","verified_at_utc"):
                    record[key]=result[key]
        HISTORY.write_text(json.dumps(hist,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return True

def main():
    now=datetime.now(timezone.utc)
    clock=now.astimezone(NY)
    if clock.time().replace(tzinfo=None)<time(10,0):
        print("Do not verify before 10:00 ET")
        return 0
    try:
        signal=json.loads(LATEST.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        print("No saved ES forecast")
        return 0
    if signal.get("status")!="ready":
        print("No preopen prediction to verify; skip")
        return 0
    if not nyse_open(date.fromisoformat(signal["date"])):
        print("Target is NYSE holiday")
        return 0
    try:
        chart=fetch_spx_chart()
        output=verify(signal,chart,now)
    except (HTTPError,URLError,OSError,TimeoutError,ValueError,TypeError) as exc:
        print("S&P source error",type(exc).__name__,str(exc)[:120])
        output=verify(signal,None,now)
    save(output)
    print("Open result:",output["date"],output["status"],
          output.get("actual_direction"),output.get("correct"))
    return 0

if __name__=="__main__":
    sys.exit(main())
