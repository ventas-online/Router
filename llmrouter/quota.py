"""Small dependency-free quota helpers for web/API request enforcement."""
from __future__ import annotations


class QuotaExceeded(Exception):
    """Raised when a user exceeds a configured request or token quota."""

    def __init__(self, kind, limit, used):
        self.kind = kind
        self.limit = int(limit)
        self.used = int(used)
        super().__init__(f"{kind} quota exceeded: {used}/{limit}")


def check_quota(usage, *, request_limit=0, token_limit=0, additional_tokens=0):
    """Validate limits. A zero/negative limit disables that limit.

    ``usage`` is expected to contain ``requests`` and ``tokens`` counters.
    The function is intentionally side-effect free so the HTTP layer can use it
    for both normal and streaming requests without duplicating policy logic.
    """
    requests = int(usage.get("requests", 0) or 0)
    tokens = int(usage.get("tokens", 0) or 0) + max(0, int(additional_tokens or 0))
    if request_limit and requests >= int(request_limit):
        raise QuotaExceeded("requests", request_limit, requests)
    if token_limit and tokens >= int(token_limit):
        raise QuotaExceeded("tokens", token_limit, tokens)
    return {"requests": requests, "tokens": tokens}


def usage_from_analytics(analytics):
    """Normalize WebStore analytics into the quota counter shape."""
    providers = analytics.get("providers") or []
    tokens = sum(int(item.get("tokens", 0) or 0) for item in providers)
    return {"requests": int(analytics.get("requests", 0) or 0), "tokens": tokens}
