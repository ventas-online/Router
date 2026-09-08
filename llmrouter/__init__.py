"""LLM Router — enrutador de modelos IA gratuitos con failover automático."""

__version__ = "1.0.0"

from .core.errors import (
    RouterError, ProviderError, QuotaExceededError, RateLimitError,
    CircuitOpenError, AllProvidersExhausted,
)
from .core.provider import Provider, OpenAICompatibleProvider, GeminiProvider
from .core.router import Router
from .core.usage_tracker import UsageTracker
from .env import load_env
from .providers import build_providers_from_env, PROVIDER_CATALOG
from .skills import discover_skills, SkillRegistry

__all__ = [
    "Router", "Provider", "OpenAICompatibleProvider", "GeminiProvider",
    "UsageTracker", "load_env", "build_providers_from_env", "PROVIDER_CATALOG",
    "discover_skills", "SkillRegistry", "RouterError", "ProviderError",
    "QuotaExceededError", "RateLimitError", "CircuitOpenError", "AllProvidersExhausted",
]
