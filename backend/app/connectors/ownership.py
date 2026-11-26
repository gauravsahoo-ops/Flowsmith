"""Per-user connector namespace resolution."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.openapi_emit import scoped_connector_key
from app.models import ConnectorPack, GeneratedConnector


def resolve_user_connector_key(
    db: Session, user_id: int, base_key: str
) -> str:
    """Return the caller's key for a generated connector.

    The first account to use a name keeps the plain key. Later accounts get a
    ``u<id>_`` namespace so the same manifest can be installed independently
    without overwriting anyone else's generated code.
    """
    owner = db.get(GeneratedConnector, base_key)
    if owner is not None:
        return (
            base_key
            if owner.user_id == user_id
            else scoped_connector_key(base_key, user_id)
        )

    pack = db.scalar(
        select(ConnectorPack).where(ConnectorPack.connector_key == base_key)
    )
    if pack is not None:
        return (
            base_key
            if pack.installed_by == user_id
            else scoped_connector_key(base_key, user_id)
        )

    # Built-in/shared generated connectors also occupy the plain key.
    try:
        from app.connectors import get_registry

        if get_registry().get_definition(base_key) is not None:
            return scoped_connector_key(base_key, user_id)
    except Exception:
        pass
    return base_key
