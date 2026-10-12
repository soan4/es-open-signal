import unittest
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from collect_with_retry import collect, is_ready, allowed_to_wait
NY=ZoneInfo("America/New_York")

def now(h,m,s=0):
    return datetime(2026,10,13,h,m,s,tzinfo=NY)

class Clock:
    def __init__(self,dt):
        self.dt=dt
        self.calls=[]
    def get(self): return self.dt
    def sleep(self,n):
        self.calls.append(n)
        self.dt+=timedelta(seconds=n)

class RetryTest(unittest.TestCase):
    def test_early_scheduled_waits_then_captures(self):
        c=Clock(now(9,17))
        count={"es":0,"nq":0}
        def es():count["es"]+=1
        def nq():count["nq"]+=1
        def ready(path,today):
            return count["es"]>=2 and count["nq"]>=2
        status,attempts=collect("schedule",c.get,c.sleep,es,nq,ready,20)
        self.assertEqual(status,"captured")
        self.assertEqual(attempts,2)
        self.assertTrue(c.calls)
    def test_manual_push_early_returns(self):
        c=Clock(now(8,55))
        status,n=collect("push",c.get,c.sleep,lambda:None,lambda:None,
                         lambda p,d:False,20)
        self.assertEqual((status,n),("too_early",0))
    def test_late_run_does_not_predict(self):
        c=Clock(now(9,30))
        status,n=collect("schedule",c.get,c.sleep,lambda:1,lambda:1,
                         lambda p,d:False,20)
        self.assertEqual((status,n),("window_expired",0))
    def test_short_run_retries_failures(self):
        c=Clock(now(9,27))
        status,n=collect("schedule",c.get,c.sleep,lambda:None,lambda:None,
                         lambda p,d:False,20)
        self.assertEqual(status,"window_expired")
        self.assertGreaterEqual(n,2)
    def test_already_ready_no_duplicate(self):
        c=Clock(now(9,20))
        status,n=collect("schedule",c.get,c.sleep,
                 lambda: self.fail("duplicate ES"),lambda:self.fail("duplicate NQ"),
                 lambda p,d:True,20)
        self.assertEqual((status,n),("already_ready",0))
    def test_no_weekend_wait(self):
        c=Clock(datetime(2026,10,17,9,10,tzinfo=NY))
        status,n=collect("schedule",c.get,c.sleep,lambda:None,lambda:None,
                         lambda p,d:False,20)
        self.assertEqual((status,n),("market_closed",0))
    def test_scheduled_early_window(self):
        self.assertTrue(allowed_to_wait(now(8,45),"schedule"))
        self.assertFalse(allowed_to_wait(now(8,45),"push"))
if __name__=="__main__":
    unittest.main()
