"""Google Gemini connector definition (Phase 39)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

GEMINI_CONNECTOR_KEY = "gemini"
GEMINI_CONNECTOR_VERSION = "1.0.0"
GEMINI_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=GEMINI_CONNECTOR_KEY,
        connector_version=GEMINI_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=GEMINI_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="gemini",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["gemini"],
    )


def build_gemini_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=GEMINI_CONNECTOR_KEY,
        display_name="Google Gemini",
        description="Build multimodal workflows, reasoning, embeddings, and text generations with Google Gemini models.",
        category="ai",
        connector_version=GEMINI_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "generate_content": _operation(
                "generate_content", "Generate Content", "Generate multimodal completions, text, and reasoning using Gemini.",
                {
                    "prompt": {"type": "string", "title": "Prompt / Instructions"},
                    "model": {"type": "string", "title": "Model Name", "default": "gemini-1.5-flash"},
                    "system_instruction": {"type": "string", "title": "System Instruction"},
                    "temperature": {"type": "number", "title": "Temperature", "default": 0.7},
                    "max_output_tokens": {"type": "integer", "title": "Max Tokens", "default": 2048},
                },
                ["prompt"],
            ),
            "embed_content": _operation(
                "embed_content", "Embed Content", "Generate vector embeddings using text-embedding-004.",
                {
                    "text": {"type": "string", "title": "Text to embed"},
                    "model": {"type": "string", "title": "Model Name", "default": "text-embedding-004"},
                },
                ["text"],
            ),
            "count_tokens": _operation(
                "count_tokens", "Count Tokens", "Count input tokens for Gemini models.",
                {
                    "prompt": {"type": "string", "title": "Prompt to count"},
                    "model": {"type": "string", "title": "Model Name", "default": "gemini-1.5-flash"},
                },
                ["prompt"],
            ),
        },
        triggers={},
        credential_types={
            "gemini": CredentialTypeV1(
                type_key="gemini",
                display_name="Google Gemini API Key",
                description="Google AI Studio / Gemini API key from aistudio.google.com.",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "title": "API Key (AIzaSy...)"},
                    },
                    "required": ["api_key"],
                },
                encryption_required=True,
            )
        },
    )
