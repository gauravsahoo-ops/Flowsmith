"""Credential Auto-Reconnect and Proactive Renewal Engine.

Provides automatic background renewal of expiring OAuth / API tokens and
seamless background reconnection without requiring interactive browser logins.
"""

from __future__ import annotations

import asyncio
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

#: Max owners listed in the sweep summary audit's ``detail.user_ids``.
#: ``detail.user_count`` always carries the full cardinality and
#: ``detail.user_ids_truncated`` tells consumers whether the list is complete.
MAX_SWEEP_AUDIT_USER_IDS = 50


def _load_batch(db: Session, chunk: list[str], use_locking: bool) -> list[Credential]:
    """Fetch one sweep batch (sync DB) — called via asyncio.to_thread."""
    if use_locking:
        try:
            return list(db.scalars(
                select(Credential)
                .where(Credential.id.in_(chunk))
                .order_by(Credential.id)
                .with_for_update(skip_locked=True)
            ).all())
        except Exception:
            return [r for r in (db.get(Credential, cid) for cid in chunk) if r is not None]
    return [r for r in (db.get(Credential, cid) for cid in chunk) if r is not None]


def is_credential_expiring(cred_data: dict[str, Any], window_seconds: float = 1800.0) -> bool:
    """Check if a credential token is expired or will expire within `window_seconds` (default 30 mins)."""
    raw_exp = cred_data.get("expires_at")
    exp_f = normalize_expires_at(raw_exp)
    if exp_f is None:
        return False
    return (time.time() + window_seconds) >= exp_f


def can_auto_reconnect(cred_type: str, cred_data: dict[str, Any]) -> bool:
    """Check whether a credential has the necessary parameters to reconnect in the background."""
    if cred_data.get("refresh_token_expired"):
        return False

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
        # NOTE: SalesforceProviderClient.authenticate() mutates the dict it is
        # given in place (access_token/expires_at/refresh_token) and persists
        # to the DB itself when "_credential_id" is present. We pass an
        # explicit copy and read the rotated values back from it, so the
        # contract does not depend on hidden side effects.
        fresh_copy: dict[str, Any] = dict(updated)
        fresh_copy.pop("access_token", None)
        fresh_copy.pop("expires_at", None)
        token = await client.authenticate(fresh_copy, force=True)
        if not token:
            raise ValueError("Salesforce re-authentication did not return a valid token.")
        updated["access_token"] = token
        raw_exp = fresh_copy.get("expires_at")
        try:
            updated["expires_at"] = float(raw_exp) if raw_exp else time.time() + 7200.0
        except (TypeError, ValueError):
            updated["expires_at"] = time.time() + 7200.0
        # Rotation-aware: authenticate() only overwrites refresh_token when
        # the provider returns a new one, otherwise the previous value
        # survives in fresh_copy and is preserved here.
        if fresh_copy.get("refresh_token"):
            updated["refresh_token"] = fresh_copy["refresh_token"]
        instance_url = fresh_copy.get("instance_url") or getattr(client, "_instance_url", "")
        if instance_url:
            updated["instance_url"] = instance_url
        return updated

    # 2. General OAuth2 Providers (Google, HubSpot, Microsoft, GitHub, etc.)
    refresh_meta = PROVIDER_REFRESH.get(canon) or {}
    token_url = updated.get("token_url") or refresh_meta.get("token_url")
    if not token_url:
        raise ValueError(f"No token refresh endpoint known for provider '{cred_type}'.")

    settings = get_settings()
    # Server-side OAuth app credentials stay server-side: prefer the bundle's
    # stored client_id/secret, else the deployment's settings for this
    # canonical provider. Not every provider has a server-side app
    # (e.g. microsoft/github have no *_client_id in Settings); in that case
    # the bundle must carry them, otherwise refresh fails fast below.
    # NOTE: cred_type aliases (google_calendar -> google, msteams ->
    # microsoft, ...) are already canonicalized, so the settings key uses
    # the canonical name on purpose.
    server_client_id = getattr(settings, f"{canon}_client_id", "") or ""
    server_client_secret = getattr(settings, f"{canon}_client_secret", "") or ""
    client_id = updated.get("client_id") or server_client_id
    client_secret = updated.get("client_secret") or server_client_secret

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
        return {"ok": False, "code": "NOT_FOUND", "message": "Credential not found or not owned by user."}

    try:
        data = json.loads(decrypt_text(rec.data))
    except Exception:
        logger.warning("Cannot decrypt credential %s for auto-reconnect", credential_id)
        return {"ok": False, "code": "DECRYPT_FAILED", "message": "Cannot decrypt credential."}

    if not can_auto_reconnect(rec.type, data):
        return {
            "ok": False,
            "message": f"Credential '{rec.name}' ({rec.type}) requires re-authorization.",
            "interactive_required": True,
            "login_url": data.get("login_url") or data.get("instance_url") or "",
        }

    try:
        updated = await reconnect_credential_data(rec.type, data, credential_id=rec.id)
        clean_to_save = {k: v for k, v in updated.items() if not k.startswith("_")}
        rec.data = encrypt_text(json.dumps(clean_to_save))
        await asyncio.to_thread(db.commit)
        await asyncio.to_thread(db.refresh, rec)
        logger.info("Successfully auto-reconnected credential %s (%s)", rec.id, rec.type)
        return {
            "ok": True,
            "message": f"Credential '{rec.name}' reconnected successfully.",
            "refreshed": True,
            "id": rec.id,
            "type": rec.type,
        }
    except Exception as exc:
        err_str = str(exc).lower()
        if "invalid_grant" in err_str or "expired access/refresh token" in err_str:
            try:
                data["refresh_token_expired"] = True
                rec.data = encrypt_text(json.dumps(data))
                await asyncio.to_thread(db.commit)
            except Exception:
                await asyncio.to_thread(db.rollback)
        logger.warning("Background auto-reconnect failed for %s (%s): %s", rec.id, rec.type, exc)
        return {
            "ok": False,
            "message": f"Automatic reconnection failed: {exc}",
            "interactive_required": True,
            "login_url": data.get("login_url") or data.get("instance_url") or "",
        }


async def auto_refresh_all_expiring_credentials(
    db: Session, window_minutes: int = 30, batch_size: int = 100,
    verify_missing: bool = True,
) -> dict[str, int]:
    """Background sweep routine: finds all stored credentials expiring soon and refreshes them.

    Returns summary counts: {"checked", "refreshed", "skipped", "failed"}
    plus a stable breakdown (all ints, safe to add to): {"skipped_locked",
    "skipped_deleted", "skipped_decrypt", "skipped_not_eligible",
    "skipped_unverified"} where ``skipped`` is always the sum of the five.
    ``skipped_locked`` rows were claimed by a concurrent sweeper (postgres
    ``SKIP LOCKED``) and are retried on the next pass — not errors.
    ``skipped_unverified`` rows were not disambiguated (only possible with
    ``verify_missing=False``) and are likewise retried, never mislabelled.

    Snapshot + bounded batches: the sweep first snapshots matching PKs
    (``SELECT id`` — no secrets), then processes them in ``batch_size``
    chunks, re-fetching each row by PK. Credential ids are random strings,
    so positional keyset/offset pagination could skip rows when inserts or
    deletes land mid-sweep; a fixed snapshot cannot shift. Rows created
    mid-sweep are picked up on the next 10-minute pass (bounded delay);
    rows deleted mid-sweep are counted as skipped. On PostgreSQL each
    batch is locked with ``FOR UPDATE SKIP LOCKED`` so concurrent
    API/worker replicas skip rows another sweeper already claimed instead
    of double-refreshing them (other backends silently fall back to no
    locking).

    ``verify_missing`` (default True) disambiguates missing snapshot rows
    (deleted vs lock-skipped) with one PK-existence query per affected
    batch — steady-state passes with no missing rows issue zero extra
    queries. Pass False to skip verification entirely: missing rows are
    then counted honestly as ``skipped_unverified`` (still included in
    ``skipped``) instead of being guessed as locked or deleted.

    Audit-throttled: all-skipped passes write nothing; passes with a
    refresh or failure write ``credential.auto_refresh_sweep`` rows
    (``target_type="system"``, ``user_id=None``) sharing one ``sweep_id``:
    a page-1 summary with counts plus the first ``MAX_SWEEP_AUDIT_USER_IDS``
    owner ids, then one continuation page per further chunk of owners when
    more than the cap are touched — so the full owner set is always in the
    audit trail and never requires a follow-up credentials query.
    Consumers must not hand-group pages — call
    ``app.audit.collect_sweep_audit(db, sweep_id)`` which returns the
    reassembled owner list, completeness flag, and summary stats.
    User-initiated reconnects audit ``credential.reconnect`` per event.
    """
    window_seconds = window_minutes * 60.0
    stats = {
        "checked": 0,
        "refreshed": 0,
        "skipped": 0,
        "failed": 0,
        "skipped_locked": 0,
        "skipped_deleted": 0,
        "skipped_decrypt": 0,
        "skipped_not_eligible": 0,
        "skipped_unverified": 0,
    }
    affected_user_ids: set[int] = set()

    try:
        bind = db.get_bind()
        use_locking = getattr(getattr(bind, "dialect", None), "name", "") == "postgresql"
    except Exception:
        use_locking = False

    # PK-only snapshot: cheap, holds no secrets, immune to paging shifts.
    all_ids: list[str] = list(await asyncio.to_thread(
        lambda: db.scalars(select(Credential.id).order_by(Credential.id)).all()
    ))

    for start in range(0, len(all_ids), batch_size):
        chunk = all_ids[start:start + batch_size]
        batch = await asyncio.to_thread(_load_batch, db, chunk, use_locking)
        # Missing rows are either deleted after the snapshot or (postgres)
        # lock-skipped by a concurrent sweeper. With verify_missing (default)
        # disambiguate via a cheap PK-existence check so stats stay honest;
        # with verify_missing=False count them as skipped_unverified rather
        # than guessing locked vs deleted. Either way steady-state batches
        # with no missing rows cost nothing extra.
        if len(batch) < len(chunk):
            missing = set(chunk) - {r.id for r in batch}
            if not verify_missing:
                stats["skipped_unverified"] += len(missing)
                stats["skipped"] += len(missing)
            elif use_locking and missing:
                try:
                    still_there = set(await asyncio.to_thread(
                        lambda: db.scalars(select(Credential.id).where(Credential.id.in_(list(missing)))).all()
                    ))
                except Exception:
                    still_there = set()
                n_locked = len(still_there & missing)
                n_deleted = len(missing) - n_locked
                stats["skipped_locked"] += n_locked
                stats["skipped_deleted"] += n_deleted
                stats["skipped"] += n_locked + n_deleted
            else:
                stats["skipped_deleted"] += len(missing)
                stats["skipped"] += len(missing)
        for rec in batch:
            stats["checked"] += 1
            try:
                data = json.loads(decrypt_text(rec.data))
            except Exception:
                stats["skipped"] += 1
                stats["skipped_decrypt"] += 1
                continue

            needs_refresh = can_auto_reconnect(rec.type, data) and is_credential_expiring(
                data, window_seconds=window_seconds
            )
            # Drop plaintext before any network I/O; the refresh path
            # re-reads only what it needs.
            del data
            if not needs_refresh:
                stats["skipped"] += 1
                stats["skipped_not_eligible"] += 1
                continue

            fresh: dict[str, Any] | None = None
            try:
                logger.info("Proactively renewing credential %s (%s) expiring soon", rec.id, rec.type)
                loaded = json.loads(decrypt_text(rec.data))
                if not isinstance(loaded, dict):
                    continue
                fresh = loaded
                updated = await reconnect_credential_data(rec.type, fresh, credential_id=rec.id)
                clean_to_save = {k: v for k, v in updated.items() if not k.startswith("_")}
                rec.data = encrypt_text(json.dumps(clean_to_save))
                await asyncio.to_thread(db.commit)
                stats["refreshed"] += 1
                affected_user_ids.add(rec.user_id)
                logger.info("Successfully renewed credential %s (%s)", rec.id, rec.type)
            except Exception as exc:
                await asyncio.to_thread(db.rollback)
                stats["failed"] += 1
                try:
                    affected_user_ids.add(rec.user_id)
                except Exception:
                    pass
                err_str = str(exc).lower()
                if ("invalid_grant" in err_str or "expired access/refresh token" in err_str) and fresh is not None:
                    try:
                        fresh["refresh_token_expired"] = True
                        rec.data = encrypt_text(json.dumps(fresh))
                        await asyncio.to_thread(db.commit)
                        logger.warning(
                            "Auto-refresh for %s (%s) failed due to expired/revoked refresh token. Marked as requiring interactive re-login: %s",
                            rec.id, rec.type, exc
                        )
                    except Exception:
                        await asyncio.to_thread(db.rollback)
                        logger.warning("Auto-refresh failed for %s (%s): %s", rec.id, rec.type, exc)
                else:
                    logger.warning("Auto-refresh failed for %s (%s): %s", rec.id, rec.type, exc)
            finally:
                # Expire the row so decrypted state is not retained in the
                # identity map (refresh() still works for callers).
                try:
                    db.expire(rec)
                except Exception:
                    pass

    # Throttled summary audit: one row per sweep, only when something
    # happened — never on all-skipped passes, so the audit table is not
    # spammed every 10 minutes. Best-effort; sweep results never depend on it.
    # Owner pages: page 1 carries the counts; every page carries a chunk of
    # owner ids under a shared sweep_id, so the full owner set is always
    # reassemblable from the audit trail (no follow-up query needed).
    if stats["refreshed"] or stats["failed"]:
        try:
            import uuid as _uuid

            from app.audit import CREDENTIAL_SWEEP, log_event

            sweep_id = _uuid.uuid4().hex[:12]
            owner_ids = sorted(affected_user_ids)
            pages = [
                owner_ids[i:i + MAX_SWEEP_AUDIT_USER_IDS]
                for i in range(0, len(owner_ids), MAX_SWEEP_AUDIT_USER_IDS)
            ] or [[]]
            for page_no, ids_page in enumerate(pages, start=1):
                detail: dict[str, Any] = {
                    "sweep_id": sweep_id,
                    "page": page_no,
                    "pages": len(pages),
                    "user_ids": ids_page,
                    "user_count": len(owner_ids),
                }
                if page_no == 1:
                    detail.update(
                        {**stats, "window_minutes": window_minutes,
                         "sweep_id": sweep_id, "page": 1, "pages": len(pages)}
                    )
                # target_id always carries the sweep_id so page lookup is an
                # indexed (action, target_id) equality query — never a scan.
                await asyncio.to_thread(
                    log_event,
                    db,
                    CREDENTIAL_SWEEP,
                    target_type="system",
                    target_id=f"credential-sweep:{sweep_id}",
                    detail=detail,
                )
        except Exception:
            logger.exception("credential sweep summary audit failed")

    return stats
