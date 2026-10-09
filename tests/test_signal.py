import unittest
from datetime import datetime,timezone,date
from zoneinfo import ZoneInfo
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from update_signal import signal,parse_bars
NY=ZoneInfo("America/New_York")
def fixture(old,new):
    def ts(d,h,m):
        return int(datetime.fromisoformat(d).replace(hour=h,minute=m,tzinfo=NY).timestamp())
    return {"timestamp":[ts("2026-10-07",15,55),ts("2026-10-08",9,5)],
       "indicators":{"quote":[{"close":[old,new]}]}}
class TestSignal(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,8,9,22,tzinfo=NY).astimezone(timezone.utc)
        self.open=lambda d:d.weekday()<5
    def test_up(self):
        r=signal(fixture(7000,7100),self.now,self.open)
        self.assertEqual(r["direction"],"up")
        self.assertEqual(r["status"],"ready")
    def test_down(self):
        self.assertEqual(signal(fixture(7000,6900),self.now,self.open)["direction"],"down")
    def test_flat(self):
        self.assertEqual(signal(fixture(7000,7000),self.now,self.open)["direction"],"flat")
    def test_missing(self):
        r=signal({"timestamp":[],"indicators":{"quote":[{"close":[]}] }},self.now,self.open)
        self.assertEqual(r["status"],"unavailable")
    def test_after_open(self):
        later=datetime(2026,10,8,9,31,tzinfo=NY).astimezone(timezone.utc)
        self.assertEqual(signal(fixture(7000,7100),later,self.open)["status"],"expired")
    def test_summer_utc(self):
        self.assertEqual(datetime(2026,10,8,9,5,tzinfo=NY).astimezone(timezone.utc).hour,13)
    def test_winter_utc(self):
        self.assertEqual(datetime(2026,1,8,9,5,tzinfo=NY).astimezone(timezone.utc).hour,14)
    def test_weekend(self):
        sat=datetime(2026,10,10,9,22,tzinfo=NY).astimezone(timezone.utc)
        self.assertEqual(signal(None,sat,self.open)["status"],"market_closed")
if __name__=="__main__":
    unittest.main()
