"""LLM Provider Adapters, Model Discovery, Normalization & Caching for Flowsmith.

Handles live API validation, lightweight probes, normalized model conversion,
and thread-safe in-memory model caching with TTL.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Any, Optional

import httpx

from app.ai.llm_registry import LLMModel, LLMProviderDefinition

logger = logging.getLogger("ai.llm_adapters")


# =============================================================================
# MODEL NORMALIZER
# =============================================================================

def normalize_model_capabilities(model_id: str, raw_meta: dict[str, Any] | None = None) -> dict[str, bool]:
    """Deterministically derive capabilities from model ID and provider metadata."""
    m = model_id.lower()
    meta = raw_meta or {}

    # Reasoning capability (o1, o3, DeepSeek R1, Claude 3.7 hybrid, QwQ, etc.)
    is_reasoning = bool(
        "reasoning" in m
        or "reasoner" in m
        or re.search(r"\b(o1|o3|r1|qwq)\b", m)
        or "deepseek-r1" in m
        or "claude-3-7" in m
        or meta.get("reasoning")
        or "thinking" in m
    )

    # Vision capability (multimodal, vision, omni, vl)
    is_vision = bool(
        "vision" in m
        or "-vl" in m
        or "vl-" in m
        or "gpt-4o" in m
        or "claude-3" in m
        or "gemini" in m
        or "pixtral" in m
        or "omni" in m
        or "multimodal" in m
        or meta.get("vision")
    )

    # Embedding capability
    is_embedding = bool("embed" in m or "text-embedding" in m or meta.get("embeddings"))

    # Tool calling
    supports_tools = not is_embedding and ("whisper" not in m and "tts" not in m and "dall-e" not in m)

    # Image generation
    is_image = bool("dall-e" in m or "flux" in m or "midjourney" in m or "stable-diffusion" in m or "imagen" in m)

    return {
        "chat": not is_embedding and not is_image,
        "reasoning": is_reasoning,
        "vision": is_vision,
        "tools": supports_tools,
        "streaming": not is_embedding and not is_image,
        "embeddings": is_embedding,
        "audio": "audio" in m or "whisper" in m or "gemini-1.5" in m or "gemini-2.0" in m or "omni" in m,
        "imageGeneration": is_image,
    }


def normalize_context_window(model_id: str, raw_meta: dict[str, Any] | None = None) -> Optional[int]:
    """Derive context window token count from metadata or standard architecture specs."""
    meta = raw_meta or {}
    raw_limit = meta.get("context_window") or meta.get("context_length") or meta.get("input_token_limit")
    if raw_limit:
        return int(raw_limit)

    m = model_id.lower()
    if "gemini-1.5-pro" in m or "gemini-2.0-pro" in m:
        return 2097152  # 2M tokens
    if "gemini" in m:
        return 1048576  # 1M tokens
    if "claude-3" in m or "claude-2" in m:
        return 200000   # 200K tokens
    if "o1" in m or "o3" in m:
        return 200000   # 200K tokens
    if "gpt-4o" in m or "gpt-4-turbo" in m or "gpt-4-1106" in m:
        return 128000   # 128K tokens
    if "llama-3.3" in m or "llama-3.1" in m or "qwen2.5" in m or "mistral-large" in m or "sonar" in m:
        return 128000   # 128K tokens
    if "deepseek" in m:
        return 64000    # 64K tokens
    if "qwen" in m:
        return 32768    # 32K tokens
    if "gpt-4" in m:
        return 8192     # 8K tokens
    if "gpt-3.5" in m:
        return 16385    # 16K tokens

    return 32768


# =============================================================================
# MODEL CACHE (Server-Side In-Memory with TTL)
# =============================================================================

class ModelCache:
    """Thread-safe in-memory cache for discovered models with TTL."""

    def __init__(self, default_ttl_s: int = 3600) -> None:
        self.default_ttl_s = default_ttl_s
        self._cache: dict[str, tuple[float, list[LLMModel]]] = {}
        self._lock = asyncio.Lock()

    def _hash_key(self, provider_id: str, variant: str, identifier: str) -> str:
        h = hashlib.sha256(f"{provider_id}:{variant}:{identifier}".encode()).hexdigest()[:24]
        return f"{provider_id}:{variant}:{h}"

    async def get(self, provider_id: str, variant: str, identifier: str) -> Optional[list[LLMModel]]:
        async with self._lock:
            key = self._hash_key(provider_id, variant, identifier)
            if key not in self._cache:
                return None
            ts, models = self._cache[key]
            if time.time() - ts > self.default_ttl_s:
                del self._cache[key]
                return None
            return models

    async def set(self, provider_id: str, variant: str, identifier: str, models: list[LLMModel]) -> None:
        async with self._lock:
            key = self._hash_key(provider_id, variant, identifier)
            self._cache[key] = (time.time(), models)

    async def invalidate(self, provider_id: str, variant: str, identifier: str) -> None:
        async with self._lock:
            key = self._hash_key(provider_id, variant, identifier)
            self._cache.pop(key, None)

    async def clear_all(self) -> None:
        async with self._lock:
            self._cache.clear()


_MODEL_CACHE = ModelCache()


def get_model_cache() -> ModelCache:
    return _MODEL_CACHE


# =============================================================================
# ADAPTER IMPLEMENTATIONS
# =============================================================================

class BaseLLMAdapter:
    """Abstract base class for provider connection testing and model discovery."""

    def __init__(self, provider: LLMProviderDefinition) -> None:
        self.provider = provider

    async def test_connection(self, cred_data: dict[str, Any], variant: str = "") -> dict[str, Any]:
        """Validate credentials using the cheapest possible endpoint."""
        raise NotImplementedError

    async def discover_models(self, cred_data: dict[str, Any], variant: str = "") -> list[LLMModel]:
        """Fetch and normalize available models from provider API or catalog."""
        raise NotImplementedError

    def _get_base_url(self, cred_data: dict[str, Any], variant: str = "") -> str:
        if cred_data.get("base_url"):
            return str(cred_data["base_url"]).rstrip("/")
        if variant and self.provider.variants:
            for v in self.provider.variants:
                if v.id == variant and v.base_url:
                    return v.base_url.rstrip("/")
        if self.provider.base_url:
            return self.provider.base_url.rstrip("/")
        return ""


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """Universal adapter for OpenAI, OpenRouter, Groq, DeepSeek, Mistral, Cerebras, Together, etc."""

    async def test_connection(self, cred_data: dict[str, Any], variant: str = "") -> dict[str, Any]:
        base_url = self._get_base_url(cred_data, variant)
        api_key = (cred_data.get("api_key") or "").strip()
        models_endpoint = self.provider.api_endpoints.get("models", "/models")

        if not base_url:
            return {"ok": False, "message": "Base URL is required.", "code": "INVALID_CONFIGURATION"}

        url = f"{base_url}{models_endpoint}"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if cred_data.get("organization"):
            headers["OpenAI-Organization"] = str(cred_data["organization"]).strip()

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
                latency_ms = round((time.perf_counter() - start) * 1000, 1)

                if resp.status_code == 200:
                    return {
                        "ok": True,
                        "message": f"Successfully connected to {self.provider.display_name} ({latency_ms}ms).",
                        "latency_ms": latency_ms,
                        "provider": self.provider.provider_id,
                    }
                elif resp.status_code in (401, 403):
                    return {
                        "ok": False,
                        "message": f"Authentication failed (HTTP {resp.status_code}): Invalid API key or unauthorized.",
                        "code": "INVALID_CREDENTIALS",
                        "provider": self.provider.provider_id,
                    }
                elif resp.status_code == 429:
                    return {
                        "ok": False,
                        "message": "Rate limit exceeded on provider endpoint.",
                        "code": "RATE_LIMITED",
                        "provider": self.provider.provider_id,
                    }
                else:
                    return {
                        "ok": False,
                        "message": f"Provider returned HTTP {resp.status_code}: {resp.text[:180]}",
                        "code": "PROVIDER_UNAVAILABLE",
                        "provider": self.provider.provider_id,
                    }
        except httpx.TimeoutException:
            return {
                "ok": False,
                "message": f"Connection timed out contacting {self.provider.display_name}.",
                "code": "TIMEOUT",
                "provider": self.provider.provider_id,
            }
        except Exception as e:
            return {
                "ok": False,
                "message": f"Network or protocol error: {str(e)[:200]}",
                "code": "PROVIDER_UNAVAILABLE",
                "provider": self.provider.provider_id,
            }

    async def discover_models(self, cred_data: dict[str, Any], variant: str = "") -> list[LLMModel]:
        base_url = self._get_base_url(cred_data, variant)
        api_key = (cred_data.get("api_key") or "").strip()
        models_endpoint = self.provider.api_endpoints.get("models", "/models")
        url = f"{base_url}{models_endpoint}"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if cred_data.get("organization"):
            headers["OpenAI-Organization"] = str(cred_data["organization"]).strip()

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    payload = resp.json()
                    raw_list = payload.get("data") or payload.get("models") or payload
                    if isinstance(raw_list, list):
                        discovered: list[LLMModel] = []
                        for item in raw_list:
                            mid = item.get("id") if isinstance(item, dict) else str(item)
                            if not mid:
                                continue
                            name = (item.get("name") if isinstance(item, dict) else None) or mid
                            caps = normalize_model_capabilities(mid, item if isinstance(item, dict) else {})
                            ctx = normalize_context_window(mid, item if isinstance(item, dict) else {})
                            desc = item.get("description", "") if isinstance(item, dict) else ""
                            discovered.append(LLMModel(
                                id=mid,
                                name=name,
                                provider_id=self.provider.provider_id,
                                description=desc,
                                capabilities=caps,
                                context_window=ctx,
                                source="live",
                            ))
                        if discovered:
                            return sorted(discovered, key=lambda m: m.name.lower())
        except Exception as exc:
            logger.warning("Dynamic model discovery failed for %s: %s; falling back to catalog", self.provider.provider_id, exc)

        # Fallback to static model catalog if live discovery fails
        if self.provider.model_catalog:
            return self.provider.model_catalog
        return []


class AnthropicAdapter(BaseLLMAdapter):
    """Adapter for Anthropic Claude Models API."""

    async def test_connection(self, cred_data: dict[str, Any], variant: str = "") -> dict[str, Any]:
        api_key = (cred_data.get("api_key") or "").strip()
        if not api_key:
            return {"ok": False, "message": "Anthropic API key is required.", "code": "INVALID_CREDENTIALS"}

        base_url = self._get_base_url(cred_data, variant) or "https://api.anthropic.com"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{base_url}/v1/models", headers=headers)
                latency_ms = round((time.perf_counter() - start) * 1000, 1)

                if resp.status_code == 200:
                    return {
                        "ok": True,
                        "message": f"Anthropic API connection verified successfully ({latency_ms}ms).",
                        "latency_ms": latency_ms,
                        "provider": "anthropic",
                    }
                elif resp.status_code in (401, 403):
                    return {
                        "ok": False,
                        "message": "Invalid Anthropic API Key or unauthorized.",
                        "code": "INVALID_CREDENTIALS",
                        "provider": "anthropic",
                    }
                elif resp.status_code == 429:
                    return {
                        "ok": False,
                        "message": "Anthropic rate limit reached.",
                        "code": "RATE_LIMITED",
                        "provider": "anthropic",
                    }
                else:
                    return {
                        "ok": False,
                        "message": f"Anthropic returned HTTP {resp.status_code}: {resp.text[:180]}",
                        "code": "PROVIDER_UNAVAILABLE",
                        "provider": "anthropic",
                    }
        except Exception as e:
            return {"ok": False, "message": f"Connection error: {str(e)[:200]}", "code": "PROVIDER_UNAVAILABLE"}

    async def discover_models(self, cred_data: dict[str, Any], variant: str = "") -> list[LLMModel]:
        api_key = (cred_data.get("api_key") or "").strip()
        base_url = self._get_base_url(cred_data, variant) or "https://api.anthropic.com"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{base_url}/v1/models", headers=headers)
                if resp.status_code == 200:
                    items = resp.json().get("data", [])
                    models = []
                    for it in items:
                        mid = it.get("id")
                        if mid:
                            models.append(LLMModel(
                                id=mid,
                                name=it.get("display_name") or mid,
                                provider_id="anthropic",
                                description=f"Anthropic {mid}",
                                capabilities=normalize_model_capabilities(mid),
                                context_window=normalize_context_window(mid),
                                source="live",
                            ))
                    if models:
                        return sorted(models, key=lambda m: m.name.lower())
        except Exception as exc:
            logger.warning("Anthropic models discovery fallback: %s", exc)

        return self.provider.model_catalog


class GeminiAdapter(BaseLLMAdapter):
    """Adapter for Google Gemini / Generative Language API."""

    async def test_connection(self, cred_data: dict[str, Any], variant: str = "") -> dict[str, Any]:
        api_key = (cred_data.get("api_key") or "").strip()
        if not api_key:
            return {"ok": False, "message": "Google AI Studio API key is required.", "code": "INVALID_CREDENTIALS"}

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                latency_ms = round((time.perf_counter() - start) * 1000, 1)

                if resp.status_code == 200:
                    return {
                        "ok": True,
                        "message": f"Google Gemini API connection verified successfully ({latency_ms}ms).",
                        "latency_ms": latency_ms,
                        "provider": "google",
                    }
                elif resp.status_code in (400, 401, 403):
                    return {
                        "ok": False,
                        "message": "Invalid Google Gemini API key.",
                        "code": "INVALID_CREDENTIALS",
                        "provider": "google",
                    }
                else:
                    return {
                        "ok": False,
                        "message": f"Google API returned HTTP {resp.status_code}.",
                        "code": "PROVIDER_UNAVAILABLE",
                        "provider": "google",
                    }
        except Exception as e:
            return {"ok": False, "message": f"Connection error: {str(e)[:200]}", "code": "PROVIDER_UNAVAILABLE"}

    async def discover_models(self, cred_data: dict[str, Any], variant: str = "") -> list[LLMModel]:
        api_key = (cred_data.get("api_key") or "").strip()
        if not api_key:
            return self.provider.model_catalog

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    items = resp.json().get("models", [])
                    models = []
                    for it in items:
                        raw_name = it.get("name", "")
                        mid = raw_name.replace("models/", "")
                        if "generateContent" in (it.get("supportedGenerationMethods") or []):
                            models.append(LLMModel(
                                id=mid,
                                name=it.get("displayName") or mid,
                                provider_id="google",
                                description=it.get("description", ""),
                                capabilities=normalize_model_capabilities(mid),
                                context_window=it.get("inputTokenLimit") or normalize_context_window(mid),
                                source="live",
                            ))
                    if models:
                        return sorted(models, key=lambda m: m.name.lower())
        except Exception as exc:
            logger.warning("Gemini model discovery error: %s", exc)

        return self.provider.model_catalog


class OllamaAdapter(BaseLLMAdapter):
    """Adapter for local and self-hosted Ollama instances."""

    async def test_connection(self, cred_data: dict[str, Any], variant: str = "") -> dict[str, Any]:
        base_url = (cred_data.get("base_url") or "http://localhost:11434").rstrip("/")
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
                latency_ms = round((time.perf_counter() - start) * 1000, 1)
                if resp.status_code == 200:
                    return {
                        "ok": True,
                        "message": f"Ollama instance reachable at {base_url} ({latency_ms}ms).",
                        "latency_ms": latency_ms,
                        "provider": "ollama",
                    }
                return {
                    "ok": False,
                    "message": f"Ollama responded with HTTP {resp.status_code}.",
                    "code": "PROVIDER_UNAVAILABLE",
                    "provider": "ollama",
                }
        except Exception as e:
            return {
                "ok": False,
                "message": f"Cannot connect to Ollama at {base_url}: {str(e)[:180]}",
                "code": "PROVIDER_UNAVAILABLE",
                "provider": "ollama",
            }

    async def discover_models(self, cred_data: dict[str, Any], variant: str = "") -> list[LLMModel]:
        base_url = (cred_data.get("base_url") or "http://localhost:11434").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
                if resp.status_code == 200:
                    tags = resp.json().get("models", [])
                    models = []
                    for t in tags:
                        name = t.get("name") or t.get("model")
                        if name:
                            models.append(LLMModel(
                                id=name,
                                name=name,
                                provider_id="ollama",
                                description=f"Local Ollama model {name}",
                                capabilities=normalize_model_capabilities(name),
                                context_window=normalize_context_window(name),
                                source="live",
                            ))
                    if models:
                        return sorted(models, key=lambda m: m.name.lower())
        except Exception as exc:
            logger.warning("Ollama discovery error: %s", exc)

        return [
            LLMModel(id="llama3.3:latest", name="llama3.3:latest", provider_id="ollama", context_window=128000, source="catalog"),
            LLMModel(id="mistral:latest", name="mistral:latest", provider_id="ollama", context_window=32768, source="catalog"),
            LLMModel(id="deepseek-r1:latest", name="deepseek-r1:latest", provider_id="ollama", capabilities={"chat": True, "reasoning": True}, context_window=65536, source="catalog"),
        ]


class CustomProviderAdapter(BaseLLMAdapter):
    """Adapter for 'Other Custom provider' with arbitrary OpenAI-compatible endpoints."""

    async def test_connection(self, cred_data: dict[str, Any], variant: str = "") -> dict[str, Any]:
        base_url = (cred_data.get("base_url") or "").rstrip("/")
        if not base_url:
            return {"ok": False, "message": "Base URL is required for custom provider.", "code": "INVALID_CONFIGURATION"}

        api_key = (cred_data.get("api_key") or "").strip()
        models_endpoint = cred_data.get("models_endpoint") or "/models"
        url = f"{base_url}{models_endpoint}"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Merge custom headers if provided
        custom_headers = cred_data.get("custom_headers") or {}
        if isinstance(custom_headers, dict):
            headers.update({str(k): str(v) for k, v in custom_headers.items()})

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
                latency_ms = round((time.perf_counter() - start) * 1000, 1)
                if resp.status_code == 200:
                    return {
                        "ok": True,
                        "message": f"Custom provider endpoint reachable ({latency_ms}ms).",
                        "latency_ms": latency_ms,
                        "provider": "custom",
                    }
                elif resp.status_code in (401, 403):
                    return {"ok": False, "message": "Authentication failed on custom endpoint.", "code": "INVALID_CREDENTIALS"}
                else:
                    return {"ok": False, "message": f"Custom endpoint returned HTTP {resp.status_code}.", "code": "PROVIDER_UNAVAILABLE"}
        except Exception as e:
            return {"ok": False, "message": f"Custom endpoint error: {str(e)[:200]}", "code": "PROVIDER_UNAVAILABLE"}

    async def discover_models(self, cred_data: dict[str, Any], variant: str = "") -> list[LLMModel]:
        base_url = (cred_data.get("base_url") or "").rstrip("/")
        if not base_url:
            def_m = cred_data.get("default_model") or "custom-model"
            return [LLMModel(id=def_m, name=def_m, provider_id="custom", source="manual")]

        api_key = (cred_data.get("api_key") or "").strip()
        models_endpoint = cred_data.get("models_endpoint") or "/models"
        url = f"{base_url}{models_endpoint}"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    payload = resp.json()
                    raw = payload.get("data") or payload.get("models") or payload
                    if isinstance(raw, list):
                        models = []
                        for it in raw:
                            mid = it.get("id") if isinstance(it, dict) else str(it)
                            if mid:
                                models.append(LLMModel(
                                    id=mid,
                                    name=mid,
                                    provider_id="custom",
                                    capabilities=normalize_model_capabilities(mid),
                                    context_window=normalize_context_window(mid),
                                    source="live",
                                ))
                        if models:
                            return sorted(models, key=lambda m: m.name.lower())
        except Exception as exc:
            logger.warning("Custom provider discovery error: %s", exc)

        def_m = cred_data.get("default_model") or "custom-model"
        return [LLMModel(id=def_m, name=def_m, provider_id="custom", source="manual")]


def get_adapter_for_provider(provider: LLMProviderDefinition) -> BaseLLMAdapter:
    """Factory resolving appropriate adapter instance for an LLM provider."""
    atype = provider.adapter_type
    if atype == "anthropic":
        return AnthropicAdapter(provider)
    if atype == "gemini":
        return GeminiAdapter(provider)
    if atype == "ollama":
        return OllamaAdapter(provider)
    if atype == "custom":
        return CustomProviderAdapter(provider)
    return OpenAICompatibleAdapter(provider)
