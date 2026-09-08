import unittest
from fakes import FakeProvider
from llmrouter import AllProvidersExhausted,Router,UsageTracker
class RouterTests(unittest.TestCase):
    def test_failover(self):
        a=FakeProvider("A",1,"quota",cooldown_seconds=0); b=FakeProvider("B",2,"ok")
        r=Router([a,b],usage_tracker=UsageTracker(":memory:")); self.assertEqual(r.complete([{"role":"user","content":"hola"}])["provider"],"B")
    def test_all_fail(self):
        r=Router([FakeProvider("A",1,"quota"),FakeProvider("B",2,"quota")],usage_tracker=UsageTracker(":memory:"))
        with self.assertRaises(AllProvidersExhausted): r.complete([{"role":"user","content":"hola"}])
if __name__=="__main__": unittest.main()
