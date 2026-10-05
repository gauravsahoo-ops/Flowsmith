"""Providers package for Flowsmith Multi-Provider LLM Engine."""

from __future__ import annotations

from app.ai.providers.base import BaseLLMProvider, LLMResponse, LLMStreamChunk, ToolCall
from app.ai.providers.openai_provider import OpenAIProvider
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.gemini_provider import GeminiProvider
from app.ai.providers.deepseek_provider import DeepSeekProvider
from app.ai.providers.groq_provider import GroqProvider
from app.ai.providers.ollama_provider import OllamaProvider
from app.ai.providers.builtin_provider import BuiltinProvider

PROVIDERS: dict[str, type[BaseLLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "claude": AnthropicProvider,
    "gemini": GeminiProvider,
    "google": GeminiProvider,
    "deepseek": DeepSeekProvider,
    "groq": GroqProvider,
    "ollama": OllamaProvider,
    "local": OllamaProvider,
    "builtin": BuiltinProvider,
}


def get_provider(provider_name: str | None = None, model: str | None = None) -> BaseLLMProvider:
    """Factory: resolves appropriate provider instance from provider name or model prefix."""
    name = (provider_name or "").lower().strip()
    m = (model or "").lower().strip()

    if name in ("builtin", "offline", "mock") or m.startswith(("builtin", "local-ai")):
        return BuiltinProvider()

    if not name:
        if m.startswith(("claude", "anthropic")):
            name = "anthropic"
        elif m.startswith(("gemini", "google")):
            name = "gemini"
        elif m.startswith("deepseek"):
            name = "deepseek"
        elif m.startswith(("groq", "llama-3.3", "mixtral")):
            name = "groq"
        elif m.startswith(("ollama", "local")):
            name = "ollama"
        else:
            name = "openai"

    provider_cls = PROVIDERS.get(name, OpenAIProvider)
    return provider_cls()


__all__ = [
    "BaseLLMProvider",
    "LLMResponse",
    "LLMStreamChunk",
    "ToolCall",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "DeepSeekProvider",
    "GroqProvider",
    "OllamaProvider",
    "PROVIDERS",
    "get_provider",
]
