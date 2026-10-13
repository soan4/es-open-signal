import unittest
import sys
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from reconcile_history import reconcile, build_dashboard, opening_result
NY=ZoneInfo("America/New_York")
NOW=datetime(2026,10,13,11,0,tzinfo=NY).astimezone(timezone.utc)
BARS={
 __import__("datetime").date(2026,10,9):{"close":7770.0,"open":7760.0},
 __import__("datetime").date(2026,10,12):{"close":7800.0,"open":7790.0},
 __import__("datetime").date(2026,10,13):{"close":7800.0,"open":7820.0}
}
OPEN=lambda d:d.weekday()<5
class TestReconcile(unittest.TestCase):
 def test_backfill_es_forecast_from_previous_day(self):
  es=[{"date":"2026-10-12","direction":"down","change_pct":-0.2}]
  nq=[]
  self.assertEqual(reconcile(es,nq,BARS,NOW,OPEN),(1,0))
  self.assertEqual(es[0]["previous_close"],7770)
  self.assertFalse(es[0]["correct"])
 def test_backfill_only_stored_forecasts(self):
  es=[]
  nq=[]
  reconcile(es,nq,BARS,NOW,OPEN)
  self.assertEqual(build_dashboard(es,nq,NOW)["timeline"],[])
 def test_grade_on_hold_without_marking_correct(self):
  nq=[{"date":"2026-10-12","status":"ready","decision":"hold","nq_direction":"down"}]
  a,b=reconcile([],nq,BARS,NOW,OPEN)
  self.assertEqual(b,1)
  self.assertIsNone(nq[0]["correct"])
  stats=build_dashboard([],nq,NOW)["es_nq"]
  self.assertEqual((stats["holds"],stats["scored"],stats["predictions"]),(1,0,0))
 def test_pending_forecast_not_marked_as_win(self):
  es=[{"date":"2026-10-13","direction":"up"}]
  now=datetime(2026,10,13,9,47,tzinfo=NY).astimezone(timezone.utc)
  reconcile(es,[],BARS,now,OPEN)
  self.assertNotIn("correct",es[0])
  self.assertEqual(build_dashboard(es,[],now)["es"]["pending"],1)
 def test_preserve_existing_evaluation(self):
  es=[{"date":"2026-10-12","direction":"up","correct":False,"actual_gap_pct":-1}]
  self.assertEqual(reconcile(es,[],BARS,NOW,OPEN),(0,0))
  self.assertEqual(es[0]["actual_gap_pct"],-1)
 def test_dashboard_stats_and_rows(self):
  es=[{"date":"2026-10-09","direction":"up","correct":True,"actual_direction":"up","actual_gap_pct":.2},
      {"date":"2026-10-12","direction":"down","correct":False,"actual_direction":"up","actual_gap_pct":.5}]
  nq=[{"date":"2026-10-12","status":"ready","decision":"hold","graded":True,"correct":None,"actual_direction":"up"}]
  v=build_dashboard(es,nq,NOW)
  self.assertEqual((v["es"]["correct"],v["es"]["scored"],v["es"]["accuracy_pct"]),(1,2,50.0))
  self.assertEqual(v["timeline"][0]["v2_status"],"hold")
 def test_live_time_restriction(self):
  now=datetime(2026,10,13,9,59,tzinfo=NY).astimezone(timezone.utc)
  self.assertIsNone(opening_result("2026-10-13",BARS,now,OPEN))
 def test_previous_session_weekend(self):
  result=opening_result("2026-10-12",BARS,NOW,OPEN)
  self.assertEqual(result["previous_session"],"2026-10-09")
if __name__=="__main__":
 unittest.main()
