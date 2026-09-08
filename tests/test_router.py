"""Tests del router: failover, circuit breaker, límites y tracking."""
import os
import tempfile
import unittest

from fakes import FakeProvider

from llmrouter import AllProvidersExhausted, QuotaExceededError, Router, UsageTracker


class RouterFailoverTests(unittest.TestCase):
    def test_failover_cuando_el_primero_agota_cuota(self):
        a = FakeProvider("A-agotado", priority=1, outcome="quota")
        b = FakeProvider("B-sano", priority=2, outcome="ok")
        router = Router(providers=[a, b], usage_tracker=UsageTracker(":memory:"))
        resp = router.complete([{"role": "user", "content": "hola"}])
        self.assertEqual(resp["provider"], "B-sano")
        self.assertIn("B-sano", resp["content"])
        self.assertTrue(a.in_cooldown())

    def test_failover_ante_error_500_con_reintento(self):
        a = FakeProvider("A-error", priority=1, outcome="error")
        b = FakeProvider("B-sano", priority=2, outcome="ok")
        router = Router(providers=[a, b], max_retries=1, base_delay=0, usage_tracker=UsageTracker(":memory:"))
        resp = router.complete([{"role": "user", "content": "hola"}])
        self.assertEqual(resp["provider"], "B-sano")

    def test_circuit_breaker_se_abre_y_no_se_vuelve_a_intentar(self):
        a = FakeProvider("A-inestable", priority=1, outcome="quota", failure_threshold=2, cooldown_seconds=0)
        b = FakeProvider("B-sano", priority=2, outcome="ok")
        router = Router(providers=[a, b], usage_tracker=UsageTracker(":memory:"))
        router.complete([{"role": "user", "content": "1"}])
        router.complete([{"role": "user", "content": "2"}])
        self.assertTrue(a.circuit_open())
        resp = router.complete([{"role": "user", "content": "3"}])
        self.assertEqual(resp["provider"], "B-sano")

    def test_todos_los_proveedores_agotados(self):
        a = FakeProvider("A", priority=1, outcome="quota")
        b = FakeProvider("B", priority=2, outcome="quota")
        router = Router(providers=[a, b], usage_tracker=UsageTracker(":memory:"))
        with self.assertRaises(AllProvidersExhausted) as cm:
            router.complete([{"role": "user", "content": "hola"}])
        self.assertIn("A", str(cm.exception))

    def test_limite_diario_fuerza_failover(self):
        a = FakeProvider("A", priority=1, outcome="ok")
        b = FakeProvider("B", priority=2, outcome="ok")
        router = Router(providers=[a, b], daily_limits={"A": 13}, usage_tracker=UsageTracker(":memory:"))
        router.complete([{"role": "user", "content": "1"}])
        resp = router.complete([{"role": "user", "content": "2"}])
        self.assertEqual(resp["provider"], "B")
        self.assertTrue(router._over_limit("A"))

    def test_exito_resetea_fallos(self):
        a = FakeProvider("A-flaky", priority=1, outcome="quota", failure_threshold=1)
        b = FakeProvider("B", priority=2, outcome="ok")
        router = Router(providers=[a, b], usage_tracker=UsageTracker(":memory:"))
        router.complete([{"role": "user", "content": "1"}])
        a.record_success()
        self.assertFalse(a.circuit_open())
        self.assertEqual(a.consecutive_failures, 0)


class UsageTrackerTests(unittest.TestCase):
    def test_usage_se_acumula_y_persiste(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "usage.json")
            t = UsageTracker(path)
            t.record("groq", "llama-3.3-70b", {"prompt_tokens": 100, "completion_tokens": 50})
            t.record("groq", "llama-3.3-70b", {"prompt_tokens": 10, "completion_tokens": 5})
            t2 = UsageTracker(path)
            self.assertEqual(t2.get_day_usage("groq"), 165)
            self.assertEqual(t2.totals("groq")["requests"], 2)

    def test_limite_diario_cero_o_sin_limite(self):
        t = UsageTracker(":memory:")
        self.assertEqual(t.get_day_usage("no-existe"), 0)


if __name__ == "__main__":
    unittest.main()
