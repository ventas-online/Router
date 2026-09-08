import unittest
from fakes import FakeProvider
from llmrouter import Router,UsageTracker
class SkillsTests(unittest.TestCase):
    def test_discovery_and_run(self):
        r=Router([FakeProvider("A",1,"ok")],usage_tracker=UsageTracker(":memory:"))
        self.assertIn("translate",[x["name"] for x in r.list_skills()]); self.assertTrue(r.run_skill("translate",text="hola",to="inglés"))
if __name__=="__main__": unittest.main()
