"""Public webhook endpoint (spec 9, 32): no auth, returns 202.

Flow (spec 32): validate path → validate method → validate payload size
→ create execution → queue → 202. Every hit gets a delivery record.
Spec 8.4: if the workflow already has a running execution the hit is
accepted but skipped (like n8n). An optional Idempotency-Key header
makes retries return the original delivery instead of re-queuing.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import ok, page_params
from app.api.auth import get_current_user
from app.config import get_settings
from app.db import get_db, get_session
from app.metrics import ratelimit_rejected, webhook_deliveries
from app.models import WebhookDelivery
from app.security.ratelimit import get_webhook_limiter
from app.triggers.registry import FORM_TRIGGER_PREFIX, get_webhook

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

MAX_WEBHOOK_BODY = 5 * 1024 * 1024  # spec: 5 MB

_settings = get_settings()
# Shared Redis budget when REDIS_URL is configured (multi-replica safe);
# per-process sliding window otherwise (audit phase 13).
from app.security.ratelimit import get_webhook_limiter

_limiter = get_webhook_limiter(
    capacity=_settings.webhook_rate_limit,
    window_s=_settings.webhook_rate_period_s,
)


def _payload(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", errors="replace")


@router.post("/{path}", status_code=status.HTTP_202_ACCEPTED)
async def webhook_receive(path: str, request: Request) -> dict:
    db = get_session()
    try:
        wh = get_webhook(db, path)
        if wh is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown webhook path.")
        if request.method != wh.method:
            raise HTTPException(status.HTTP_405_METHOD_NOT_ALLOWED, f"Webhook expects {wh.method}.")

        idempotency_key = request.headers.get("idempotency-key")
        if idempotency_key:
            replay = db.scalars(
                select(WebhookDelivery).where(
                    WebhookDelivery.path == path,
                    WebhookDelivery.idempotency_key == idempotency_key,
                )
            ).first()
            if replay is not None:
                # Spec 32: duplicate delivery with the same key returns the
                # original result; no second execution is created.
                return ok({
                    "delivery_id": replay.id,
                    "execution_id": replay.execution_id,
                    "skipped": replay.status == "skipped",
                    "replayed": True,
                })

        allowed, retry_after = _limiter.allow(f"webhook:{path}")
        if not allowed:
            ratelimit_rejected.inc(("webhook",))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Webhook rate limit exceeded.",
                headers={"Retry-After": str(retry_after)},
            )

        length = request.headers.get("content-length")
        if length and int(length) > MAX_WEBHOOK_BODY:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Body exceeds 5 MB limit.")
        raw = await request.body()
        if len(raw) > MAX_WEBHOOK_BODY:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Body exceeds 5 MB limit.")

        delivery_id = f"dlv_{uuid.uuid4().hex[:12]}"
        trigger_items = [{
            "body": _payload(raw),
            "headers": dict(request.headers),
            "query": dict(request.query_params),
            "params": {},
        }]

        from app.api.executions import has_running_execution, start_execution, workflow_workspace

        if has_running_execution(db, wh.workflow_id):
            webhook_deliveries.inc(("skipped",))
            db.add(WebhookDelivery(
                id=delivery_id,
                workflow_id=wh.workflow_id,
                user_id=wh.user_id,
                path=path,
                status="skipped",
                response_code=status.HTTP_202_ACCEPTED,
                execution_id=None,
                idempotency_key=idempotency_key,
            ))
            db.commit()
            return ok({
                "delivery_id": delivery_id,
                "execution_id": None,
                "skipped": True,
            })

        try:
            execution_id = start_execution(
                db,
                workflow_id=wh.workflow_id,
                user_id=wh.user_id,
                version=wh.workflow_version,
                workflow_data=wh.workflow_data,
                trigger="webhook",
                trigger_items=trigger_items,
                workspace_id=workflow_workspace(db, wh.workflow_id),
            )
        except Exception as exc:
            # Credential validation before queue — fail fast with clear 422
            from app.engine.errors import WorkflowValidationError
            if isinstance(exc, WorkflowValidationError):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.to_dict())
            raise
        webhook_deliveries.inc(("queued",))
        db.add(WebhookDelivery(
            id=delivery_id,
            workflow_id=wh.workflow_id,
            user_id=wh.user_id,
            path=path,
            status="queued",
            response_code=status.HTTP_202_ACCEPTED,
            execution_id=execution_id,
            idempotency_key=idempotency_key,
        ))
        db.commit()
        return ok({
            "delivery_id": delivery_id,
            "execution_id": execution_id,
            "skipped": False,
        })
    finally:
        db.close()


@router.get("/deliveries")
def list_deliveries(
    _: object = Depends(get_current_user),
    db: Session = Depends(get_db),
    workflow_id: str | None = None,
    node_id: str | None = None,
    page: int = 1,
    pageSize: int = 50,
) -> dict:
    """Authenticated endpoint to list webhook deliveries with pagination."""
    from app.api.access import accessible_ids
    from app.models import User
    page, size = page_params(page=page, pageSize=pageSize)
    stmt = select(WebhookDelivery)
    count_stmt = select(func.count()).select_from(WebhookDelivery)
    if workflow_id:
        stmt = stmt.where(WebhookDelivery.workflow_id == workflow_id)
        count_stmt = count_stmt.where(WebhookDelivery.workflow_id == workflow_id)
    total = db.scalar(count_stmt) or 0
    deliveries = db.scalars(
        stmt.order_by(WebhookDelivery.received_at.desc(), WebhookDelivery.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return ok(
        [
            {
                "id": d.id,
                "workflow_id": d.workflow_id,
                "path": d.path,
                "status": d.status,
                "response_code": d.response_code,
                "execution_id": d.execution_id,
                "received_at": d.received_at,
            }
            for d in deliveries
        ],
        {"page": page, "pageSize": size, "total": total},
    )


# ----------------------------------------------------------------------
# Public forms (Batch D): definition + submission on the `form/` namespace.
# ----------------------------------------------------------------------

_EMAIL_RE = None  # compiled lazily to keep import cheap


def _form_node_params(workflow_data: dict) -> dict | None:
    """Params of the first form_trigger node in a workflow snapshot."""
    for node in (workflow_data or {}).get("nodes", []):
        if isinstance(node, dict) and node.get("type") == "form_trigger":
            params = node.get("parameters") or {}
            if isinstance(params, dict):
                return params
    return None


def _validate_form_fields(params: dict, body: Any) -> dict:
    """Coerce + check a submission against the form definition.

    Returns the validated field dict. Raises 422 with a readable detail.
    Unknown keys are dropped; headers are never persisted.
    """
    import re

    global _EMAIL_RE
    if _EMAIL_RE is None:
        _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    fields = params.get("fields") or []
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Form submission must be a JSON object.")
    out: dict[str, Any] = {}
    for spec in fields:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or "")
        ftype = str(spec.get("type") or "text")
        required = bool(spec.get("required"))
        raw = body.get(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if required:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Field '{name}' is required.")
            continue
        try:
            if ftype == "number":
                out[name] = float(raw) if "." in str(raw) else int(raw)
            elif ftype == "boolean":
                if isinstance(raw, bool):
                    out[name] = raw
                elif str(raw).lower() in ("true", "1", "yes", "on"):
                    out[name] = True
                elif str(raw).lower() in ("false", "0", "no", "off"):
                    out[name] = False
                else:
                    raise ValueError(f"not a boolean: {raw!r}")
            else:
                out[name] = str(raw)
                if ftype == "email" and not _EMAIL_RE.match(out[name]):
                    raise ValueError(f"not an email: {raw!r}")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Field '{name}' is invalid.")
    return out


@router.get("/form/{slug}", status_code=status.HTTP_200_OK)
def form_definition(slug: str) -> dict:
    """Public form definition (title + fields) for rendering."""
    db = get_session()
    try:
        wh = get_webhook(db, f"{FORM_TRIGGER_PREFIX}{slug}")
        if wh is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown form.")
        params = _form_node_params(wh.workflow_data) or {}
        return ok({
            "path": wh.path,
            "title": params.get("title", "Form"),
            "fields": params.get("fields", []),
        })
    finally:
        db.close()


@router.post("/form/{slug}", status_code=status.HTTP_202_ACCEPTED)
async def form_submit(slug: str, request: Request) -> dict:
    """Public form submission: validate fields, queue an execution, 202."""
    db = get_session()
    try:
        path = f"{FORM_TRIGGER_PREFIX}{slug}"
        wh = get_webhook(db, path)
        if wh is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown form.")
        params = _form_node_params(wh.workflow_data) or {}

        allowed, retry_after = _limiter.allow(f"webhook:{path}")
        if not allowed:
            ratelimit_rejected.inc(("webhook",))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Form rate limit exceeded.",
                headers={"Retry-After": str(retry_after)},
            )

        length = request.headers.get("content-length")
        if length and int(length) > MAX_WEBHOOK_BODY:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Body exceeds 5 MB limit.")
        raw = await request.body()
        if len(raw) > MAX_WEBHOOK_BODY:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Body exceeds 5 MB limit.")
        form = _validate_form_fields(params, _payload(raw))
        trigger_items = [{"form": form, "query": dict(request.query_params)}]

        from app.api.executions import has_running_execution, start_execution, workflow_workspace

        delivery_id = f"dlv_{uuid.uuid4().hex[:12]}"
        if has_running_execution(db, wh.workflow_id):
            webhook_deliveries.inc(("skipped",))
            db.add(WebhookDelivery(
                id=delivery_id,
                workflow_id=wh.workflow_id,
                user_id=wh.user_id,
                path=path,
                status="skipped",
                response_code=status.HTTP_202_ACCEPTED,
                execution_id=None,
            ))
            db.commit()
            return ok({"delivery_id": delivery_id, "execution_id": None, "skipped": True})

        try:
            execution_id = start_execution(
                db,
                workflow_id=wh.workflow_id,
                user_id=wh.user_id,
                version=wh.workflow_version,
                workflow_data=wh.workflow_data,
                trigger="webhook",
                trigger_items=trigger_items,
                workspace_id=workflow_workspace(db, wh.workflow_id),
            )
        except Exception as exc:
            from app.engine.errors import WorkflowValidationError
            if isinstance(exc, WorkflowValidationError):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.to_dict())
            raise
        webhook_deliveries.inc(("queued",))
        db.add(WebhookDelivery(
            id=delivery_id,
            workflow_id=wh.workflow_id,
            user_id=wh.user_id,
            path=path,
            status="queued",
            response_code=status.HTTP_202_ACCEPTED,
            execution_id=execution_id,
        ))
        db.commit()
        return ok({"delivery_id": delivery_id, "execution_id": execution_id, "skipped": False})
    finally:
        db.close()
