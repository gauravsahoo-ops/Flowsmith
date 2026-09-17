"""OpenAI connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

OPENAI_CONNECTOR_KEY = "openai"
OPENAI_CONNECTOR_VERSION = "1.0.0"
OPENAI_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=OPENAI_CONNECTOR_KEY,
        connector_version=OPENAI_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=OPENAI_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="openai",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["openai"],
    )


def build_openai_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=OPENAI_CONNECTOR_KEY,
        display_name="OpenAI",
        description="OpenAI models, embeddings, and chat completions (or any OpenAI-compatible endpoint).",
        category="ai",
        connector_version=OPENAI_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_models": _operation(
                "list_models", "List Models", "List available models.",
                {}, [],
            ),
            "create_embedding": _operation(
                "create_embedding", "Create Embedding", "Embed text into vectors.",
                {
                    "model": {"type": "string", "title": "Embedding model"},
                    "text": {"type": "string", "title": "Input text"},
                },
                ["model", "text"],
            ),
            "chat_completion": _operation(
                "chat_completion", "Chat Completion", "Run a chat completion.",
                {
                    "model": {"type": "string", "title": "Model"},
                    "messages": {"type": "string", "title": "Messages JSON array"},
                    "temperature": {"type": "number", "title": "Temperature"},
                },
                ["model", "messages"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "openai": CredentialTypeV1(
                type_key="openai",
                display_name="OpenAI",
                description="OpenAI API key (or compatible endpoint + key).",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "title": "API key"},
                        "base_url": {"type": "string", "title": "Base URL (default OpenAI)"},
                        "organization": {"type": "string", "title": "Organization (optional)"},
                    },
                    "required": ["api_key"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_models", "create_embedding", "chat_completion"], "auth": "Bearer API key"},
        icon="🧠",
    )
