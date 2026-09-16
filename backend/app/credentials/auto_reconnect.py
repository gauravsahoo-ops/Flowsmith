"""Credential Auto-Reconnect and Proactive Renewal Engine.

Provides automatic background renewal of expiring OAuth / API tokens and
seamless background reconnection without requiring interactive browser logins.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_state.adapter import (
    PROVIDER_REFRESH,
    canonical_provider,
    normalize_expires_at,
)
from app.config import get_settings
from app.credentials.oauth_manager import OAuthManager
from app.models.credential import Credential
from app.security.crypto import decrypt_text, encrypt_text

logger = logging.getLogger("credentials.auto_reconnect")


def is_credential_expiring(cred_data: dict[str, Any], window_seconds: float = 1800.0) -> bool:
    """Check if a credential token is expired or will expire within `window_seconds` (default 30 mins)."""
    raw_exp = cred_data.get("expires_at")
    exp_f = normalize_expires_at(raw_exp)
    if exp_f is None:
        return False
    return (time.time() + window_seconds) >= exp_f


def can_auto_reconnect(cred_type: str, cred_data: dict[str, Any]) -> bool:
    """Check whether a credential has the necessary parameters to reconnect in the background."""
    canon = canonical_provider(cred_type)
    if canon == "salesforce":
        has_refresh = bool(cred_data.get("refresh_token"))
        has_pwd = bool(cred_data.get("username") and cred_data.get("password"))
        return has_refresh or has_pwd

    if cred_data.get("refresh_token"):
        return True

    return False


async def reconnect_credential_data(
    cred_type: str,
    cred_data: dict[str, Any],
    credential_id: str | None = None,
) -> dict[str, Any]:
    """Execute background token refresh/re-authentication on raw credential data.

    Returns the updated credential dict. Raises Exception on failure.
    """
    canon = canonical_provider(cred_type)
    updated = dict(cred_data)
    if credential_id:
        updated["_credential_id"] = credential_id

    # 1. Salesforce Provider
    if canon == "salesforce":
        from app.providers.salesforce import SalesforceProviderClient

        client = SalesforceProviderClient()
        fresh_copy: dict[str, Any] = dict(updated)
        fresh_copy.pop("access_token", None)
        fresh_copy.pop("expires_at", None)
        token = await client.authenticate(fresh_copy)
        if not token:
            raise ValueError("Salesforce re-authentication did not return a valid token.")
        updated["access_token"] = token
        if fresh_copy.get("expires_at"):
            updated["expires_at"] = fresh_copy["expires_at"]
        else:
            updated["expires_at"] = time.time() + 7200.0
        if fresh_copy.get("refresh_token"):
            updated["refresh_token"] = fresh_copy["refresh_token"]
        if fresh_copy.get("instance_url"):
            updated["instance_url"] = fresh_copy["instance_url"]
        return updated

    # 2. General OAuth2 Providers (Google, HubSpot, Microsoft, GitHub, etc.)
    refresh_meta = PROVIDER_REFRESH.get(canon) or {}
    token_url = updated.get("token_url") or refresh_meta.get("token_url")
    if not token_url:
        raise ValueError(f"No token refresh endpoint known for provider '{cred_type}'.")

    settings = get_settings()
    client_id = updated.get("client_id") or getattr(settings, f"{canon}_client_id", "")
    client_secret = updated.get("client_secret") or getattr(settings, f"{canon}_client_secret", "")

    refresh_token = updated.get("refresh_token")
    if not refresh_token:
        raise ValueError(f"Credential '{cred_type}' has no refresh_token.")

    manager = OAuthManager()
    refreshed = await manager.refresh({
        **updated,
        "token_url": token_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })
    return refreshed


async def reconnect_credential(db: Session, user_id: int, credential_id: str) -> dict[str, Any]:
    """Manually or programmatically trigger background reconnection for a user's credential.

    Returns a status dict: {"ok": bool, "message": str, "refreshed": bool, ...}
    """
    rec = db.get(Credential, credential_id)
    if rec is None or rec.user_id != user_id:
        return {"ok": False, "message": "Credential not found or not owned by user."}

    try:
        data = json.loads(decrypt_text(rec.data))
    except Exception as exc:
        return {"ok": False, "message": f"Cannot decrypt credential: {exc}"}

    if not can_auto_reconnect(rec.type, data):
        return {
            "ok": False,
            "message": f"Credential '{rec.name}' ({rec.type}) does not support automatic background reconnection.",
            "interactive_required": True,
        }

    try:
        updated = await reconnect_credential_data(rec.type, data, credential_id=rec.id)
        clean_to_save = {k: v for k, v in updated.items() if not k.startswith("_")}
        rec.data = encrypt_text(json.dumps(clean_to_save))
        db.commit()
        db.refresh(rec)
        logger.info("Successfully auto-reconnected credential %s (%s)", rec.id, rec.type)
        return {
            "ok": True,
            "message": f"Credential '{rec.name}' reconnected successfully.",
            "refreshed": True,
            "id": rec.id,
            "type": rec.type,
        }
    except Exception as exc:
        logger.warning("Background auto-reconnect failed for %s (%s): %s", rec.id, rec.type, exc)
        return {
            "ok": False,
            "message": f"Automatic reconnection failed: {exc}",
            "interactive_required": True,
        }


async def auto_refresh_all_expiring_credentials(db: Session, window_minutes: int = 30) -> dict[str, int]:
    """Background sweep routine: finds all stored credentials expiring soon and refreshes them.

    Returns summary counts: {"checked": n, "refreshed": n, "skipped": n, "failed": n}.
    """
    window_seconds = window_minutes * 60.0
    recs = db.scalars(select(Credential)).all()
    stats = {"checked": len(recs), "refreshed": 0, "skipped": 0, "failed": 0}

    for rec in recs:
        try:
            data = json.loads(decrypt_text(rec.data))
        except Exception:
            stats["skipped"] += 1
            continue

        if not can_auto_reconnect(rec.type, data):
            stats["skipped"] += 1
            continue

        if not is_credential_expiring(data, window_seconds=window_seconds):
            stats["skipped"] += 1
            continue

        try:
            logger.info("Proactively renewing credential %s (%s) expiring soon", rec.id, rec.type)
            updated = await reconnect_credential_data(rec.type, data, credential_id=rec.id)
            clean_to_save = {k: v for k, v in updated.items() if not k.startswith("_")}
            rec.data = encrypt_text(json.dumps(clean_to_save))
            db.commit()
            stats["refreshed"] += 1
            logger.info("Successfully renewed credential %s (%s)", rec.id, rec.type)
        except Exception as exc:
            stats["failed"] += 1
            logger.warning("Auto-refresh failed for %s (%s): %s", rec.id, rec.type, exc)

    return stats
