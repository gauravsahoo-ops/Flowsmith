"""Anthropic Claude connector definition (Phase 39)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

ANTHROPIC_CONNECTOR_KEY = "anthropic"
ANTHROPIC_CONNECTOR_VERSION = "1.0.0"
ANTHROPIC_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=ANTHROPIC_CONNECTOR_KEY,
        connector_version=ANTHROPIC_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=ANTHROPIC_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="anthropic",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["anthropic"],
    )


def build_anthropic_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=ANTHROPIC_CONNECTOR_KEY,
        display_name="Anthropic Claude",
        description="Generate text, analyze code, and call tools using Anthropic Claude models (Claude 3.5 Sonnet, Haiku, Opus).",
        category="ai",
        connector_version=ANTHROPIC_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "generate_message": _operation(
                "generate_message", "Generate Message", "Send conversational messages and get Claude text completions.",
                {
                    "prompt": {"type": "string", "title": "User Message / Prompt"},
                    "model": {"type": "string", "title": "Model Name", "default": "claude-3-5-sonnet-20241022"},
                    "system": {"type": "string", "title": "System Prompt"},
                    "max_tokens": {"type": "integer", "title": "Max Tokens", "default": 1024},
                    "temperature": {"type": "number", "title": "Temperature", "default": 0.7},
                },
                ["prompt"],
                retryable=True, idempotency="idempotent",
            ),
            "count_tokens": _operation(
                "count_tokens", "Count Tokens", "Calculate the token count of a prompt or message list.",
                {
                    "prompt": {"type": "string", "title": "Prompt to count"},
                    "model": {"type": "string", "title": "Model Name", "default": "claude-3-5-sonnet-20241022"},
                },
                ["prompt"],
            ),
        },
        triggers={},
        credential_types={
            "anthropic": CredentialTypeV1(
                type_key="anthropic",
                display_name="Anthropic API Key",
                description="Anthropic Claude API key from console.anthropic.com.",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "title": "API Key (sk-ant-...)"},
                    },
                    "required": ["api_key"],
                },
                encryption_required=True,
            )
        },
    )
