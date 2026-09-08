"""Jerarquía de errores del router."""
from __future__ import annotations
from typing import List, Optional

class RouterError(Exception):
    """Error base de toda la librería."""

class ProviderError(RouterError):
    def __init__(self, provider: str, message: str, status_code: Optional[int] = None):
        self.provider = provider
        self.status_code = status_code
        suffix = f" (HTTP {status_code})" if status_code else ""
        super().__init__(f"[{provider}] {message}{suffix}")

class QuotaExceededError(ProviderError):
    pass

class RateLimitError(ProviderError):
    pass

class CircuitOpenError(ProviderError):
    pass

class AllProvidersExhausted(RouterError):
    def __init__(self, failures: List[str]):
        self.failures = failures
        super().__init__("Todos los proveedores fallaron o están agotados. Fallos: " + "; ".join(failures))
