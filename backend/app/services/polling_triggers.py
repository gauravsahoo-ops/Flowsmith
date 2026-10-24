"""Generic HTTP polling trigger daemon.

Claims due rows with PostgreSQL row locks, fetches JSON with the shared
SSRF-safe HTTP client, deduplicates items, and starts one workflow execution
with the new items. Polling is deliberately generic; provider-specific
subscription registration remains separate.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import PollingTrigger

logger = logging.getLogger("triggers.polling")

POLL_TICK_SECONDS = 5
POLL_BATCH_SIZE = 20
MAX_ITEMS_PER_POLL = 100
MAX_SEEN_KEYS = 1000


def _dig(data: Any, path: str) -> Any:
    current = data
    for part in [part for part in path.split(".") if part]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _extract_items(payload: Any, path: str) -> list[Any]:
    value = _dig(payload, path) if path else payload
    if isinstance(value, list):
        return value[:MAX_ITEMS_PER_POLL]
    if value is None:
        return []
    return [value]


def _dedupe_key(item: Any, field: str) -> str:
    value = _dig(item, field) if field else None
    if value is None:
        value = item
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


async def _fetch(trigger: PollingTrigger) -> tuple[Any, dict[str, str]]:
    from app.security.safe_http_client import get_safe_http_client

    client = get_safe_http_client()
    response = await client.request(
        trigger.method,
        trigger.url,
        headers=trigger.headers or None,
        json=trigger.json_body if trigger.method == "POST" else None,
        timeout=30.0,
        max_response_bytes=2 * 1024 * 1024,
    )
    response.raise_for_status()
    return response.json(), dict(response.headers)


def _queue_items(db: Session, trigger: PollingTrigger, items: list[Any]) -> bool:
    from app.api.executions import has_running_execution, start_execution, workflow_workspace

    if has_running_execution(db, trigger.workflow_id):
        return False
    workspace_id = workflow_workspace(db, trigger.workflow_id)
    from app.billing.service import enforce_can_start_execution
    from fastapi import HTTPException

    try:
        enforce_can_start_execution(db, workspace_id)
    except HTTPException:
        return False
    start_execution(
        db,
        workflow_id=trigger.workflow_id,
        user_id=trigger.user_id,
        version=trigger.workflow_version,
        workflow_data=trigger.workflow_data,
        trigger="poll",
        trigger_items=[
            {"body": item, "headers": {}, "query": {}, "params": {}}
            for item in items
        ],
        workspace_id=workspace_id,
    )
    return True


async def poll_due(now: datetime | None = None) -> int:
    """Poll due triggers; returns the number of executions started."""
    now = now or datetime.now(UTC)
    db = get_session()
    started = 0
    try:
        due = db.execute(
            select(PollingTrigger)
            .where(
                PollingTrigger.status == "active",
                PollingTrigger.next_poll_at <= now,
            )
            .order_by(PollingTrigger.next_poll_at)
            .limit(POLL_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for trigger in due:
            trigger.next_poll_at = now + timedelta(seconds=max(30, trigger.interval_seconds))
            trigger.last_polled_at = now
            db.commit()
            try:
                payload, headers = await _fetch(trigger)
                items = _extract_items(payload, trigger.items_path)
                seen = [str(key) for key in (trigger.seen_keys or [])]
                seen_set = set(seen)
                new_items: list[Any] = []
                new_keys: list[str] = []
                for item in items:
                    key = _dedupe_key(item, trigger.dedupe_field)
                    if key in seen_set:
                        continue
                    seen_set.add(key)
                    new_keys.append(key)
                    new_items.append(item)
                if new_items and _queue_items(db, trigger, new_items):
                    trigger.seen_keys = (seen + new_keys)[-MAX_SEEN_KEYS:]
                    trigger.last_error = None
                    started += 1
                elif new_items:
                    trigger.last_error = "workflow already running or quota blocked"
                db.commit()
            except Exception as exc:
                db.rollback()
                trigger = db.get(PollingTrigger, trigger.id)
                if trigger is not None:
                    trigger.last_error = str(exc)[:1000]
                    trigger.next_poll_at = now + timedelta(
                        seconds=max(30, trigger.interval_seconds)
                    )
                    db.commit()
                logger.warning("polling trigger %s failed: %s", trigger.id if trigger else "?", exc)
        return started
    finally:
        db.close()


class PollingDaemon:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await poll_due()
            except Exception:
                logger.exception("polling trigger tick failed")
            await asyncio.sleep(POLL_TICK_SECONDS)

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


polling_daemon = PollingDaemon()
