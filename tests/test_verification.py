import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from verify_open import verify
NY=ZoneInfo("America/New_York")
S={"date":"2026-10-09","status":"ready","direction":"up","model":"test"}
NOW=datetime(2026,10,9,10,20,tzinfo=NY).astimezone(timezone.utc)
def chart(today_open=7050, prior_close=7000, date_str="2026-10-09"):
  def epoch(s):
    return int(datetime.strptime(s,"%Y-%m-%d").replace(hour=9,minute=30,tzinfo=NY).timestamp())
  return {"timestamp":[epoch("2026-10-08"),epoch(date_str)],
          "indicators":{"quote":[{"open":[6970,today_open],"close":[prior_close,today_open]}]}}
class TestVerification(unittest.TestCase):
  def setUp(self):
    self.session=lambda d:d.weekday()<5
  def test_win(self):
    out=verify(S,chart(),NOW,self.session)
    self.assertEqual(out["status"],"verified")
    self.assertTrue(out["correct"])
    self.assertAlmostEqual(out["actual_gap_pct"],.71429,places=4)
  def test_miss(self):
    out=verify(S,chart(today_open=6900),NOW,self.session)
    self.assertEqual(out["actual_direction"],"down")
    self.assertFalse(out["correct"])
  def test_flat(self):
    out=verify(S,chart(today_open=7000),NOW,self.session)
    self.assertEqual(out["actual_direction"],"flat")
    self.assertFalse(out["correct"])
  def test_after_open_too_soon(self):
    early=datetime(2026,10,9,9,34,tzinfo=NY).astimezone(timezone.utc)
    out=verify(S,chart(),early,self.session)
    self.assertEqual(out["status"],"pending")
  def test_invalid_prediction(self):
    out=verify({**S,"status":"unavailable"},chart(),NOW,self.session)
    self.assertEqual(out["status"],"pending")
  def test_missing_today(self):
    c=chart(date_str="2026-10-08")
    # Duplicate date means no 10/9 daily candle
    out=verify(S,c,NOW,self.session)
    self.assertEqual(out["status"],"pending")
  def test_no_chart(self):
    self.assertEqual(verify(S,None,NOW,self.session)["status"],"pending")
if __name__=="__main__":unittest.main()
