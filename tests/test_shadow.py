import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from update_shadow import capture

NY=ZoneInfo("America/New_York")
ES={"date":"2026-10-09","status":"ready","direction":"up","change_pct":0.3134}
TIME=datetime(2026,10,9,9,22,tzinfo=NY).astimezone(timezone.utc)

def chart(p,c):
    def timestamp(d,h,m):
        return int(datetime.fromisoformat(d).replace(hour=h,minute=m,tzinfo=NY).timestamp())
    return {"timestamp":[timestamp("2026-10-08",15,55),timestamp("2026-10-09",9,5)],
            "indicators":{"quote":[{"close":[p,c]}]}}

class ShadowTest(unittest.TestCase):
    def setUp(self):
        self.open=lambda d:d.weekday()<5
    def test_agree_up(self):
        s=capture(ES,chart(20000,20100),TIME,self.open)
        self.assertEqual(s["status"],"ready")
        self.assertEqual(s["decision"],"up")
        self.assertTrue(s["agreement"])
    def test_disagreement_hold(self):
        s=capture(ES,chart(20000,19900),TIME,self.open)
        self.assertEqual(s["decision"],"hold")
        self.assertFalse(s["agreement"])
    def test_flat_is_hold(self):
        s=capture(ES,chart(20000,20000),TIME,self.open)
        self.assertEqual(s["decision"],"hold")
    def test_not_when_es_missing(self):
        s=capture({**ES,"status":"unavailable"},chart(1,2),TIME,self.open)
        self.assertEqual(s["status"],"unavailable")
    def test_no_future_leakage(self):
        later=datetime(2026,10,9,9,31,tzinfo=NY).astimezone(timezone.utc)
        s=capture(ES,chart(20000,20100),later,self.open)
        self.assertEqual(s["status"],"unavailable")
    def test_nq_missing(self):
        s=capture(ES,None,TIME,self.open)
        self.assertEqual(s["status"],"unavailable")

if __name__=="__main__":
    unittest.main()
