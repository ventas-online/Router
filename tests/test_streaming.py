import unittest

from llmrouter.core.errors import ProviderError, QuotaExceededError
from llmrouter.core.provider import Provider
from llmrouter.core.router import Router
from tests.fakes import FakeProvider


class StreamingProvider(Provider):
    def __init__(self, name, priority, events, fail=None):
        super().__init__(name=name, priority=priority, models=["stream-model"])
        self.events = events
        self.fail = fail

    def complete(self, *args, **kwargs):
        raise NotImplementedError

    def stream(self, messages, model=None, temperature=None, max_tokens=None, timeout=60):
        if self.fail == "quota":
            raise QuotaExceededError(self.name, "quota", 429)
        if self.fail == "error":
            raise ProviderError(self.name, "failed", 500)
        for event in self.events:
            yield dict(event)


class StreamingTests(unittest.TestCase):
    def test_stream_yields_deltas_and_records_usage(self):
        provider = StreamingProvider(
            "primary",
            1,
            [
                {"type": "delta", "content": "hel", "model": "stream-model", "provider": "primary"},
                {"type": "delta", "content": "lo", "model": "stream-model", "provider": "primary"},
                {"type": "usage", "usage": {"prompt_tokens": 5, "completion_tokens": 2}, "model": "stream-model", "provider": "primary"},
                {"type": "done", "model": "stream-model", "provider": "primary"},
            ],
        )
        events = list(Router([provider]).stream([{"role": "user", "content": "hi"}]))
        self.assertEqual("hello", "".join(e.get("content", "") for e in events if e["type"] == "delta"))
        self.assertEqual(0, provider.consecutive_failures)

    def test_stream_fails_over_before_first_delta(self):
        first = StreamingProvider("first", 1, [], fail="error")
        second = StreamingProvider(
            "second",
            2,
            [
                {"type": "delta", "content": "ok", "model": "stream-model", "provider": "second"},
                {"type": "usage", "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "model": "stream-model", "provider": "second"},
                {"type": "done", "model": "stream-model", "provider": "second"},
            ],
        )
        router = Router([first, second], max_retries=0)
        events = list(router.stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(["ok"], [e["content"] for e in events if e["type"] == "delta"])
        self.assertEqual(1, first.consecutive_failures)
        self.assertEqual(0, second.consecutive_failures)

    def test_stream_does_not_fail_over_after_output_started(self):
        class BrokenAfterOutput(StreamingProvider):
            def stream(self, *args, **kwargs):
                yield {"type": "delta", "content": "partial", "model": "stream-model", "provider": self.name}
                raise ProviderError(self.name, "connection lost", 500)

        first = BrokenAfterOutput("first", 1, [])
        second = FakeProvider("second", 2, "success")
        router = Router([first, second], max_retries=0)
        with self.assertRaises(ProviderError):
            list(router.stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(0, second.consecutive_failures)


if __name__ == "__main__":
    unittest.main()
