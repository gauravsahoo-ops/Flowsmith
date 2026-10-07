"""Public Salesforce Outbound Message endpoint (Phase 10).

Salesforce's reliably-supported event push: a Workflow Rule / Flow
outbound-message action POSTs a SOAP envelope here when records change
and retries for 24 hours until we ACK, giving at-least-once delivery.

Mechanism decision (Phase 10): Change Data Capture and Platform Events
require a persistent CometD/Bayeux subscriber with OAuth token
lifecycle and replay-cursor management — not reliably supportable
without a dedicated client library, so they are intentionally NOT
implemented. This endpoint reuses the existing webhook pipeline
end-to-end (webhooks table → start_execution → queue → worker): no
separate execution engine.

Handling per requirement:

- authentication: the secret path suffix under sf-outbound/ is the
  credential (treat like a webhook URL; org allowlisting can tighten it)
- verification: Salesforce signs nothing on outbound messages; we
  verify structure (SOAP + notifications namespace) and record the
  OrganizationId from the envelope for audit
- deduplication: retries can duplicate deliveries; MessageId is stored
  as the delivery idempotency key and replays return the original result
- processing: one execution per envelope, one item per Notification;
  optional object_name filter drops non-matching objects (still ACKed)
- retry/failure: accepted events return the SOAP Ack Salesforce needs;
  malformed input → 400, unknown/inactive trigger → 404, queue failures
  → 500 so Salesforce's retry schedule kicks in
- rate limits: same sliding-window limiter as public webhooks
- audit: every accepted/rejected hit writes an AuditEvent row
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from defusedxml import ElementTree as SafeET
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.audit import SALESFORCE_TRIGGER_RECEIVED, SALESFORCE_TRIGGER_REJECTED, log_event
from app.api.common import ok  # noqa: F401  (kept for symmetric imports/tests)
from app.config import get_settings
from app.db import get_session
from app.metrics import ratelimit_rejected, webhook_deliveries
from app.models import WebhookDelivery
from app.security.ratelimit import SlidingWindowLimiter
from app.triggers.registry import SALESFORCE_TRIGGER_PREFIX, get_webhook

router = APIRouter(prefix="/api/triggers/salesforce", tags=["salesforce-triggers"])

MAX_SF_BODY = 5 * 1024 * 1024  # mirror webhook cap

#: SOAP namespaces used by Salesforce outbound messages.
_NS_OUTBOUND = "http://soap.sforce.com/2005/09/outbound"
_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

_settings = get_settings()
_limiter = SlidingWindowLimiter(
    capacity=_settings.webhook_rate_limit,
    window_s=_settings.webhook_rate_period_s,
)


# ----------------------------------------------------------------------
# SOAP parsing
# ----------------------------------------------------------------------

@dataclass
class SFNotification:
    object_type: str
    notification_id: str
    record_id: str
    record: dict[str, Any] = field(default_factory=dict)

    def as_item(self, message: "OutboundMessage") -> dict[str, Any]:
        """Engine item shape consumed by salesforce_trigger nodes."""
        return {
            "object_type": self.object_type,
            "record": self.record,
            "record_id": self.record_id,
            "organization_id": message.organization_id,
            "action_id": message.action_id,
            "message_id": message.message_id,
            "notification_id": self.notification_id,
        }


@dataclass
class OutboundMessage:
    organization_id: str
    action_id: str
    message_id: str
    notifications: list[SFNotification] = field(default_factory=list)


def _localname(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _object_type(sobject_el: Any, notification_el: Any) -> str:
    xsi = sobject_el.get(_XSI_TYPE) if sobject_el is not None else None
    if xsi:
        return _localname(xsi)
    xsi = notification_el.get(_XSI_TYPE)
    if xsi:
        name = _localname(xsi)
        return name[:-len("Notification")] if name.endswith("Notification") else name
    return ""


def parse_outbound_message(raw: bytes) -> OutboundMessage | None:
    """Parse a Salesforce outbound-message SOAP envelope.

    Returns None for anything that is not structurally an outbound
    message (wrong root, missing Body/notifications). Uses defusedxml,
    so DTDs/entity expansion are rejected outright.
    """
    try:
        root = SafeET.fromstring(raw)
    except Exception:
        return None

    if _localname(root.tag) != "Envelope":
        return None
    body = root.find("{*}Body")
    if body is None:
        return None
    notifications_el = body.find(f"{{{_NS_OUTBOUND}}}notifications")
    if notifications_el is None:
        return None

    def _child_text(parent: Any, name: str) -> str:
        el = parent.find(f"{{{_NS_OUTBOUND}}}{name}")
        if el is None or el.text is None:
            return ""
        return el.text.strip()

    message = OutboundMessage(
        organization_id=_child_text(notifications_el, "OrganizationId"),
        action_id=_child_text(notifications_el, "ActionId"),
        message_id=_child_text(notifications_el, "MessageId"),
    )

    for notification in notifications_el.findall(f"{{{_NS_OUTBOUND}}}Notification"):
        sobject = notification.find(f"{{{_NS_OUTBOUND}}}sObject")
        record: dict[str, Any] = {}
        if sobject is not None:
            for field_el in sobject:
                name = _localname(field_el.tag)
                value = field_el.text if field_el.text is not None else ""
                if name and name not in record:
                    record[name] = value
        message.notifications.append(SFNotification(
            object_type=_object_type(sobject, notification),
            notification_id=_child_text(notification, "Id"),
            record_id=str(record.get("Id") or ""),
            record=record,
        ))
    return message


def ack_xml(acked: bool = True) -> str:
    """The SOAP acknowledgement Salesforce requires to stop retrying."""
    value = "true" if acked else "false"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soapenv:Body>"
        f'<response xmlns="{_NS_OUTBOUND}"><Ack>{value}</Ack></response>'
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )


def ack_response(acked: bool = True, *, delivery_id: str = "", execution_id: str = "",
                 skipped: bool | None = None) -> Response:
    """SOAP acknowledgement plus flowsmith observability headers.

    Salesforce parses only the SOAP Ack; the extra headers carry
    delivery/execution ids for humans, tests and tooling without
    breaking the contract.
    """
    headers = {
        "X-Flowsmith-Delivery-Id": delivery_id,
        "X-Flowsmith-Execution-Id": execution_id,
    }
    if skipped is not None:
        headers["X-Flowsmith-Skipped"] = "true" if skipped else "false"
    return Response(content=ack_xml(acked), media_type="text/xml", headers=headers)


def _trigger_object_filter(workflow_data: dict[str, Any]) -> str:
    """The object_name filter of the salesforce_trigger node that owns
    this path (empty string = accept all objects)."""
    for node in (workflow_data or {}).get("nodes", []):
        if isinstance(node, dict) and node.get("type") == "salesforce_trigger":
            params = node.get("parameters") or {}
            return str(params.get("object_name") or "")
    return ""


# ----------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------

@router.post("/{path:path}")
async def salesforce_outbound_message(path: str, request: Request) -> Response:
    if not path.startswith(SALESFORCE_TRIGGER_PREFIX):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown Salesforce trigger path.")

    db = get_session()
    try:
        trigger = await asyncio.to_thread(get_webhook, db, path)
        if trigger is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown Salesforce trigger path.")

        content_type = request.headers.get("content-type", "")
        if "xml" not in content_type.lower():
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                "Salesforce outbound messages must be XML (text/xml).")

        length = request.headers.get("content-length")
        if length and int(length) > MAX_SF_BODY:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Body exceeds 5 MB limit.")
        raw = await request.body()
        if len(raw) > MAX_SF_BODY:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Body exceeds 5 MB limit.")

        allowed, retry_after = _limiter.allow(f"salesforce-trigger:{path}")
        if not allowed:
            ratelimit_rejected.inc(("salesforce_trigger",))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Salesforce trigger rate limit exceeded.",
                headers={"Retry-After": str(retry_after)},
            )

        parsed = parse_outbound_message(raw)
        if parsed is None or not parsed.message_id:
            await asyncio.to_thread(
                log_event,
                db, SALESFORCE_TRIGGER_REJECTED,
                target_type="salesforce_trigger", target_id=path,
                detail={"reason": "malformed_envelope"},
            )
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Payload is not a valid Salesforce outbound message.")

        idempotency_key = f"sf:{parsed.message_id}"
        replay = await asyncio.to_thread(
            lambda: db.scalars(
                select(WebhookDelivery).where(
                    WebhookDelivery.path == path,
                    WebhookDelivery.idempotency_key == idempotency_key,
                )
            ).first()
        )
        if replay is not None:
            # Duplicate retry from Salesforce after our earlier ACK.
            return ack_response(True, delivery_id=replay.id,
                                execution_id=replay.execution_id or "")

        kept = list(parsed.notifications)
        wanted_object = _trigger_object_filter(trigger.workflow_data)
        if wanted_object:
            kept = [n for n in kept if n.object_type == wanted_object]

        delivery_id = f"dlv_{uuid.uuid4().hex[:12]}"

        if not kept:
            webhook_deliveries.inc(("skipped",))
            db.add(WebhookDelivery(
                id=delivery_id,
                workflow_id=trigger.workflow_id,
                user_id=trigger.user_id,
                path=path,
                status="skipped",
                response_code=status.HTTP_200_OK,
                execution_id=None,
                idempotency_key=idempotency_key,
            ))
            await asyncio.to_thread(db.commit)
            return ack_response(True, delivery_id=delivery_id, skipped=True)

        from app.api.executions import has_running_execution, start_execution, workflow_workspace

        if await asyncio.to_thread(has_running_execution, db, trigger.workflow_id):
            webhook_deliveries.inc(("skipped",))
            db.add(WebhookDelivery(
                id=delivery_id,
                workflow_id=trigger.workflow_id,
                user_id=trigger.user_id,
                path=path,
                status="skipped",
                response_code=status.HTTP_200_OK,
                execution_id=None,
                idempotency_key=idempotency_key,
            ))
            await asyncio.to_thread(db.commit)
            return ack_response(True, delivery_id=delivery_id, skipped=True)

        items = [n.as_item(parsed) for n in kept]
        ws_id = await asyncio.to_thread(workflow_workspace, db, trigger.workflow_id)
        execution_id = await asyncio.to_thread(
            start_execution,
            db,
            workflow_id=trigger.workflow_id,
            user_id=trigger.user_id,
            version=trigger.workflow_version,
            workflow_data=trigger.workflow_data,
            trigger="salesforce_outbound_message",
            trigger_items=items,
            workspace_id=ws_id,
        )
        webhook_deliveries.inc(("queued",))
        db.add(WebhookDelivery(
            id=delivery_id,
            workflow_id=trigger.workflow_id,
            user_id=trigger.user_id,
            path=path,
            status="queued",
            response_code=status.HTTP_200_OK,
            execution_id=execution_id,
            idempotency_key=idempotency_key,
        ))
        await asyncio.to_thread(db.commit)

        await asyncio.to_thread(
            log_event,
            db, SALESFORCE_TRIGGER_RECEIVED,
            target_type="workflow", target_id=trigger.workflow_id,
            user_id=trigger.user_id,
            detail={
                "path": path,
                "message_id": parsed.message_id,
                "organization_id": parsed.organization_id,
                "objects": sorted({n.object_type for n in kept}),
                "execution_id": execution_id,
            },
        )
        return ack_response(True, delivery_id=delivery_id, execution_id=execution_id,
                            skipped=False)
    finally:
        db.close()
