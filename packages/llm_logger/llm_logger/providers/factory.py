"""Lazy provider factory keyed by env."""
from __future__ import annotations

import os

from .base import Provider


def get_provider(name: str | None = None) -> Provider:
    name = (name or os.getenv("PROVIDER", "gemini")).lower()
    if name == "gemini":
        from .gemini import GeminiProvider
        return GeminiProvider()
    if name == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider()
    if name == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider()
    if name == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider()
    raise ValueError(f"unknown provider: {name!r}")
