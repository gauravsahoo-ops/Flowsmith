"""Background cleanup for provider-side webhook registrations.

The API removes registrations immediately on explicit DELETE. This reaper
handles workflow deactivation, deletion, or a provider registration that was
orphaned by another process.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.credentials.service import CredentialError, resolve_credentials
from app.db import get_session
from app.models import ProviderWebhookRegistration, WorkflowRecord
from app.schemas.workflow import Workflow
from app.services.provider_webhooks import (
    PROVIDER_BY_NODE,
    ProviderWebhookError,
    unregister_provider_webhook,
)

logger = logging.getLogger("provider_webhooks.reaper")

REAP_INTERVAL_SECONDS = 60.0


def _node_still_exists(rec: WorkflowRecord | None, row: ProviderWebhookRegistration) -> bool:
    if rec is None or not rec.active or rec.deleted_at is not None:
        return False
    try:
        workflow = Workflow.model_validate(rec.data)
    except Exception:
        return False
    for node in workflow.nodes:
        if node.id != row.node_id or PROVIDER_BY_NODE.get(node.type) != row.provider:
            continue
        path = str((node.parameters or {}).get("path") or "").strip()
        if path and row.callback_url.endswith(f"/api/webhooks/{path}"):
            return True
    return False


async def reap_provider_webhooks() -> int:
    """Remove provider webhooks whose workflow/node is no longer active."""
    db = get_session()
    removed = 0
    try:
        rows = db.execute(select(ProviderWebhookRegistration)).scalars().all()
        for row in rows:
            rec = db.get(WorkflowRecord, row.workflow_id)
            # An explicit force-unregister is a cleanup request even if the
            # workflow/node is still active; keep retrying it.
            if row.status != "orphaned" and _node_still_exists(rec, row):
                continue
            try:
                resolved = resolve_credentials(
                    db, row.user_id, {row.provider: row.credential_id}
                )
                credential = resolved.get(row.provider)
                if not isinstance(credential, dict):
                    raise CredentialError("Credential data could not be resolved.")
                await unregister_provider_webhook(
                    provider=row.provider,
                    credential=credential,
                    external_id=str(row.external_id or ""),
                    config=row.provider_config or {},
                )
                db.delete(row)
                db.commit()
                removed += 1
            except (CredentialError, ProviderWebhookError) as exc:
                was_orphaned = row.status == "orphaned"
                db.rollback()
                row = db.get(ProviderWebhookRegistration, row.id)
                if row is not None:
                    row.status = "orphaned" if was_orphaned else "error"
                    row.last_error = str(exc)[:1000]
                    db.commit()
                logger.warning("provider webhook %s cleanup failed: %s", row.id if row else "?", exc)
            except Exception:
                db.rollback()
                logger.exception("provider webhook %s cleanup crashed", row.id)
        return removed
    finally:
        db.close()


class ProviderWebhookReaper:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await reap_provider_webhooks()
            except Exception:
                logger.exception("provider webhook reaper failed")
            await asyncio.sleep(REAP_INTERVAL_SECONDS)

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


provider_webhook_reaper = ProviderWebhookReaper()
