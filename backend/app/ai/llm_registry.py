"""Centralized LLM Provider Registry for Flowsmith Enterprise AI Platform.

Defines the authoritative catalog of LLM providers, variants, authentication
schemas, model discovery protocols, normalization models, and static catalogs.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("ai.llm_registry")


class LLMModel(BaseModel):
    """Normalized common Flowsmith model structure."""
    id: str = Field(description="Unique model identifier used in API calls.")
    name: str = Field(description="Human-readable model name.")
    provider_id: str = Field(description="Associated provider ID.")
    description: str = Field(default="", description="Model description.")
    capabilities: dict[str, bool] = Field(
        default_factory=lambda: {
            "chat": True,
            "reasoning": False,
            "vision": False,
            "tools": True,
            "streaming": True,
            "embeddings": False,
            "audio": False,
            "imageGeneration": False,
        },
        description="Supported model capabilities.",
    )
    context_window: Optional[int] = Field(default=None, description="Context window size in tokens.")
    max_output_tokens: Optional[int] = Field(default=None, description="Maximum output tokens.")
    input_modalities: list[str] = Field(default_factory=lambda: ["text"], description="Supported input modalities.")
    output_modalities: list[str] = Field(default_factory=lambda: ["text"], description="Supported output modalities.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Provider-specific raw metadata.")
    source: str = Field(default="live", description="Source: 'live' (discovered), 'catalog' (static), 'manual' (user custom).")


class CredentialField(BaseModel):
    """Specification of an input field in the provider credential form."""
    key: str
    label: str
    type: str = "text"  # "text", "password", "select", "url"
    required: bool = True
    placeholder: str = ""
    description: str = ""
    default: Any = ""
    options: list[dict[str, str]] = Field(default_factory=list)
    secret: bool = False


class ProviderVariant(BaseModel):
    """Regional or plan-based variant of an LLM provider."""
    id: str
    name: str
    description: str = ""
    base_url: str = ""
    region: str = ""
    auth_type: str = "api_key"
    models_endpoint: str = "/models"
    chat_endpoint: str = "/chat/completions"
    capabilities: dict[str, bool] = Field(default_factory=dict)


class LLMProviderDefinition(BaseModel):
    """Authoritative metadata and protocol definition for an LLM Provider."""
    provider_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    category: str
    auth_type: str = "api_key"  # api_key, bearer_token, oauth2, basic_auth, aws_sigv4, client_credentials, custom_header, none, local
    credential_fields: list[CredentialField] = Field(default_factory=list)
    base_url: str = ""
    api_endpoints: dict[str, str] = Field(
        default_factory=lambda: {
            "models": "/models",
            "chat": "/chat/completions",
        }
    )
    model_discovery_method: str = "api"  # "api", "static", "manual"
    capabilities: dict[str, bool] = Field(
        default_factory=lambda: {
            "chat": True,
            "reasoning": False,
            "vision": False,
            "tools": True,
            "streaming": True,
            "embeddings": False,
        }
    )
    variants: list[ProviderVariant] = Field(default_factory=list)
    regional_configuration: dict[str, Any] = Field(default_factory=dict)
    model_catalog: list[LLMModel] = Field(default_factory=list)
    adapter_type: str = "openai"  # openai, anthropic, gemini, bedrock, azure, ollama, custom
    status: str = "SUPPORTED"  # SUPPORTED, PARTIAL, MODEL_DISCOVERY_UNSUPPORTED, CUSTOM_ONLY, COMING_SOON


class LLMProviderRegistry:
    """Centralized LLM Provider Registry holding all registered providers."""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProviderDefinition] = {}
        self._initialized: bool = False

    def register(self, provider: LLMProviderDefinition) -> None:
        """Register a provider definition, validating required invariants."""
        if not provider.provider_id:
            raise ValueError("Provider ID cannot be empty.")
        if not provider.display_name:
            raise ValueError(f"Provider '{provider.provider_id}' display name cannot be empty.")
        if provider.provider_id in self._providers:
            raise ValueError(f"Duplicate provider ID registered: '{provider.provider_id}'")
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> Optional[LLMProviderDefinition]:
        """Lookup provider by ID or alias (case-insensitive)."""
        if not provider_id:
            return None
        pid = provider_id.lower().strip()
        if pid in self._providers:
            return self._providers[pid]
        for p in self._providers.values():
            if pid in [a.lower().strip() for a in p.aliases]:
                return p
        return None

    def list_all(self) -> list[LLMProviderDefinition]:
        """Return all registered providers sorted by category and display name."""
        return sorted(
            self._providers.values(),
            key=lambda p: (p.category != "Major Providers", p.category, p.display_name.lower()),
        )

    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[LLMProviderDefinition]:
        """Fuzzy and multi-field search across providers."""
        q = (query or "").lower().strip()
        results = []
        for p in self._providers.values():
            if category and p.category.lower() != category.lower():
                continue
            if status and p.status.lower() != status.lower():
                continue
            if not q:
                results.append(p)
                continue

            # Multi-token match across name, ID, aliases, category, variants
            search_corpus = [
                p.provider_id.lower(),
                p.display_name.lower(),
                p.category.lower(),
                *(a.lower() for a in p.aliases),
                *(v.name.lower() for v in p.variants),
                *(v.id.lower() for v in p.variants),
            ]
            corpus_str = " ".join(search_corpus)
            tokens = q.split()
            if all(t in corpus_str for t in tokens):
                results.append(p)

        return sorted(
            results,
            key=lambda p: (
                p.provider_id != q and p.display_name.lower() != q,
                p.category != "Major Providers",
                p.display_name.lower(),
            ),
        )

    def get_categories(self) -> list[str]:
        """Return distinct categories present in registry."""
        cats = sorted({p.category for p in self._providers.values()})
        # Keep Major Providers at top
        if "Major Providers" in cats:
            cats.remove("Major Providers")
            return ["Major Providers"] + cats
        return cats

    def validate_registry(self) -> dict[str, Any]:
        """Run self-audit checking for duplicates, missing adapters, or invalid fields."""
        errors: list[str] = []
        warnings: list[str] = []
        ids = set()

        for pid, p in self._providers.items():
            if pid in ids:
                errors.append(f"Duplicate ID: {pid}")
            ids.add(pid)
            if not p.display_name:
                errors.append(f"Provider {pid} has empty display name")
            if not p.category:
                errors.append(f"Provider {pid} has empty category")
            if p.adapter_type not in ("openai", "anthropic", "gemini", "bedrock", "azure", "ollama", "custom"):
                errors.append(f"Provider {pid} has unknown adapter type: {p.adapter_type}")
            if p.status not in ("SUPPORTED", "PARTIAL", "MODEL_DISCOVERY_UNSUPPORTED", "CUSTOM_ONLY", "COMING_SOON"):
                errors.append(f"Provider {pid} has unknown status: {p.status}")

        return {
            "valid": len(errors) == 0,
            "total_providers": len(self._providers),
            "errors": errors,
            "warnings": warnings,
        }


# Global registry singleton
_REGISTRY: Optional[LLMProviderRegistry] = None


def get_llm_registry() -> LLMProviderRegistry:
    """Return the populated global LLMProviderRegistry."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = LLMProviderRegistry()
        _init_all_providers(_REGISTRY)
    return _REGISTRY


# Standard credential field sets
def _api_key_fields(placeholder: str = "sk-...", desc: str = "API Key from provider dashboard") -> list[CredentialField]:
    return [
        CredentialField(key="api_key", label="API Key", type="password", required=True, placeholder=placeholder, description=desc, secret=True),
        CredentialField(key="base_url", label="Base URL", type="url", required=False, placeholder="Optional override", description="Leave empty to use official provider endpoint"),
    ]


def _init_all_providers(reg: LLMProviderRegistry) -> None:
    """Populate all providers required by Flowsmith Enterprise AI Platform."""

    # =========================================================================
    # 1. MAJOR PROVIDERS
    # =========================================================================
    reg.register(LLMProviderDefinition(
        provider_id="openai",
        display_name="OpenAI",
        aliases=["chatgpt", "gpt-4", "gpt-4o", "gpt-3.5", "o1", "o3", "openai-api"],
        category="Major Providers",
        auth_type="api_key",
        credential_fields=[
            CredentialField(key="api_key", label="API Key", type="password", required=True, placeholder="sk-proj-...", description="OpenAI API Key", secret=True),
            CredentialField(key="organization", label="Organization ID", type="text", required=False, placeholder="org-...", description="Optional OpenAI Organization ID"),
            CredentialField(key="base_url", label="Base URL", type="url", required=False, placeholder="https://api.openai.com/v1", description="Default: https://api.openai.com/v1"),
        ],
        base_url="https://api.openai.com/v1",
        api_endpoints={"models": "/models", "chat": "/chat/completions"},
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True, "embeddings": True},
        variants=[
            ProviderVariant(id="openai-standard", name="OpenAI Standard", base_url="https://api.openai.com/v1"),
            ProviderVariant(id="openai-chatgpt", name="OpenAI (ChatGPT Plus/Pro)", base_url="https://api.openai.com/v1"),
        ],
        model_catalog=[
            LLMModel(id="gpt-4o", name="GPT-4o", provider_id="openai", description="Flagship omni-model for high-intelligence reasoning, vision, and tool calling.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
            LLMModel(id="gpt-4o-mini", name="GPT-4o Mini", provider_id="openai", description="Affordable, fast, lightweight model for high-throughput orchestration.", capabilities={"chat": True, "reasoning": False, "vision": True, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
            LLMModel(id="o1", name="o1", provider_id="openai", description="Reasoning model engineered for deep code, math, and complex multi-step logic.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True}, context_window=200000, source="catalog"),
            LLMModel(id="o3-mini", name="o3-mini", provider_id="openai", description="High-speed reasoning model balancing deep inference with low latency.", capabilities={"chat": True, "reasoning": True, "vision": False, "tools": True, "streaming": True}, context_window=200000, source="catalog"),
            LLMModel(id="gpt-4-turbo", name="GPT-4 Turbo", provider_id="openai", description="Prior generation high-capability model with vision and JSON mode.", capabilities={"chat": True, "reasoning": False, "vision": True, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="anthropic",
        display_name="Anthropic (API key)",
        aliases=["claude", "anthropic-claude", "claude-3-5", "claude-3-7"],
        category="Major Providers",
        auth_type="api_key",
        credential_fields=[
            CredentialField(key="api_key", label="Anthropic API Key", type="password", required=True, placeholder="sk-ant-api03-...", description="Anthropic Console API Key", secret=True),
            CredentialField(key="base_url", label="Base URL", type="url", required=False, placeholder="https://api.anthropic.com", description="Default: https://api.anthropic.com"),
        ],
        base_url="https://api.anthropic.com",
        api_endpoints={"models": "/v1/models", "chat": "/v1/messages"},
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        model_catalog=[
            LLMModel(id="claude-3-7-sonnet-20250219", name="Claude 3.7 Sonnet", provider_id="anthropic", description="Hybrid reasoning model with configurable thinking budget and exceptional coding capability.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True}, context_window=200000, source="catalog"),
            LLMModel(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet", provider_id="anthropic", description="Industry standard for coding, complex agentic workflows, and nuanced text understanding.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True}, context_window=200000, source="catalog"),
            LLMModel(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", provider_id="anthropic", description="Ultra-fast, cost-efficient model with responsiveness ideal for instant tool calling.", capabilities={"chat": True, "reasoning": False, "vision": False, "tools": True, "streaming": True}, context_window=200000, source="catalog"),
            LLMModel(id="claude-3-opus-20240229", name="Claude 3 Opus", provider_id="anthropic", description="Deep analysis, domain synthesis, and comprehensive reasoning across lengthy context.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True}, context_window=200000, source="catalog"),
        ],
        adapter_type="anthropic",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="google",
        display_name="Google Gemini",
        aliases=["gemini", "google-ai", "google-gemini", "google-deepmind"],
        category="Major Providers",
        auth_type="api_key",
        credential_fields=[
            CredentialField(key="api_key", label="Google AI Studio API Key", type="password", required=True, placeholder="AIzaSy...", description="API key from Google AI Studio", secret=True),
        ],
        base_url="https://generativelanguage.googleapis.com",
        api_endpoints={"models": "/v1beta/models", "chat": "/v1beta/models/{model}:generateContent"},
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True, "audio": True},
        model_catalog=[
            LLMModel(id="gemini-2.0-flash", name="Gemini 2.0 Flash", provider_id="google", description="Next-generation multimodal model with native tool execution and real-time responsiveness.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True, "audio": True}, context_window=1048576, source="catalog"),
            LLMModel(id="gemini-1.5-pro", name="Gemini 1.5 Pro", provider_id="google", description="2-Million token context window for massive codebase analysis and document reasoning.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True, "audio": True}, context_window=2097152, source="catalog"),
            LLMModel(id="gemini-1.5-flash", name="Gemini 1.5 Flash", provider_id="google", description="Lightweight, fast, 1M context model optimized for latency-critical tasks.", capabilities={"chat": True, "reasoning": False, "vision": True, "tools": True, "streaming": True}, context_window=1048576, source="catalog"),
        ],
        adapter_type="gemini",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="deepseek",
        display_name="DeepSeek",
        aliases=["deepseek-ai", "deepseek-r1", "deepseek-v3"],
        category="Major Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields("sk-...", "DeepSeek Platform API Key"),
        base_url="https://api.deepseek.com/v1",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": False, "tools": True, "streaming": True},
        model_catalog=[
            LLMModel(id="deepseek-chat", name="DeepSeek-V3", provider_id="deepseek", description="High-performance general reasoning and coding model with 64K context.", capabilities={"chat": True, "reasoning": False, "vision": False, "tools": True, "streaming": True}, context_window=65536, source="catalog"),
            LLMModel(id="deepseek-reasoner", name="DeepSeek-R1", provider_id="deepseek", description="Open-weights breakthrough reasoning model producing chain-of-thought tokens.", capabilities={"chat": True, "reasoning": True, "vision": False, "tools": False, "streaming": True}, context_window=65536, source="catalog"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="groq",
        display_name="Groq",
        aliases=["groq-lpu", "groqcloud"],
        category="Major Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields("gsk_...", "Groq Cloud API Key"),
        base_url="https://api.groq.com/openai/v1",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        model_catalog=[
            LLMModel(id="llama-3.3-70b-versatile", name="Llama 3.3 70B (Versatile)", provider_id="groq", description="Ultra-fast LPU inference of Meta Llama 3.3 70B with tool calling.", capabilities={"chat": True, "reasoning": True, "vision": False, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
            LLMModel(id="llama-3.1-8b-instant", name="Llama 3.1 8B (Instant)", provider_id="groq", description="Sub-second streaming latency model for realtime text manipulation.", capabilities={"chat": True, "reasoning": False, "vision": False, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
            LLMModel(id="deepseek-r1-distill-llama-70b", name="DeepSeek-R1 Distill Llama 70B", provider_id="groq", description="Fast reasoning model on Groq hardware.", capabilities={"chat": True, "reasoning": True, "vision": False, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="mistral",
        display_name="Mistral",
        aliases=["mistral-ai", "mistralai", "codestral"],
        category="Major Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.mistral.ai/v1",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        model_catalog=[
            LLMModel(id="mistral-large-latest", name="Mistral Large", provider_id="mistral", description="Top-tier flagship reasoning model with multilingual fluency.", capabilities={"chat": True, "reasoning": True, "vision": False, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
            LLMModel(id="pixtral-large-latest", name="Pixtral Large", provider_id="mistral", description="Multimodal visual reasoning model.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
            LLMModel(id="codestral-latest", name="Codestral", provider_id="mistral", description="Specialized model fine-tuned for code generation and FIM completion.", capabilities={"chat": True, "reasoning": True, "vision": False, "tools": True, "streaming": True}, context_window=256000, source="catalog"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="xai",
        display_name="xAI",
        aliases=["grok", "grok-2", "x-ai"],
        category="Major Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields("xai-...", "xAI API Key"),
        base_url="https://api.x.ai/v1",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        model_catalog=[
            LLMModel(id="grok-2-1212", name="Grok 2", provider_id="xai", description="State-of-the-art conversational and reasoning model.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
            LLMModel(id="grok-2-vision-1212", name="Grok 2 Vision", provider_id="xai", description="Multimodal vision understanding model.", capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True}, context_window=128000, source="catalog"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="meta",
        display_name="Meta",
        aliases=["llama", "llama-3", "llama-3.3", "meta-ai"],
        category="Major Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.groq.com/openai/v1",  # Standard reference gateway for Llama
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        adapter_type="openai",
        status="SUPPORTED",
    ))

    # =========================================================================
    # 2. CLOUD PROVIDERS
    # =========================================================================
    reg.register(LLMProviderDefinition(
        provider_id="azure",
        display_name="Azure",
        aliases=["azure-openai", "azure-cognitive-services", "microsoft-azure"],
        category="Cloud Providers",
        auth_type="api_key",
        credential_fields=[
            CredentialField(key="api_key", label="Azure API Key", type="password", required=True, secret=True),
            CredentialField(key="endpoint", label="Endpoint URL", type="url", required=True, placeholder="https://<resource-name>.openai.azure.com"),
            CredentialField(key="deployment", label="Deployment Name", type="text", required=True, placeholder="gpt-4o-deployment"),
            CredentialField(key="api_version", label="API Version", type="text", required=False, default="2024-08-01-preview"),
        ],
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        adapter_type="azure",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="azure_cognitive_services",
        display_name="Azure Cognitive Services",
        aliases=["azure-cognitive", "azure-ai-services"],
        category="Cloud Providers",
        auth_type="api_key",
        credential_fields=[
            CredentialField(key="api_key", label="Key", type="password", required=True, secret=True),
            CredentialField(key="endpoint", label="Endpoint URL", type="url", required=True),
            CredentialField(key="region", label="Region", type="text", required=False, placeholder="eastus"),
        ],
        model_discovery_method="api",
        adapter_type="azure",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="bedrock",
        display_name="Amazon Bedrock",
        aliases=["aws-bedrock", "amazon-bedrock", "aws-ai"],
        category="Cloud Providers",
        auth_type="aws_sigv4",
        credential_fields=[
            CredentialField(key="access_key_id", label="AWS Access Key ID", type="text", required=True),
            CredentialField(key="secret_access_key", label="AWS Secret Access Key", type="password", required=True, secret=True),
            CredentialField(key="region", label="AWS Region", type="text", required=True, default="us-east-1"),
            CredentialField(key="session_token", label="Session Token", type="password", required=False, secret=True),
        ],
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        model_catalog=[
            LLMModel(id="anthropic.claude-3-5-sonnet-20241022-v2:0", name="Claude 3.5 Sonnet (Bedrock)", provider_id="bedrock", context_window=200000, source="catalog"),
            LLMModel(id="amazon.titan-text-express-v1", name="Amazon Titan Text Express", provider_id="bedrock", context_window=8192, source="catalog"),
            LLMModel(id="meta.llama3-3-70b-instruct-v1:0", name="Meta Llama 3.3 70B (Bedrock)", provider_id="bedrock", context_window=128000, source="catalog"),
        ],
        adapter_type="bedrock",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="vertex",
        display_name="Vertex",
        aliases=["google-vertex", "vertex-ai", "gcp-vertex"],
        category="Cloud Providers",
        auth_type="client_credentials",
        credential_fields=[
            CredentialField(key="service_account_json", label="Service Account JSON", type="password", required=True, secret=True),
            CredentialField(key="project_id", label="GCP Project ID", type="text", required=True),
            CredentialField(key="location", label="Location", type="text", required=False, default="us-central1"),
        ],
        model_discovery_method="api",
        adapter_type="gemini",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="vertex_anthropic",
        display_name="Vertex (Anthropic)",
        aliases=["vertex-claude", "gcp-claude"],
        category="Cloud Providers",
        auth_type="client_credentials",
        credential_fields=[
            CredentialField(key="service_account_json", label="Service Account JSON", type="password", required=True, secret=True),
            CredentialField(key="project_id", label="GCP Project ID", type="text", required=True),
            CredentialField(key="location", label="Location", type="text", required=False, default="us-east5"),
        ],
        model_discovery_method="api",
        adapter_type="anthropic",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="databricks",
        display_name="Databricks",
        aliases=["databricks-foundation-models", "dbrx"],
        category="Cloud Providers",
        auth_type="bearer_token",
        credential_fields=[
            CredentialField(key="api_key", label="Databricks Personal Access Token", type="password", required=True, secret=True),
            CredentialField(key="base_url", label="Workspace URL", type="url", required=True, placeholder="https://<workspace>.cloud.databricks.com/serving-endpoints"),
        ],
        model_discovery_method="api",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="snowflake_cortex",
        display_name="Snowflake Cortex",
        aliases=["snowflake-ai", "cortex-ai"],
        category="Cloud Providers",
        auth_type="bearer_token",
        credential_fields=[
            CredentialField(key="api_key", label="Snowflake JWT / Token", type="password", required=True, secret=True),
            CredentialField(key="base_url", label="Account URL", type="url", required=True, placeholder="https://<account>.snowflakecomputing.com"),
        ],
        model_discovery_method="api",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    # =========================================================================
    # 3. LLM GATEWAYS & ROUTERS
    # =========================================================================
    reg.register(LLMProviderDefinition(
        provider_id="openrouter",
        display_name="OpenRouter",
        aliases=["open-router", "openrouter-ai"],
        category="LLM Gateways",
        auth_type="api_key",
        credential_fields=_api_key_fields("sk-or-v1-...", "OpenRouter API Key"),
        base_url="https://openrouter.ai/api/v1",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        model_catalog=[
            LLMModel(id="anthropic/claude-3.5-sonnet", name="Claude 3.5 Sonnet (via OpenRouter)", provider_id="openrouter", context_window=200000, source="catalog"),
            LLMModel(id="openai/gpt-4o", name="GPT-4o (via OpenRouter)", provider_id="openrouter", context_window=128000, source="catalog"),
            LLMModel(id="deepseek/deepseek-r1", name="DeepSeek-R1 (via OpenRouter)", provider_id="openrouter", context_window=65536, capabilities={"chat": True, "reasoning": True}, source="catalog"),
            LLMModel(id="meta-llama/llama-3.3-70b-instruct", name="Llama 3.3 70B (via OpenRouter)", provider_id="openrouter", context_window=128000, source="catalog"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="helicone",
        display_name="Helicone",
        aliases=["helicone-gateway", "helicone-ai"],
        category="LLM Gateways",
        auth_type="api_key",
        credential_fields=[
            CredentialField(key="api_key", label="Helicone API Key", type="password", required=True, secret=True),
            CredentialField(key="upstream_key", label="Upstream Provider Key", type="password", required=False, secret=True),
            CredentialField(key="base_url", label="Gateway URL", type="url", required=False, default="https://oai.helicone.ai/v1"),
        ],
        base_url="https://oai.helicone.ai/v1",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="vercel_ai_gateway",
        display_name="Vercel AI Gateway",
        aliases=["vercel-ai", "vercel-gateway"],
        category="LLM Gateways",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://gateway.ai.cloudflare.com/v1",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    # =========================================================================
    # 4. INFERENCE PROVIDERS
    # =========================================================================
    reg.register(LLMProviderDefinition(
        provider_id="cerebras",
        display_name="Cerebras",
        aliases=["cerebras-wafer", "cerebras-ai"],
        category="Inference Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields("csk-...", "Cerebras API Key"),
        base_url="https://api.cerebras.ai/v1",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": False, "tools": True, "streaming": True},
        model_catalog=[
            LLMModel(id="llama3.3-70b", name="Llama 3.3 70B (Cerebras Ultra-Fast)", provider_id="cerebras", context_window=128000, source="catalog"),
            LLMModel(id="llama3.1-8b", name="Llama 3.1 8B (Cerebras)", provider_id="cerebras", context_window=8192, source="catalog"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="together_ai",
        display_name="Together AI",
        aliases=["together", "together-compute"],
        category="Inference Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.together.xyz/v1",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="fireworks_ai",
        display_name="Fireworks AI",
        aliases=["fireworks", "fireworks-api"],
        category="Inference Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields("fw_..."),
        base_url="https://api.fireworks.ai/inference/v1",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="deep_infra",
        display_name="Deep Infra",
        aliases=["deepinfra", "deep-infra-ai"],
        category="Inference Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.deepinfra.com/v1/openai",
        model_discovery_method="api",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="baseten",
        display_name="Baseten",
        aliases=["baseten-ai", "truss"],
        category="Inference Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://bridge.baseten.co/v1",
        model_discovery_method="api",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="novita_ai",
        display_name="NovitaAI",
        aliases=["novita", "novita-ai"],
        category="Inference Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.novita.ai/v3/openai",
        model_discovery_method="api",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="nvidia",
        display_name="Nvidia",
        aliases=["nvidia-nim", "nvidia-ai", "nim"],
        category="Inference Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields("nvapi-..."),
        base_url="https://integrate.api.nvidia.com/v1",
        model_discovery_method="api",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="perplexity",
        display_name="Perplexity",
        aliases=["sonar", "perplexity-ai", "perplexity-agent"],
        category="Inference Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields("pplx-..."),
        base_url="https://api.perplexity.ai",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": False, "tools": False, "streaming": True},
        model_catalog=[
            LLMModel(id="sonar-pro", name="Sonar Pro", provider_id="perplexity", description="Online search-grounded reasoning model.", context_window=128000, source="catalog"),
            LLMModel(id="sonar-reasoning-pro", name="Sonar Reasoning Pro", provider_id="perplexity", description="Deep web research with chain-of-thought inference.", context_window=128000, capabilities={"chat": True, "reasoning": True}, source="catalog"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    # =========================================================================
    # 5. REGIONAL PROVIDERS (China, Asia, Europe) & VARIANTS
    # =========================================================================
    reg.register(LLMProviderDefinition(
        provider_id="alibaba",
        display_name="Alibaba",
        aliases=["qwen", "dashscope", "aliyun", "tongyi", "alibaba-cloud"],
        category="Regional Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        variants=[
            ProviderVariant(id="alibaba-global", name="Alibaba (Global)", base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            ProviderVariant(id="alibaba-china", name="Alibaba (China)", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ProviderVariant(id="alibaba-coding-plan", name="Alibaba Coding Plan", base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            ProviderVariant(id="alibaba-coding-plan-china", name="Alibaba Coding Plan (China)", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ProviderVariant(id="alibaba-token-plan", name="Alibaba Token Plan", base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            ProviderVariant(id="alibaba-token-plan-china", name="Alibaba Token Plan (China)", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ],
        model_catalog=[
            LLMModel(id="qwen-max", name="Qwen Max", provider_id="alibaba", context_window=32768, source="catalog"),
            LLMModel(id="qwen-plus", name="Qwen Plus", provider_id="alibaba", context_window=131072, source="catalog"),
            LLMModel(id="qwen-turbo", name="Qwen Turbo", provider_id="alibaba", context_window=1000000, source="catalog"),
            LLMModel(id="qwen2.5-coder-32b-instruct", name="Qwen 2.5 Coder 32B", provider_id="alibaba", context_window=131072, source="catalog"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="minimax",
        display_name="MiniMax",
        aliases=["minimax-ai", "hailuo", "minimax-china", "china"],
        category="Regional Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.minimax.chat/v1",
        model_discovery_method="api",
        variants=[
            ProviderVariant(id="minimax-cn", name="MiniMax (minimax.cn)", base_url="https://api.minimax.chat/v1"),
            ProviderVariant(id="minimax-io", name="MiniMax (minimax.io)", base_url="https://api.minimaxi.chat/v1"),
            ProviderVariant(id="minimax-token-cn", name="MiniMax Token Plan (minimax.cn)", base_url="https://api.minimax.chat/v1"),
            ProviderVariant(id="minimax-token-io", name="MiniMax Token Plan (minimax.io)", base_url="https://api.minimaxi.chat/v1"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="xiaomi",
        display_name="Xiaomi",
        aliases=["miai", "xiaomi-ai"],
        category="Regional Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.ai.xiaomi.com/v1",
        model_discovery_method="api",
        variants=[
            ProviderVariant(id="xiaomi-china", name="Xiaomi Token Plan (China)", base_url="https://api.ai.xiaomi.com/v1"),
            ProviderVariant(id="xiaomi-europe", name="Xiaomi Token Plan (Europe)", base_url="https://eu.api.ai.xiaomi.com/v1"),
            ProviderVariant(id="xiaomi-singapore", name="Xiaomi Token Plan (Singapore)", base_url="https://sg.api.ai.xiaomi.com/v1"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="stepfun",
        display_name="StepFun",
        aliases=["stepfun-ai", "step-ai"],
        category="Regional Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.stepfun.com/v1",
        model_discovery_method="api",
        variants=[
            ProviderVariant(id="stepfun-china", name="StepFun (China)", base_url="https://api.stepfun.com/v1"),
            ProviderVariant(id="stepfun-global", name="StepFun (Global)", base_url="https://api-global.stepfun.com/v1"),
            ProviderVariant(id="stepfun-step-china", name="StepFun Step Plan (China)", base_url="https://api.stepfun.com/v1"),
            ProviderVariant(id="stepfun-step-global", name="StepFun Step Plan (Global)", base_url="https://api-global.stepfun.com/v1"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="siliconflow",
        display_name="SiliconFlow",
        aliases=["silicon-flow", "siliconflow-ai"],
        category="Regional Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.siliconflow.cn/v1",
        model_discovery_method="api",
        variants=[
            ProviderVariant(id="siliconflow-global", name="SiliconFlow", base_url="https://api.siliconflow.com/v1"),
            ProviderVariant(id="siliconflow-china", name="SiliconFlow (China)", base_url="https://api.siliconflow.cn/v1"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="zhipu_ai",
        display_name="Zhipu AI",
        aliases=["chatglm", "glm-4", "zhipu", "bigmodel"],
        category="Regional Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model_discovery_method="api",
        variants=[
            ProviderVariant(id="zhipu-std", name="Zhipu AI", base_url="https://open.bigmodel.cn/api/paas/v4"),
            ProviderVariant(id="zhipu-coding", name="Zhipu AI Coding Plan", base_url="https://open.bigmodel.cn/api/paas/v4"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="tencent",
        display_name="Tencent",
        aliases=["hunyuan", "tencent-cloud", "tencent-hunyuan"],
        category="Regional Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
        model_discovery_method="api",
        variants=[
            ProviderVariant(id="tencent-coding-china", name="Tencent Coding Plan (China)", base_url="https://api.hunyuan.cloud.tencent.com/v1"),
            ProviderVariant(id="tencent-token-plan", name="Tencent Token Plan", base_url="https://api.hunyuan.cloud.tencent.com/v1"),
            ProviderVariant(id="tencent-tokenhub", name="Tencent TokenHub", base_url="https://tokenhub.tencent.com/v1"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="moonshot_ai",
        display_name="Moonshot AI",
        aliases=["kimi", "moonshot"],
        category="Regional Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.moonshot.cn/v1",
        model_discovery_method="api",
        variants=[
            ProviderVariant(id="moonshot-global", name="Moonshot AI", base_url="https://api.moonshot.ai/v1"),
            ProviderVariant(id="moonshot-china", name="Moonshot AI (China)", base_url="https://api.moonshot.cn/v1"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="volcengine_ark",
        display_name="Volcengine Ark",
        aliases=["bytedance-doubao", "doubao", "volcengine"],
        category="Regional Providers",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model_discovery_method="api",
        variants=[
            ProviderVariant(id="volcengine-ark", name="Volcengine Ark", base_url="https://ark.cn-beijing.volces.com/api/v3"),
            ProviderVariant(id="volcengine-ark-coding", name="Volcengine Ark Coding Plan", base_url="https://ark.cn-beijing.volces.com/api/v3"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    # =========================================================================
    # 6. CODING AI
    # =========================================================================
    reg.register(LLMProviderDefinition(
        provider_id="github_copilot",
        display_name="GitHub Copilot",
        aliases=["copilot", "github-ai"],
        category="Coding AI",
        auth_type="bearer_token",
        credential_fields=[
            CredentialField(key="api_key", label="GitHub Token", type="password", required=True, secret=True),
        ],
        base_url="https://api.githubcopilot.com",
        model_discovery_method="api",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="kimi_for_coding",
        display_name="Kimi For Coding",
        aliases=["kimi-code", "kimi-coding"],
        category="Coding AI",
        auth_type="api_key",
        credential_fields=_api_key_fields(),
        base_url="https://api.kimi.com/v1",
        model_discovery_method="api",
        variants=[
            ProviderVariant(id="kimi-ai", name="Kimi For Coding (kimi.ai)", base_url="https://api.kimi.ai/v1"),
            ProviderVariant(id="kimi-com", name="Kimi For Coding (kimi.com)", base_url="https://api.kimi.com/v1"),
        ],
        adapter_type="openai",
        status="SUPPORTED",
    ))

    # =========================================================================
    # 7. SELF-HOSTED / LOCAL
    # =========================================================================
    reg.register(LLMProviderDefinition(
        provider_id="ollama",
        display_name="Ollama",
        aliases=["ollama-local", "local-ollama"],
        category="Self-hosted / Local",
        auth_type="local",
        credential_fields=[
            CredentialField(key="base_url", label="Ollama Server URL", type="url", required=True, default="http://localhost:11434", placeholder="http://localhost:11434"),
        ],
        base_url="http://localhost:11434",
        api_endpoints={"models": "/api/tags", "chat": "/v1/chat/completions"},
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        adapter_type="ollama",
        status="SUPPORTED",
    ))

    reg.register(LLMProviderDefinition(
        provider_id="lmstudio",
        display_name="LMStudio",
        aliases=["lm-studio", "lmstudio-ai"],
        category="Self-hosted / Local",
        auth_type="local",
        credential_fields=[
            CredentialField(key="base_url", label="LM Studio Server URL", type="url", required=True, default="http://localhost:1234/v1", placeholder="http://localhost:1234/v1"),
        ],
        base_url="http://localhost:1234/v1",
        model_discovery_method="api",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    # =========================================================================
    # 8. AGGREGATORS & HUBS
    # =========================================================================
    reg.register(LLMProviderDefinition(
        provider_id="huggingface",
        display_name="Hugging Face",
        aliases=["hf", "hugging-face", "hf-inference"],
        category="Aggregators",
        auth_type="bearer_token",
        credential_fields=_api_key_fields("hf_...", "Hugging Face User Access Token"),
        base_url="https://api-inference.huggingface.co/v1",
        model_discovery_method="api",
        adapter_type="openai",
        status="SUPPORTED",
    ))

    # =========================================================================
    # 9. CUSTOM PROVIDER
    # =========================================================================
    reg.register(LLMProviderDefinition(
        provider_id="custom",
        display_name="Other Custom provider",
        aliases=["custom-llm", "openai-compatible", "vllm", "tgi", "sglang"],
        category="Custom",
        auth_type="api_key",
        credential_fields=[
            CredentialField(key="provider_name", label="Provider Name", type="text", required=True, placeholder="My Private LLM Gateway"),
            CredentialField(key="base_url", label="Base URL", type="url", required=True, placeholder="https://api.my-gateway.internal/v1"),
            CredentialField(key="api_key", label="API Key", type="password", required=False, secret=True, placeholder="Optional API Key"),
            CredentialField(key="models_endpoint", label="Models Endpoint", type="text", required=False, default="/models"),
            CredentialField(key="chat_endpoint", label="Chat Endpoint", type="text", required=False, default="/chat/completions"),
            CredentialField(key="default_model", label="Default Model", type="text", required=False, placeholder="e.g. meta-llama/Llama-3-70B"),
        ],
        base_url="",
        model_discovery_method="api",
        capabilities={"chat": True, "reasoning": True, "vision": True, "tools": True, "streaming": True},
        adapter_type="custom",
        status="SUPPORTED",
    ))

    # =========================================================================
    # 10. COMPREHENSIVE PROVIDER INVENTORY (Remaining ~130+ Providers from Prompt)
    # =========================================================================
    # Each entry is explicitly classified into its proper category, default base_url,
    # auth mechanism, and status ("PARTIAL" or "COMING_SOON" if not verified with a live sandbox).

    secondary_providers = [
        # (id, display_name, category, default_url, auth_type, status, aliases, variants)
        ("302_ai", "302.AI", "Aggregators", "https://api.302.ai/v1", "api_key", "PARTIAL", ["302ai"], []),
        ("abacus", "Abacus", "Enterprise AI", "https://pa002.api.abacus.ai/v1", "api_key", "PARTIAL", ["abacus-ai"], []),
        ("abliteration_ai", "abliteration.ai", "Inference Providers", "https://api.abliteration.ai/v1", "api_key", "PARTIAL", [], []),
        ("above_dev", "above.dev", "Inference Providers", "https://api.above.dev/v1", "api_key", "PARTIAL", [], []),
        ("agentrouter", "AgentRouter", "LLM Gateways", "https://api.agentrouter.com/v1", "api_key", "PARTIAL", [], []),
        ("agnes_ai", "Agnes AI", "Enterprise AI", "https://api.agnes.ai/v1", "api_key", "PARTIAL", [], []),
        ("ai_and", "ai&", "Inference Providers", "https://api.aiand.com/v1", "api_key", "PARTIAL", [], []),
        ("ai_router", "AI-ROUTER", "LLM Gateways", "https://api.ai-router.com/v1", "api_key", "PARTIAL", ["airouter"], []),
        ("ai21_labs", "AI21 Labs", "Aggregators", "https://api.ai21.com/studio/v1", "api_key", "PARTIAL", ["jamba", "ai21"], []),
        ("aihubmix", "AIHubMix", "Aggregators", "https://api.aihubmix.com/v1", "api_key", "PARTIAL", [], []),
        ("ainetface", "ainetface", "Inference Providers", "https://api.ainetface.com/v1", "api_key", "PARTIAL", [], []),
        ("aixy", "Aixy", "Inference Providers", "https://api.aixy.ai/v1", "api_key", "PARTIAL", [], []),
        ("aki_io", "AKI.IO", "Compute Providers", "https://api.aki.io/v1", "api_key", "PARTIAL", [], []),
        ("ambient", "Ambient", "Compute Providers", "https://api.ambient.ai/v1", "api_key", "PARTIAL", [], []),
        ("amd", "AMD", "Compute Providers", "https://api.amd.com/v1", "api_key", "PARTIAL", ["amd-rocm"], []),
        ("anyapi", "AnyAPI", "Inference Providers", "https://anyapi.io/api/v1", "api_key", "PARTIAL", [], []),
        ("arcee", "Arcee", "Inference Providers", "https://api.arcee.ai/v1", "api_key", "PARTIAL", ["arcee-ai"], []),
        ("atomic_chat", "Atomic Chat", "Enterprise AI", "https://api.atomicchat.com/v1", "api_key", "PARTIAL", [], []),
        ("auriko", "Auriko", "Enterprise AI", "https://api.auriko.ai/v1", "api_key", "PARTIAL", [], []),
        ("bailing", "Bailing", "Regional Providers", "https://api.bailing.ai/v1", "api_key", "PARTIAL", [], []),
        ("bee_by_heosst", "Bee by HEOSST", "Enterprise AI", "https://api.heosst.com/bee/v1", "api_key", "PARTIAL", [], []),
        ("berget_ai", "Berget AI", "Regional Providers", "https://api.berget.ai/v1", "api_key", "PARTIAL", ["berget"], []),
        ("blue_claw", "Blue Claw", "Inference Providers", "https://api.blueclaw.ai/v1", "api_key", "PARTIAL", [], []),
        ("bothub", "Bothub", "Aggregators", "https://bothub.chat/api/v1", "api_key", "PARTIAL", [], []),
        ("charm_hyper", "Charm Hyper", "Inference Providers", "https://api.charmhyper.com/v1", "api_key", "PARTIAL", [], []),
        ("chutes", "Chutes", "Inference Providers", "https://api.chutes.ai/v1", "api_key", "PARTIAL", [], []),
        ("clarifai", "Clarifai", "Aggregators", "https://api.clarifai.com/v2", "api_key", "PARTIAL", [], []),
        ("claudinio", "Claudinio", "Inference Providers", "https://api.claudinio.com/v1", "api_key", "PARTIAL", [], []),
        ("daoxe", "DaoXE", "Regional Providers", "https://api.daoxe.com/v1", "api_key", "PARTIAL", [], []),
        ("devpass", "DevPass (LLM Gateway)", "LLM Gateways", "https://api.devpass.ai/v1", "api_key", "PARTIAL", ["devpass-gateway"], []),
        ("digitalocean", "DigitalOcean", "Cloud Providers", "https://api.digitalocean.com/v2/gen-ai", "api_key", "PARTIAL", ["do-genai"], []),
        ("dinference", "DInference", "Inference Providers", "https://api.dinference.com/v1", "api_key", "PARTIAL", [], []),
        ("ebcloud", "EBCloud", "Compute Providers", "https://api.ebcloud.com/v1", "api_key", "PARTIAL", [], []),
        ("echo", "Echo", "Inference Providers", "https://api.echo.ai/v1", "api_key", "PARTIAL", [], []),
        ("eden_ai", "Eden AI", "Aggregators", "https://api.edenai.run/v2", "api_key", "PARTIAL", ["edenai"], []),
        ("empiriolabs_ai", "EmpirioLabs AI", "Enterprise AI", "https://api.empiriolabs.com/v1", "api_key", "PARTIAL", [], []),
        ("evroc", "evroc", "Cloud Providers", "https://api.evroc.com/v1", "api_key", "PARTIAL", [], []),
        ("fastrouter", "FastRouter", "LLM Gateways", "https://api.fastrouter.io/v1", "api_key", "PARTIAL", [], []),
        ("freemodel", "FreeModel", "Aggregators", "https://api.freemodel.ai/v1", "api_key", "PARTIAL", [], []),
        ("friendli", "Friendli", "Inference Providers", "https://api.friendli.ai/v1", "api_key", "PARTIAL", ["friendli-ai"], []),
        ("frogbot", "FrogBot", "Inference Providers", "https://api.frogbot.ai/v1", "api_key", "PARTIAL", [], []),
        ("gitlab_duo", "GitLab Duo", "Coding AI", "https://gitlab.com/api/v4/ai", "bearer_token", "PARTIAL", ["gitlab-ai"], []),
        ("gmi_cloud", "GMI Cloud", "Compute Providers", "https://api.gmicloud.ai/v1", "api_key", "PARTIAL", [], []),
        ("greenpt", "GreenPT", "Inference Providers", "https://api.greenpt.ai/v1", "api_key", "PARTIAL", [], []),
        ("hetzner", "Hetzner", "Cloud Providers", "https://api.hetzner.cloud/v1", "bearer_token", "PARTIAL", [], []),
        ("hpc_ai", "HPC-AI", "Compute Providers", "https://api.hpc-ai.com/v1", "api_key", "PARTIAL", [], []),
        ("iflow", "iFlow", "Enterprise AI", "https://api.iflow.ai/v1", "api_key", "PARTIAL", [], []),
        ("impossibl", "Impossibl", "Inference Providers", "https://api.impossibl.com/v1", "api_key", "PARTIAL", [], []),
        ("inception", "Inception", "Inference Providers", "https://api.inception.ai/v1", "api_key", "PARTIAL", [], []),
        ("inceptron", "Inceptron", "Inference Providers", "https://api.inceptron.com/v1", "api_key", "PARTIAL", [], []),
        ("inco", "Inco", "Inference Providers", "https://api.inco.org/v1", "api_key", "PARTIAL", [], []),
        ("infer_by_flow7", "Infer by Flow7", "Inference Providers", "https://api.flow7.com/v1", "api_key", "PARTIAL", [], []),
        ("inference", "Inference", "Inference Providers", "https://api.inference.ai/v1", "api_key", "PARTIAL", [], []),
        ("inferx", "InferX", "Inference Providers", "https://api.inferx.ai/v1", "api_key", "PARTIAL", [], []),
        ("infomaniak", "Infomaniak", "Regional Providers", "https://api.infomaniak.com/1/ai", "api_key", "PARTIAL", [], []),
        ("io_net", "IO.NET", "Compute Providers", "https://api.io.net/v1", "api_key", "PARTIAL", ["ionet"], []),
        ("iteracompute", "IteraCompute", "Compute Providers", "https://api.iteracompute.com/v1", "api_key", "PARTIAL", [], []),
        ("jalapeno_cloud", "Jalapeno Cloud", "Compute Providers", "https://api.jalapenocloud.com/v1", "api_key", "PARTIAL", [], []),
        ("jiekou_ai", "Jiekou.AI", "Regional Providers", "https://api.jiekou.ai/v1", "api_key", "PARTIAL", [], []),
        ("kenari", "Kenari", "Inference Providers", "https://api.kenari.ai/v1", "api_key", "PARTIAL", [], []),
        ("kilo_gateway", "Kilo Gateway", "LLM Gateways", "https://api.kilogateway.com/v1", "api_key", "PARTIAL", [], []),
        ("klokintegration", "klokintegration.se", "Regional Providers", "https://api.klokintegration.se/v1", "api_key", "PARTIAL", [], []),
        ("kosmik_compute", "Kosmik Compute", "Compute Providers", "https://api.kosmikcompute.com/v1", "api_key", "PARTIAL", [], []),
        ("kuae_cloud_coding", "KUAE Cloud Coding Plan", "Coding AI", "https://api.kuaecloud.com/v1", "api_key", "PARTIAL", [], []),
        ("lilac", "Lilac", "Inference Providers", "https://api.lilac.ai/v1", "api_key", "PARTIAL", [], []),
        ("llm_gateway", "LLM Gateway", "LLM Gateways", "https://api.llmgateway.ai/v1", "api_key", "PARTIAL", [], []),
        ("llm_tech", "LLM Tech", "Enterprise AI", "https://api.llmtech.com/v1", "api_key", "PARTIAL", [], []),
        ("llmtr", "LLMTR", "LLM Gateways", "https://api.llmtr.com/v1", "api_key", "PARTIAL", [], []),
        ("longcat", "LongCat", "Inference Providers", "https://api.longcat.ai/v1", "api_key", "PARTIAL", [], []),
        ("lucidquery", "LucidQuery", "Enterprise AI", "https://api.lucidquery.com/v1", "api_key", "PARTIAL", [], []),
        ("lynkr", "Lynkr", "Enterprise AI", "https://api.lynkr.ai/v1", "api_key", "PARTIAL", [], []),
        ("meganova", "Meganova", "Inference Providers", "https://api.meganova.ai/v1", "api_key", "PARTIAL", [], []),
        ("melius", "Melius", "Inference Providers", "https://api.melius.ai/v1", "api_key", "PARTIAL", [], []),
        ("merge_gateway", "Merge Gateway", "LLM Gateways", "https://api.mergegateway.com/v1", "api_key", "PARTIAL", [], []),
        ("mixlayer", "Mixlayer", "Inference Providers", "https://api.mixlayer.com/v1", "api_key", "PARTIAL", [], []),
        ("moark", "Moark", "Inference Providers", "https://api.moark.ai/v1", "api_key", "PARTIAL", [], []),
        ("modal", "Modal", "Compute Providers", "https://api.modal.com/v1", "api_key", "PARTIAL", ["modal-labs"], []),
        ("model_oracle_ai", "Model Oracle AI", "Enterprise AI", "https://api.modeloracle.com/v1", "api_key", "PARTIAL", [], []),
        ("modelis", "Modelis", "Enterprise AI", "https://api.modelis.ai/v1", "api_key", "PARTIAL", [], []),
        ("modelscope", "ModelScope", "Aggregators", "https://api-inference.modelscope.cn/v1", "api_key", "PARTIAL", ["modelscope-ai"], []),
        ("morph", "Morph", "Inference Providers", "https://api.morph.ai/v1", "api_key", "PARTIAL", [], []),
        ("nan", "NaN", "Inference Providers", "https://api.nan.ai/v1", "api_key", "PARTIAL", [], []),
        ("nanogpt", "NanoGPT", "Aggregators", "https://nano-gpt.com/api/v1", "api_key", "PARTIAL", [], []),
        ("near_ai_cloud", "NEAR AI Cloud", "Compute Providers", "https://api.near.ai/v1", "api_key", "PARTIAL", ["near-ai"], []),
        ("nebius_token_factory", "Nebius Token Factory", "Compute Providers", "https://api.tokenfactory.nebius.com/v1", "api_key", "PARTIAL", ["nebius"], []),
        ("neon", "Neon", "Enterprise AI", "https://api.neon.ai/v1", "api_key", "PARTIAL", [], []),
        ("neosmith", "NeoSmith", "Enterprise AI", "https://api.neosmith.com/v1", "api_key", "PARTIAL", [], []),
        ("neuralwatt", "Neuralwatt", "Compute Providers", "https://api.neuralwatt.com/v1", "api_key", "PARTIAL", [], []),
        ("nova", "Nova", "Inference Providers", "https://api.nova.ai/v1", "api_key", "PARTIAL", [], []),
        ("oci_generative_ai", "OCI Generative AI", "Cloud Providers", "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/20231130", "api_key", "PARTIAL", ["oracle-genai"], []),
        ("ofox", "Ofox", "Aggregators", "https://api.ofox.ai/v1", "api_key", "PARTIAL", [], []),
        ("ollama_cloud", "Ollama Cloud", "Cloud Providers", "https://api.ollamacloud.com/v1", "api_key", "PARTIAL", [], []),
        ("openreason", "OpenReason", "Inference Providers", "https://api.openreason.ai/v1", "api_key", "PARTIAL", [], []),
        ("opper", "Opper", "Enterprise AI", "https://api.opper.ai/v1", "api_key", "PARTIAL", [], []),
        ("orcarouter", "OrcaRouter", "LLM Gateways", "https://api.orcarouter.com/v1", "api_key", "PARTIAL", [], []),
        ("ovhcloud_ai", "OVHcloud AI Endpoints", "Cloud Providers", "https://endpoints.ai.cloud.ovh.net/v1", "bearer_token", "PARTIAL", ["ovh-ai"], []),
        ("pareto_inference", "Pareto Inference", "Inference Providers", "https://api.pareto.ai/v1", "api_key", "PARTIAL", [], []),
        ("pendra", "Pendra", "Inference Providers", "https://api.pendra.ai/v1", "api_key", "PARTIAL", [], []),
        ("perplexity_agent", "Perplexity Agent", "Enterprise AI", "https://api.perplexity.ai/agent/v1", "api_key", "PARTIAL", [], []),
        ("pioneer", "Pioneer", "Inference Providers", "https://api.pioneer.ai/v1", "api_key", "PARTIAL", [], []),
        ("poe", "Poe", "Aggregators", "https://api.poe.com/v1", "api_key", "PARTIAL", ["quora-poe"], []),
        ("poolside", "Poolside", "Coding AI", "https://api.poolside.ai/v1", "api_key", "PARTIAL", [], []),
        ("privatemode_ai", "Privatemode AI", "Enterprise AI", "https://api.privatemode.ai/v1", "api_key", "PARTIAL", [], []),
        ("qihang", "QiHang", "Regional Providers", "https://api.qihang.ai/v1", "api_key", "PARTIAL", [], []),
        ("qvac", "QVAC", "Inference Providers", "https://api.qvac.ai/v1", "api_key", "PARTIAL", [], []),
        ("regolo_ai", "Regolo AI", "Inference Providers", "https://api.regolo.ai/v1", "api_key", "PARTIAL", [], []),
        ("requesty", "Requesty", "LLM Gateways", "https://api.requesty.ai/v1", "api_key", "PARTIAL", [], []),
        ("routing_run", "routing.run", "LLM Gateways", "https://api.routing.run/v1", "api_key", "PARTIAL", [], []),
        ("runinfra", "RunInfra", "Inference Providers", "https://api.runinfra.com/v1", "api_key", "PARTIAL", [], []),
        ("sakana_ai", "Sakana AI", "Enterprise AI", "https://api.sakana.ai/v1", "api_key", "PARTIAL", [], []),
        ("saladcloud_ai_gateway", "SaladCloud AI Gateway", "Compute Providers", "https://api.salad.com/v1", "api_key", "PARTIAL", ["salad-cloud"], []),
        ("sap_ai_core", "SAP AI Core", "Cloud Providers", "https://api.ai.prod.eu-central-1.aws.ml.hana.ondemand.com/v2", "bearer_token", "PARTIAL", ["sap-ai"], []),
        ("sarvam_ai", "Sarvam AI", "Regional Providers", "https://api.sarvam.ai/v1", "api_key", "PARTIAL", ["sarvam"], []),
        ("scaleway", "Scaleway", "Cloud Providers", "https://api.scaleway.com/ai/v1", "bearer_token", "PARTIAL", ["scaleway-ai"], []),
        ("scnet_token_plan", "SCNet Token Plan", "Regional Providers", "https://api.scnet.com/v1", "api_key", "PARTIAL", [], []),
        ("scx_ai", "SCX.ai", "Regional Providers", "https://api.scx.ai/v1", "api_key", "PARTIAL", [], []),
        ("sensenova", "SenseNova (China)", "Regional Providers", "https://api.sensenova.cn/v1", "api_key", "PARTIAL", ["sensetime"], []),
        ("stackit", "STACKIT", "Cloud Providers", "https://api.stackit.cloud/ai/v1", "bearer_token", "PARTIAL", [], []),
        ("standard_compute", "Standard Compute", "Compute Providers", "https://api.standardcompute.com/v1", "api_key", "PARTIAL", [], []),
        ("subconscious", "Subconscious", "Enterprise AI", "https://api.subconscious.ai/v1", "api_key", "PARTIAL", [], []),
        ("submodel", "submodel", "Inference Providers", "https://api.submodel.com/v1", "api_key", "PARTIAL", [], []),
        ("synthetic", "Synthetic", "Inference Providers", "https://api.synthetic.ai/v1", "api_key", "PARTIAL", [], []),
        ("tempr", "Tempr", "Enterprise AI", "https://api.tempr.ai/v1", "api_key", "PARTIAL", [], []),
        ("tensorx", "TensorX", "Compute Providers", "https://api.tensorx.ai/v1", "api_key", "PARTIAL", [], []),
        ("the_grid_ai", "The Grid AI", "Enterprise AI", "https://api.thegrid.ai/v1", "api_key", "PARTIAL", [], []),
        ("thinking_machines", "Thinking Machines", "Enterprise AI", "https://api.thinkingmachines.ai/v1", "api_key", "PARTIAL", [], []),
        ("tinfoil", "Tinfoil", "Inference Providers", "https://api.tinfoil.sh/v1", "api_key", "PARTIAL", [], []),
        ("tokengo", "TokenGo", "Aggregators", "https://api.tokengo.ai/v1", "api_key", "PARTIAL", [], []),
        ("tokenrouter", "TokenRouter", "LLM Gateways", "https://api.tokenrouter.com/v1", "api_key", "PARTIAL", [], []),
        ("trustedrouter", "TrustedRouter", "LLM Gateways", "https://api.trustedrouter.com/v1", "api_key", "PARTIAL", [], []),
        ("umans_ai", "Umans AI", "Enterprise AI", "https://api.umans.ai/v1", "api_key", "PARTIAL", [], [
            ProviderVariant(id="umans-std", name="Umans AI", base_url="https://api.umans.ai/v1"),
            ProviderVariant(id="umans-coding", name="Umans AI Coding Plan", base_url="https://api.umans.ai/v1"),
        ]),
        ("unorouter", "UnoRouter", "LLM Gateways", "https://api.unorouter.com/v1", "api_key", "PARTIAL", [], []),
        ("upstage", "Upstage", "Enterprise AI", "https://api.upstage.ai/v1/solar", "api_key", "PARTIAL", ["solar-mini", "upstage-ai"], []),
        ("v0", "v0", "Coding AI", "https://api.v0.dev/v1", "api_key", "PARTIAL", ["vercel-v0"], []),
        ("vancine", "Vancine", "Inference Providers", "https://api.vancine.ai/v1", "api_key", "PARTIAL", [], []),
        ("venice_ai", "Venice AI", "Inference Providers", "https://api.venice.ai/api/v1", "api_key", "PARTIAL", ["venice"], []),
        ("vispark", "Vispark", "Inference Providers", "https://api.vispark.ai/v1", "api_key", "PARTIAL", [], []),
        ("viggrid", "Viggrid", "Inference Providers", "https://api.viggrid.com/v1", "api_key", "PARTIAL", [], []),
        ("vultr", "Vultr", "Cloud Providers", "https://api.vultr.com/v2/inference", "api_key", "PARTIAL", ["vultr-ai"], []),
        ("wafer", "Wafer", "Compute Providers", "https://api.wafer.ai/v1", "api_key", "PARTIAL", [], []),
        ("wallaby", "Wallaby", "Inference Providers", "https://api.wallaby.ai/v1", "api_key", "PARTIAL", [], []),
        ("watsonx_ai", "watsonx.ai", "Cloud Providers", "https://us-south.ml.cloud.ibm.com/v1", "bearer_token", "PARTIAL", ["ibm-watsonx", "ibm-ai"], []),
        ("xpserona", "Xpserona", "Inference Providers", "https://api.xpserona.ai/v1", "api_key", "PARTIAL", [], []),
        ("z_ai", "Z.AI", "Regional Providers", "https://api.z.ai/v1", "api_key", "PARTIAL", [], [
            ProviderVariant(id="z-ai-std", name="Z.AI", base_url="https://api.z.ai/v1"),
            ProviderVariant(id="z-ai-coding", name="Z.AI Coding Plan", base_url="https://api.z.ai/v1"),
        ]),
        ("zeldoc", "Zeldoc", "Inference Providers", "https://api.zeldoc.ai/v1", "api_key", "PARTIAL", [], []),
        ("zenifra", "Zenifra", "Inference Providers", "https://api.zenifra.ai/v1", "api_key", "PARTIAL", [], []),
        ("zenmux", "ZenMux", "LLM Gateways", "https://api.zenmux.ai/v1", "api_key", "PARTIAL", [], []),
    ]

    for item in secondary_providers:
        pid, name, cat, url, auth, stat, aliases, variants = item
        reg.register(LLMProviderDefinition(
            provider_id=pid,
            display_name=name,
            aliases=aliases,
            category=cat,
            auth_type=auth,
            credential_fields=_api_key_fields(),
            base_url=url,
            model_discovery_method="api",
            variants=variants,
            adapter_type="openai",
            status=stat,
        ))
