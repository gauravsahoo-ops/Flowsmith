"""Trello connector definition (Batch B, original).

Ops: list_cards, get_card, create_card, add_comment.
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

TRELLO_CONNECTOR_KEY = "trello"
TRELLO_CONNECTOR_VERSION = "1.0.0"
TRELLO_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: dict,
    required: list[str],
    *,
    retryable: bool = True,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=TRELLO_CONNECTOR_KEY,
        connector_version=TRELLO_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=TRELLO_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="trello",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["trello"],
    )


def _trello_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "list_cards": _operation(
            "list_cards", "List Board Cards", "List cards on a Trello board.",
            {"board_id": {"type": "string", "title": "Board id"}}, ["board_id"],
        ),
        "get_card": _operation(
            "get_card", "Get Card", "Fetch one Trello card by id.",
            {"card_id": {"type": "string", "title": "Card id"}}, ["card_id"],
        ),
        "create_card": _operation(
            "create_card", "Create Card", "Create a card on a list.",
            {
                "list_id": {"type": "string", "title": "List id"},
                "name": {"type": "string", "title": "Card name"},
                "desc": {"type": "string", "title": "Description"},
            },
            ["list_id", "name"], retryable=False, idempotency="non_idempotent",
        ),
        "add_comment": _operation(
            "add_comment", "Add Comment", "Add a comment to a card.",
            {
                "card_id": {"type": "string", "title": "Card id"},
                "text": {"type": "string", "title": "Comment text"},
            },
            ["card_id", "text"], retryable=False, idempotency="non_idempotent",
        ),
    }


def build_trello_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=TRELLO_CONNECTOR_KEY,
        display_name="Trello",
        description="Work with Trello boards, cards, and comments.",
        category="productivity",
        connector_version=TRELLO_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_trello_operations(),
        triggers={},
        credential_types={
            "trello": CredentialTypeV1(
                type_key="trello",
                display_name="Trello",
                description="Trello API key + token from trello.com/app-key (token via the authorize link).",
                secret_fields=["api_key", "api_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "title": "API key"},
                        "api_token": {"type": "string", "title": "API token"},
                    },
                    "required": ["api_key", "api_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_cards", "get_card", "create_card", "add_comment"], "auth": "api key + token"},
        icon="🗂️",
    )
