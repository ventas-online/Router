import tempfile
import unittest
from pathlib import Path

from llmrouter.api_keys import ApiKeyStore, QuotaExceeded


class ApiKeyStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "router.sqlite3"
        self.store = ApiKeyStore(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_key_is_returned_once_and_authenticates(self):
        project = self.store.create_project("alice", "Demo")
        created = self.store.create_key("alice", project["id"], "primary")
        self.assertTrue(created["key"].startswith("rtr_live_"))
        self.assertNotIn("key", self.store.list_keys("alice", project["id"])[0])
        auth = self.store.authenticate_key(created["key"])
        self.assertEqual(auth["user_id"], "alice")
        self.assertEqual(auth["project_id"], project["id"])

    def test_revoked_key_is_rejected(self):
        project = self.store.create_project("alice", "Demo")
        created = self.store.create_key("alice", project["id"])
        self.assertTrue(self.store.revoke_key("alice", project["id"], created["id"]))
        self.assertIsNone(self.store.authenticate_key(created["key"]))

    def test_project_isolation(self):
        alice = self.store.create_project("alice", "Alice")
        bob = self.store.create_project("bob", "Bob")
        key = self.store.create_key("alice", alice["id"])
        self.assertIsNone(self.store.create_key("bob", alice["id"]))
        self.assertEqual(self.store.authenticate_key(key["key"])["user_id"], "alice")
        self.assertIsNone(self.store.get_project("bob", alice["id"]))
        self.assertEqual(self.store.get_project("bob", bob["id"])["name"], "Bob")

    def test_request_and_token_quotas(self):
        project = self.store.create_project("alice", "Limited", requests_per_day=1, tokens_per_day=5)
        self.store.check_quota(project["id"], additional_tokens=5)
        self.store.record_usage("alice", project["id"], prompt_tokens=2, completion_tokens=3, ok=True)
        with self.assertRaises(QuotaExceeded) as ctx:
            self.store.check_quota(project["id"])
        self.assertEqual(ctx.exception.kind, "requests_per_day")

        project2 = self.store.create_project("alice", "Tokens", requests_per_day=10, tokens_per_day=5)
        self.store.record_usage("alice", project2["id"], prompt_tokens=4, completion_tokens=1, ok=True)
        with self.assertRaises(QuotaExceeded) as ctx:
            self.store.check_quota(project2["id"], additional_tokens=1)
        self.assertEqual(ctx.exception.kind, "tokens_per_day")


if __name__ == "__main__":
    unittest.main()
