"""Background LDAP profile/group refresh daemon."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.audit import USER_ROLE_CHANGE, log_event
from app.config import get_settings
from app.db import engine, get_session
from app.models import User
from app.services.ldap_auth import LdapUnavailable, lookup_ldap_profile, parse_group_role_map, role_for_groups
from app.services.ldap_org_access import sync_ldap_organization_access
from app.services.ldap_workspace_access import sync_ldap_workspace_access

logger = logging.getLogger("ldap.sync")

LDAP_SYNC_LOCK_KEY = 0x4C444150  # "LDAP"


def _acquire_lock():
    if engine.dialect.name != "postgresql":
        return None, True
    try:
        conn = engine.connect()
        acquired = conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": LDAP_SYNC_LOCK_KEY}
        ).scalar()
        if not acquired:
            conn.close()
            return None, False
        return conn, True
    except Exception as exc:
        logger.warning("LDAP sync advisory lock unavailable: %s", exc)
        return None, False


def sync_all_ldap_users() -> int:
    """Refresh stored LDAP users; returns the number successfully refreshed."""
    settings = get_settings()
    if not settings.ldap_enabled or not settings.ldap_sync_enabled:
        return 0
    lock_conn, locked = _acquire_lock()
    if not locked:
        logger.info("LDAP sync skipped: advisory lock not acquired")
        return 0
    db = get_session()
    refreshed = 0
    try:
        users = db.execute(
            select(User).where(User.ldap_dn.is_not(None)).order_by(User.id)
        ).scalars().all()
        for user in users:
            try:
                profile = lookup_ldap_profile(user.ldap_dn or "")
            except LdapUnavailable as exc:
                logger.warning("LDAP sync unavailable for user %s: %s", user.id, exc)
                continue
            if profile is None:
                logger.warning("LDAP sync could not find user %s at %s", user.id, user.ldap_dn)
                continue
            groups = tuple(profile.groups)
            desired_role = role_for_groups(
                groups, parse_group_role_map(), settings.ldap_default_role
            )
            user.ldap_groups = json.dumps(list(groups))
            user.ldap_synced_at = datetime.now(UTC)
            if desired_role == "admin" and user.role != "admin":
                previous_role = user.role
                user.role = "admin"
                db.commit()
                log_event(
                    db,
                    USER_ROLE_CHANGE,
                    target_type="user",
                    target_id=str(user.id),
                    user_id=user.id,
                    detail={"from": previous_role, "to": "admin", "source": "ldap_sync"},
                )
            else:
                db.commit()
            try:
                sync_ldap_workspace_access(db, user, groups)
                sync_ldap_organization_access(db, user, groups)
            except Exception:
                db.rollback()
                logger.exception("LDAP access sync failed for user %s", user.id)
                continue
            refreshed += 1
        return refreshed
    finally:
        db.close()
        if lock_conn is not None:
            try:
                lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": LDAP_SYNC_LOCK_KEY}
                )
                lock_conn.close()
            except Exception:
                pass


class LdapSyncDaemon:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def ensure_started(self) -> None:
        settings = get_settings()
        if not settings.ldap_enabled or not settings.ldap_sync_enabled:
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                count = await asyncio.to_thread(sync_all_ldap_users)
                if count:
                    logger.info("LDAP sync refreshed %d users", count)
            except Exception:
                logger.exception("LDAP sync tick failed")
            await asyncio.sleep(max(60, get_settings().ldap_sync_interval_seconds))

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


ldap_sync = LdapSyncDaemon()
