import unittest

from llmrouter.quota import QuotaExceeded, check_quota, usage_from_analytics


class QuotaTests(unittest.TestCase):
    def test_disabled_limits_allow_usage(self):
        self.assertEqual(check_quota({"requests": 999, "tokens": 999}), {"requests": 999, "tokens": 999})

    def test_request_limit(self):
        with self.assertRaises(QuotaExceeded) as ctx:
            check_quota({"requests": 10, "tokens": 20}, request_limit=10)
        self.assertEqual(ctx.exception.kind, "requests")

    def test_token_limit_includes_new_tokens(self):
        with self.assertRaises(QuotaExceeded) as ctx:
            check_quota({"requests": 1, "tokens": 90}, token_limit=100, additional_tokens=10)
        self.assertEqual(ctx.exception.kind, "tokens")

    def test_analytics_normalization(self):
        self.assertEqual(
            usage_from_analytics({"requests": 4, "providers": [{"tokens": 7}, {"tokens": 3}]}),
            {"requests": 4, "tokens": 10},
        )


if __name__ == "__main__":
    unittest.main()
