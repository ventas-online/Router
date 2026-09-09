import os
import tempfile
import unittest

from llmrouter.web_store import WebStore


class WebStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.store = WebStore(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_conversation_round_trip(self):
        cid = self.store.save_conversation(None, "Hello", [{"role": "user", "content": "Hello"}])
        item = self.store.get_conversation(cid)
        self.assertEqual(item["title"], "Hello")
        self.assertEqual(item["messages"][0]["content"], "Hello")
        self.assertEqual(len(self.store.list_conversations()), 1)

    def test_analytics_counts_success_and_failure(self):
        self.store.record_request(provider="groq", model="m", latency_ms=100,
                                  prompt_tokens=10, completion_tokens=20, ok=True)
        self.store.record_request(provider="groq", model="m", latency_ms=300, ok=False,
                                  error_type="RateLimitError")
        data = self.store.analytics()
        self.assertEqual(data["requests"], 2)
        self.assertEqual(data["successes"], 1)
        self.assertEqual(data["success_rate"], 50.0)
        self.assertEqual(data["providers"][0]["tokens"], 30)

    def test_delete_conversation(self):
        cid = self.store.save_conversation(None, "Delete me", [])
        self.store.delete_conversation(cid)
        self.assertIsNone(self.store.get_conversation(cid))


if __name__ == "__main__":
    unittest.main()
