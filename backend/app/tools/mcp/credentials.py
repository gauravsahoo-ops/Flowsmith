"""MCP credential resolution.

Server records reference credentials by id; this module turns that reference
into the bearer token used by the transport. It never returns, logs, or embeds
the decrypted credential payload in an error.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.credentials.resolver import get_credential_resolver
from app.models import Credential, MCPServer
from app.tools.mcp.discovery import MCPDiscoveryError
from app.tools.mcp.registry import MCPServiceError

TOKEN_KEYS: tuple[str, ...] = (
    "token",
    "api_key",
    "access_token",
    "private_token",
    "bearer_token",
)

_MISSING_MESSAGE = "MCP server credential could not be resolved."


def _credential_required(message: str = _MISSING_MESSAGE) -> MCPDiscoveryError:
    return MCPDiscoveryError("MCP_CREDENTIAL_REQUIRED", message)


def _extract_token(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in TOKEN_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def resolve_mcp_auth_token(
    db: Session,
    server: MCPServer,
    user_id: int,
) -> str | None:
    """Resolve the bearer token for an MCP server.

    ``none`` servers need no secret. ``bearer`` and ``credential`` servers load
    ``server.credential_id``, require that it belongs to ``user_id`` (the API
    layer enforces workspace edit access), resolve it through the credential
    resolver, and read the first usable token field.

    Raises ``MCPDiscoveryError`` with code ``MCP_CREDENTIAL_REQUIRED`` when the
    reference is missing, foreign, undecryptable, or has no token field.
    """
    if server.auth_type == "none":
        return None
    if server.auth_type not in ("bearer", "credential"):
        raise MCPServiceError(
            f"Unsupported MCP auth type: {server.auth_type!r}",
            code="MCP_INVALID",
        )

    credential_id = (server.credential_id or "").strip()
    if not credential_id:
        raise _credential_required(
            "MCP server requires a credential, but none is configured."
        )

    credential = db.get(Credential, credential_id)
    if credential is None or credential.user_id != user_id:
        raise _credential_required()

    try:
        data, _provider = get_credential_resolver().resolve(
            db,
            user_id,
            credential.type,
            credential.id,
        )
    except Exception as exc:  # noqa: BLE001 - keep decrypted material out of errors
        raise _credential_required() from exc

    token = _extract_token(data)
    if token is None:
        raise _credential_required(
            "MCP server credential does not contain a usable token."
        )
    return token
