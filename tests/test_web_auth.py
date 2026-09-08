import tempfile
import unittest

from llmrouter.web_store import WebStore


class WebAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.store = WebStore(self.tmp.name)

    def tearDown(self):
        import os
        os.unlink(self.tmp.name)

    def test_user_password_and_session_round_trip(self):
        user = self.store.create_user("Test@Example.com", "correct horse battery")
        self.assertEqual(user["email"], "test@example.com")
        self.assertIsNone(self.store.create_user("test@example.com", "another password"))
        self.assertIsNotNone(self.store.authenticate_user("TEST@example.com", "correct horse battery"))
        self.assertIsNone(self.store.authenticate_user("test@example.com", "wrong password"))
        token = self.store.create_session(user["id"], ttl_seconds=60)
        self.assertEqual(self.store.get_user_by_session(token)["id"], user["id"])
        self.store.delete_session(token)
        self.assertIsNone(self.store.get_user_by_session(token))

    def test_conversations_are_isolated_by_user(self):
        alice = self.store.create_user("alice@example.com", "alice password 123")
        bob = self.store.create_user("bob@example.com", "bob password 123")
        cid = self.store.save_conversation(alice["id"], None, "Alice", [{"role": "user", "content": "private"}])
        self.assertIsNotNone(self.store.get_conversation(alice["id"], cid))
        self.assertIsNone(self.store.get_conversation(bob["id"], cid))
        self.assertEqual(len(self.store.list_conversations(alice["id"])), 1)
        self.assertEqual(len(self.store.list_conversations(bob["id"])), 0)


if __name__ == "__main__":
    unittest.main()
