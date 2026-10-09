#!/usr/bin/env python3
"""Intraday ES direction, without look-ahead. Yahoo Finance is unofficial/delayed."""
import json
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "data/latest.json"
HISTORY = ROOT / "data/history.json"

def nyse_open(d):
    if d.weekday() >= 5:
        return False
    import holidays
    return d not in holidays.financial_holidays("NYSE", years=[d.year])

def chart_data():
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" +
           quote("ES=F", safe="") + "?" +
           urlencode({"interval":"5m","range":"7d","includePrePost":"true"}))
    req = Request(url, headers={"User-Agent":"Mozilla/5.0", "Accept":"application/json",
                                "Cache-Control":"no-cache"})
    with urlopen(req, timeout=18) as f:
        data = json.load(f)
    if data["chart"].get("error"):
        raise ValueError("Yahoo Finance chart error")
    result = data["chart"].get("result") or []
    if not result:
        raise ValueError("No ES quotes")
    return result[0]

def parse_bars(chart):
    stamps = chart.get("timestamp") or []
    closes = ((chart.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    if not stamps or len(stamps) != len(closes):
        raise ValueError("Missing or misaligned 5m bars")
    bars = {}
    for stamp, raw in zip(stamps, closes):
        if raw is None:
            continue
        val = float(raw)
        if not math.isfinite(val) or val <= 0:
            continue
        t = datetime.fromtimestamp(int(stamp), timezone.utc).astimezone(NY)
        if t.minute % 5 == 0 and t.second == 0:
            bars[(t.date(), t.hour, t.minute)] = val
    return bars

def previous_session(today, is_open=nyse_open):
    day = today-timedelta(days=1)
    for _ in range(8):
        if is_open(day):
            return day
        day -= timedelta(days=1)
    raise ValueError("No previous NYSE trading session")

def signal(chart, now, is_open=nyse_open):
    local = now.astimezone(NY)
    today = local.date()
    r = {"date":today.isoformat(), "calculated_at_utc":now.isoformat(),
         "model":"ES_overnight_direction_5m_delayed_v1","source":"Yahoo Finance delayed",
         "status":"unavailable"}
    if not is_open(today):
        r.update(status="market_closed",reason="NYSE休場日")
        return r
    clock=local.time().replace(tzinfo=None)
    if clock<time(9,18):
        r.update(status="waiting",reason="寄り付き前の更新を待っています")
        return r
    if clock>=time(9,30):
        r.update(status="expired",reason="9:30以降の事後予測は禁止しています")
        return r
    if chart is None:
        r["reason"]="先物の時刻付きデータを取得できません"
        return r
    try:
        b=parse_bars(chart)
        prev=previous_session(today,is_open)
        first=b.get((prev,15,55))
        last=b.get((today,9,5))
        if not first or not last:
            r["reason"]="前日16:00と当日9:10の5分足が揃いません"
            return r
        change=(last/first-1)*100
        if not math.isfinite(change):
            r["reason"]="異常な先物価格です"
            return r
    except (ValueError, TypeError, KeyError):
        r["reason"]="先物価格のデータ形式が不正です"
        return r
    r.update(status="ready", direction="up" if change>0 else "down" if change<0 else "flat",
             change_pct=round(change,4),
             previous_session=prev.isoformat(),
             base_bar_end_et=prev.isoformat()+" 16:00 ET",
             signal_bar_end_et=today.isoformat()+" 09:10 ET",
             issue_warning="連続先物の限月切替や無料価格の遅延に注意")
    return r

def save(r):
    LATEST.parent.mkdir(parents=True,exist_ok=True)
    try:
        before=json.loads(LATEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        before={}
    if before.get("date")==r.get("date") and before.get("status")=="ready" and r.get("status")!="ready":
        return False
    if before==r:
        return False
    LATEST.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if r.get("status")=="ready":
        try:
            hist=json.loads(HISTORY.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            hist=[]
        hist=[x for x in hist if x.get("date")!=r["date"]]
        hist.append({k:r[k] for k in ("date","direction","change_pct","calculated_at_utc","signal_bar_end_et")})
        HISTORY.write_text(json.dumps(sorted(hist,key=lambda x:x["date"])[-260:],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return True

def main():
    now=datetime.now(timezone.utc)
    local=now.astimezone(NY)
    tm=local.time().replace(tzinfo=None)
    if not nyse_open(local.date()) or tm<time(9,18) or tm>=time(9,30):
        print("Outside live prediction window; do not generate a retrospective signal.")
        return 0
    try:
        data=chart_data()
    except (HTTPError,URLError,ValueError,TimeoutError,OSError) as err:
        print("Data source unavailable:",type(err).__name__,str(err)[:120])
        data=None
    result=signal(data,now)
    print("ES signal:",result.get("date"),result["status"],result.get("direction"))
    save(result)
    return 0

if __name__=="__main__":
    sys.exit(main())
