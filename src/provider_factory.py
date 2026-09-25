"""Builds the configured LLMProvider - one place that reads settings.llm_provider
so the rest of the codebase never branches on provider choice."""
from __future__ import annotations

from src.config import Settings
from src.llm_providers.base import LLMProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "groq":
        if not settings.groq_api_key:
            raise ValueError(
                "llm_provider is 'groq' but GROQ_API_KEY is not set in .env. "
                "Get a free key at https://console.groq.com"
            )
        from src.llm_providers.groq_provider import GroqProvider
        return GroqProvider(settings)

    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("llm_provider is 'anthropic' but ANTHROPIC_API_KEY is not set in .env")
        from src.llm_providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(settings)

    raise ValueError(f"Unknown llm_provider: {settings.llm_provider!r} (expected 'groq' or 'anthropic')")
