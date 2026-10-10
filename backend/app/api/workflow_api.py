"""Workflow-as-API (original implementation).

Programmatic execution with a minted `UserAPIKey` (see /api/apikeys)
instead of a JWT: ``X-API-Key: <raw key>``.

- ``POST /api/w/{workflow_id}/execute`` — async by default (202 +
  execution id); ``?mode=sync`` waits bounded for completion and
  returns outputs (or the error) inline.
- Only owners and edit-shares may execute; view shares and strangers
  get 404 (existence hidden, like the rest of the API).
- Per-key rate budget + expiry + revocation enforced here; usage
  stamps ``last_used_at``.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.access import get_permission
from app.api.common import ok
from app.config import get_settings
from app.db import get_db
from app.metrics import ratelimit_rejected
from app.models import Execution as ExecutionModel
from app.models import User, UserAPIKey, WorkflowRecord

router = APIRouter(prefix="/api/w", tags=["workflow-api"])

_settings = get_settings()
from app.security.ratelimit import get_webhook_limiter

_limiter = get_webhook_limiter(
    capacity=_settings.webhook_rate_limit,
    window_s=_settings.webhook_rate_period_s,
)

SYNC_WAIT_CAP = 120.0


def _key_owner(raw_key: str | None, db: Session) -> tuple[User, UserAPIKey]:
    if not raw_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key.")
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    rec = db.scalar(
        select(UserAPIKey).where(UserAPIKey.key_hash == digest, UserAPIKey.is_active.is_(True))
    )
    if rec is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key.")
    expires = rec.expires_at
    if expires is not None and expires.replace(tzinfo=UTC) <= datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key expired.")
    user = db.get(User, rec.user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key owner inactive.")
    rec.last_used_at = datetime.now(UTC)
    db.commit()
    return user, rec


@router.post("/{workflow_id}/execute", status_code=status.HTTP_202_ACCEPTED)
async def execute_workflow_api(
    workflow_id: str,
    request: Request,
    response: Response,
    x_api_key: str | None = Header(default=None),
    mode: Literal["async", "sync"] = Query(default="async"),
    wait_seconds: float = Query(default=60.0, ge=1, le=SYNC_WAIT_CAP),
    db: Session = Depends(get_db),
) -> dict:
    user, key_rec = _key_owner(x_api_key, db)

    allowed, retry_after = _limiter.allow(f"apikey:{key_rec.prefix}")
    if not allowed:
        ratelimit_rejected.inc(("workflow-api",))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "API rate limit exceeded.",
            headers={"Retry-After": str(retry_after)},
        )

    permission = get_permission(db, workflow_id, user)
    if permission not in ("owner", "edit"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    rec = db.get(WorkflowRecord, workflow_id)
    assert rec is not None

    try:
        raw = await request.body()
        payload: Any = {}
        if raw:
            import json

            payload = json.loads(raw)
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Body must be JSON.")
    if payload is None:
        payload = {}
    trigger_items = payload if isinstance(payload, list) else [payload if isinstance(payload, dict) else {"value": payload}]

    from app.api.executions import start_execution, workflow_workspace
    from app.billing.service import enforce_can_start_execution

    workspace_id = workflow_workspace(db, rec.id)
    enforce_can_start_execution(db, workspace_id)

    try:
        execution_id = start_execution(
            db,
            workflow_id=rec.id,
            user_id=user.id,
            version=rec.version,
            workflow_data=rec.data,
            trigger="api",
            trigger_items=trigger_items,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        from app.engine.errors import WorkflowValidationError
        if isinstance(exc, WorkflowValidationError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.to_dict())
        raise

    if mode == "async":
        return ok({"execution_id": execution_id, "status": "queued"}, {"mode": "async"})

    deadline = time.monotonic() + min(wait_seconds, SYNC_WAIT_CAP)
    response.status_code = status.HTTP_200_OK
    while time.monotonic() < deadline:
        db.expire_all()
        exec_rec = db.get(ExecutionModel, execution_id)
        if exec_rec is not None and exec_rec.status not in ("queued", "running", "cancelling"):
            if exec_rec.status == "success":
                return ok({
                    "execution_id": execution_id, "status": "success",
                    "outputs": (exec_rec.results or {}).get("outputs", {}),
                }, {"mode": "sync"})
            return ok({
                "execution_id": execution_id, "status": exec_rec.status,
                "error": exec_rec.error,
            }, {"mode": "sync"})
        await asyncio.sleep(0.25)
    return ok({
        "execution_id": execution_id, "status": "timeout", "timeout": True,
    }, {"mode": "sync"})
