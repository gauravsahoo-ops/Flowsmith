"""Tests for Flowsmith Enterprise Multi-Provider LLM Platform."""

import pytest
import respx
import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.ai.llm_registry import get_llm_registry, LLMModel
from app.ai.llm_adapters import (
    get_adapter_for_provider,
    normalize_model_capabilities,
    normalize_context_window,
    get_model_cache,
)


@pytest.fixture
def client():
    return TestClient(app)


class TestLLMRegistry:
    def test_all_expected_providers_registered(self):
        reg = get_llm_registry()
        audit = reg.validate_registry()
        assert audit["valid"] is True
        assert audit["total_providers"] >= 180

        # Core representative providers
        expected = [
            "openai", "anthropic", "google", "deepseek", "groq", "mistral",
            "xai", "cerebras", "together_ai", "fireworks_ai", "perplexity",
            "azure", "bedrock", "vertex", "vertex_anthropic", "openrouter",
            "ollama", "lmstudio", "huggingface", "alibaba", "minimax",
            "xiaomi", "stepfun", "siliconflow", "zhipu_ai", "tencent",
            "moonshot_ai", "volcengine_ark", "github_copilot", "kimi_for_coding",
            "custom"
        ]
        for pid in expected:
            p = reg.get(pid)
            assert p is not None, f"Expected provider '{pid}' not found in registry"
            assert p.display_name, f"Provider '{pid}' missing display name"
            assert p.category, f"Provider '{pid}' missing category"

    def test_provider_variants(self):
        reg = get_llm_registry()

        # Alibaba variants
        alibaba = reg.get("alibaba")
        assert alibaba is not None
        assert len(alibaba.variants) >= 6
        variant_names = [v.name for v in alibaba.variants]
        assert "Alibaba (China)" in variant_names
        assert "Alibaba Coding Plan" in variant_names
        assert "Alibaba Token Plan" in variant_names

        # MiniMax variants
        minimax = reg.get("minimax")
        assert minimax is not None
        assert len(minimax.variants) >= 4
        m_names = [v.name for v in minimax.variants]
        assert "MiniMax (minimax.cn)" in m_names
        assert "MiniMax (minimax.io)" in m_names

        # Xiaomi variants
        xiaomi = reg.get("xiaomi")
        assert xiaomi is not None
        x_names = [v.name for v in xiaomi.variants]
        assert "Xiaomi Token Plan (China)" in x_names
        assert "Xiaomi Token Plan (Europe)" in x_names
        assert "Xiaomi Token Plan (Singapore)" in x_names

    def test_provider_search(self):
        reg = get_llm_registry()

        # Search by prefix
        open_results = reg.search("open")
        pids = [p.provider_id for p in open_results]
        assert "openai" in pids
        assert "openrouter" in pids

        # Search by regional variant term
        china_results = reg.search("china")
        c_names = [p.display_name for p in china_results]
        assert "Alibaba" in c_names
        assert "MiniMax" in c_names
        assert "Xiaomi" in c_names
        assert "StepFun" in c_names

        # Search by alias
        claude_results = reg.search("claude")
        assert any(p.provider_id == "anthropic" for p in claude_results)

        qwen_results = reg.search("qwen")
        assert any(p.provider_id == "alibaba" for p in qwen_results)

    def test_categories(self):
        reg = get_llm_registry()
        cats = reg.get_categories()
        assert "Major Providers" in cats
        assert "Cloud Providers" in cats
        assert "LLM Gateways" in cats
        assert "Inference Providers" in cats
        assert "Regional Providers" in cats
        assert "Self-hosted / Local" in cats
        assert "Custom" in cats


class TestModelNormalization:
    def test_capabilities_inference(self):
        # Reasoning models
        o1_caps = normalize_model_capabilities("o1-preview")
        assert o1_caps["reasoning"] is True
        assert o1_caps["chat"] is True

        r1_caps = normalize_model_capabilities("deepseek-r1")
        assert r1_caps["reasoning"] is True

        c37_caps = normalize_model_capabilities("claude-3-7-sonnet-20250219")
        assert c37_caps["reasoning"] is True
        assert c37_caps["vision"] is True

        # Vision models
        gpt4o_caps = normalize_model_capabilities("gpt-4o")
        assert gpt4o_caps["vision"] is True

        # Embedding models
        embed_caps = normalize_model_capabilities("text-embedding-3-small")
        assert embed_caps["embeddings"] is True
        assert embed_caps["chat"] is False

    def test_context_window_normalization(self):
        assert normalize_context_window("gemini-1.5-pro") == 2097152
        assert normalize_context_window("claude-3-5-sonnet") == 200000
        assert normalize_context_window("gpt-4o") == 128000
        assert normalize_context_window("deepseek-chat") == 64000
        assert normalize_context_window("custom-model", {"context_window": 50000}) == 50000


@pytest.mark.asyncio
class TestAdaptersAndDiscovery:
    async def test_openai_compatible_test_connection_success(self):
        reg = get_llm_registry()
        openai_p = reg.get("openai")
        adapter = get_adapter_for_provider(openai_p)

        with respx.mock(base_url="https://api.openai.com/v1") as respx_mock:
            respx_mock.get("/models").respond(200, json={"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})
            res = await adapter.test_connection({"api_key": "sk-test", "base_url": "https://api.openai.com/v1"})
            assert res["ok"] is True
            assert "Successfully connected" in res["message"]
            assert res["latency_ms"] >= 0

    async def test_openai_compatible_test_connection_auth_error(self):
        reg = get_llm_registry()
        openai_p = reg.get("openai")
        adapter = get_adapter_for_provider(openai_p)

        with respx.mock(base_url="https://api.openai.com/v1") as respx_mock:
            respx_mock.get("/models").respond(401, json={"error": {"message": "Invalid API key"}})
            res = await adapter.test_connection({"api_key": "sk-invalid", "base_url": "https://api.openai.com/v1"})
            assert res["ok"] is False
            assert res["code"] == "INVALID_CREDENTIALS"

    async def test_openai_compatible_discover_models(self):
        reg = get_llm_registry()
        groq_p = reg.get("groq")
        adapter = get_adapter_for_provider(groq_p)

        with respx.mock(base_url="https://api.groq.com/openai/v1") as respx_mock:
            respx_mock.get("/models").respond(200, json={
                "data": [
                    {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile"},
                    {"id": "deepseek-r1-distill-llama-70b", "name": "DeepSeek R1 Distill 70B"},
                ]
            })
            models = await adapter.discover_models({"api_key": "gsk_test"})
            assert len(models) == 2
            ids = [m.id for m in models]
            assert "llama-3.3-70b-versatile" in ids
            assert "deepseek-r1-distill-llama-70b" in ids
            r1 = next(m for m in models if m.id == "deepseek-r1-distill-llama-70b")
            assert r1.capabilities["reasoning"] is True

    async def test_anthropic_adapter_discovery_and_test(self):
        reg = get_llm_registry()
        ant_p = reg.get("anthropic")
        adapter = get_adapter_for_provider(ant_p)

        with respx.mock(base_url="https://api.anthropic.com") as respx_mock:
            respx_mock.get("/v1/models").respond(200, json={
                "data": [
                    {"id": "claude-3-7-sonnet-20250219", "display_name": "Claude 3.7 Sonnet"},
                    {"id": "claude-3-5-haiku-20241022", "display_name": "Claude 3.5 Haiku"},
                ]
            })
            test_res = await adapter.test_connection({"api_key": "sk-ant-test"})
            assert test_res["ok"] is True

            models = await adapter.discover_models({"api_key": "sk-ant-test"})
            assert len(models) == 2
            assert models[0].provider_id == "anthropic"

    async def test_model_cache(self):
        cache = get_model_cache()
        await cache.clear_all()

        m1 = [LLMModel(id="test-1", name="Test 1", provider_id="openai")]
        await cache.set("openai", "", "test_user_cred", m1)

        hit = await cache.get("openai", "", "test_user_cred")
        assert hit is not None
        assert len(hit) == 1
        assert hit[0].id == "test-1"

        miss = await cache.get("openai", "", "other_cred")
        assert miss is None
