"""Connector discovery endpoints (spec 37+).

Provides backend APIs for connector discovery as defined in the
Connector Framework v2 specification.

Required conceptual endpoints:

GET /api/connectors
GET /api/connectors/{connector_key}
GET /api/connectors/{connector_key}/operations
GET /api/connectors/{connector_key}/triggers
GET /api/connectors/{connector_key}/credential-types

Protect endpoints appropriately - read access for authenticated users,
writable operations require proper authorization.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user
from app.api.common import ok
from app.models import User
from app.connectors import (
    ConnectorSDK,
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
    ConnectorCategory,
    ConnectorLifecycle,
    make_connector_error,
    ConnectorErrorCode,
)
from app.connectors.registry import ConnectorRegistry
from app.connectors import get_registry as _get_registry

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


def get_registry() -> ConnectorRegistry:
    """FastAPI dependency: get the global connector registry."""
    return _get_registry()


@router.get("")
def list_connectors(
    user: User = Depends(get_current_user),
) -> dict:
    """List all registered connectors (public discovery)."""
    registry = get_registry()
    definitions = registry.list_definitions()
    return ok(
        [
            {
                "connector_key": d.connector_key,
                "display_name": d.display_name,
                "description": d.description,
                "category": d.category,
                "connector_version": d.connector_version,
                "lifecycle_status": d.lifecycle_status,
                "icon": d.icon,
                "operations": list(d.operations.keys()),
                "triggers": list(d.triggers.keys()),
                "credential_types": list(d.credential_types.keys()),
                "metadata": d.metadata,
            }
            for d in definitions
        ]
    )


@router.get("/{connector_key}")
def get_connector(
    connector_key: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get connector definition by key."""
    registry = get_registry()
    definition = registry.get_definition(connector_key)
    if definition is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Connector '{connector_key}' not found.",
        )
    return ok(
        {
            "connector_key": definition.connector_key,
            "display_name": definition.display_name,
            "description": definition.description,
            "category": definition.category,
            "connector_version": definition.connector_version,
            "lifecycle_status": definition.lifecycle_status,
            "icon": definition.icon,
            "operations": {
                k: {
                    "operation_key": op.operation_key,
                    "operation_version": op.operation_version,
                    "display_name": op.display_name,
                    "description": op.description,
                    "credential_require": op.credential_require,
                    "retryable": op.retryable,
                    "idempotency": op.idempotency,
                }
                for k, op in definition.operations.items()
            },
            "triggers": {
                k: {
                    "trigger_key": t.trigger_key,
                    "trigger_version": t.trigger_version,
                    "trigger_type": t.trigger_type,
                    "configuration_schema": t.configuration_schema,
                    "credential_require": t.credential_require,
                }
                for k, t in definition.triggers.items()
            },
            "credential_types": {
                k: {
                    "type_key": ct.type_key,
                    "display_name": ct.display_name,
                    "description": ct.description,
                    "secret_fields": ct.secret_fields,
                    "validation_schema": ct.validation_schema,
                    "encryption_required": ct.encryption_required,
                }
                for k, ct in definition.credential_types.items()
            },
            "metadata": definition.metadata,
        }
    )


@router.get("/{connector_key}/operations")
def get_connector_operations(
    connector_key: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get operation definitions for a connector."""
    registry = get_registry()
    definition = registry.get_definition(connector_key)
    if definition is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Connector '{connector_key}' not found.",
        )
    return ok(
        {
            "connector_key": connector_key,
            "operations": {
                op_key: {
                    "operation_key": op.operation_key,
                    "operation_version": op.operation_version,
                    "display_name": op.display_name,
                    "description": op.description,
                    "input_schema": op.input_schema,
                    "output_schema": op.output_schema,
                    "credential_require": op.credential_require,
                    "retryable": op.retryable,
                    "idempotency": op.idempotency,
                }
                for op_key, op in definition.operations.items()
            },
        }
    )


@router.get("/{connector_key}/triggers")
def get_connector_triggers(
    connector_key: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get trigger definitions for a connector."""
    registry = get_registry()
    definition = registry.get_definition(connector_key)
    if definition is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Connector '{connector_key}' not found.",
        )
    return ok(
        {
            "connector_key": connector_key,
            "triggers": {
                trigger_key: {
                    "trigger_key": t.trigger_key,
                    "trigger_version": t.trigger_version,
                    "trigger_type": t.trigger_type,
                    "configuration_schema": t.configuration_schema,
                    "credential_require": t.credential_require,
                }
                for trigger_key, t in definition.triggers.items()
            },
        }
    )


@router.get("/{connector_key}/credential-types")
def get_connector_credential_types(
    connector_key: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get credential type definitions for a connector."""
    registry = get_registry()
    definition = registry.get_definition(connector_key)
    if definition is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Connector '{connector_key}' not found.",
        )
    return ok(
        {
            "connector_key": connector_key,
            "credential_types": {
                ct_type: {
                    "type_key": ct.type_key,
                    "display_name": ct.display_name,
                    "description": ct.description,
                    "secret_fields": ct.secret_fields,
                    "validation_schema": ct.validation_schema,
                    "encryption_required": ct.encryption_required,
                }
                for ct_type, ct in definition.credential_types.items()
            },
        }
    )