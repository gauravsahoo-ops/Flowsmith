"""Trigger registry (spec 32/33).

Reconciles the `webhooks` and `schedule_triggers` tables with the
currently active workflows: every active workflow that contains webhook
or schedule nodes gets a trigger row with a snapshot of the workflow
JSON and version (the version that was active when the sync ran);
stale rows are deleted. The scheduler and webhook endpoint read
exclusively from these tables, so "activate" semantics are exact.

Called on app startup and after any workflow save / delete / active
toggle.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import PollingTrigger, ScheduleTrigger, WebhookTrigger, WorkflowRecord
from app.schemas.workflow import Workflow


def make_schedule_trigger_id(wf_id: str, node_id: str, rule_id: str) -> str:
    """Produce deterministic schedule_triggers.id capped at 64 characters."""
    raw = f"sch_{wf_id}_{node_id}_{rule_id}"
    if len(raw) <= 64:
        return raw
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{raw[:40]}_{h}"[:64]


def make_polling_trigger_id(wf_id: str, node_id: str) -> str:
    raw = f"poll_{wf_id}_{node_id}"
    if len(raw) <= 64:
        return raw
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{raw[:40]}_{h}"[:64]

logger = logging.getLogger("triggers.registry")


def _owned_by_other_active_workflow(
    db: Session, existing: WebhookTrigger | None, workflow_id: str, path: str
) -> bool:
    """True when an existing row is still legitimately claimed by its owner.

    Path validation should prevent this state, but startup reconciliation and
    legacy rows can still collide.  Never silently reassign a live path based
    only on loop order; that turns a collision into a callback hijack.
    """
    if existing is None or existing.workflow_id == workflow_id:
        return False
    owner = db.get(WorkflowRecord, existing.workflow_id)
    if owner is None or not owner.active or owner.deleted_at is not None:
        return False
    try:
        owner_workflow = Workflow.model_validate(owner.data)
    except Exception:
        return True
    return any(
        str(trigger["params"].get("path") or "") == path
        for trigger in workflow_trigger_nodes(owner_workflow)
    )


WEBHOOK_TRIGGER_TYPES = {
    "webhook",
    "github_trigger",
    "stripe_trigger",
    "shopify_trigger",
    "slack_trigger",
    "typeform_trigger",
    "gitlab_trigger",
}
POLL_TRIGGER_TYPES = {"http_poll_trigger"}
TRIGGER_NODE_TYPES = {
    "schedule",
    "salesforce_trigger",
    "form_trigger",
    "chat_trigger",
} | WEBHOOK_TRIGGER_TYPES | POLL_TRIGGER_TYPES

#: Reserved path namespace owned by the Salesforce Outbound Message
#: endpoint (Phase 10); generic webhook routes refuse it.
SALESFORCE_TRIGGER_PREFIX = "sf-outbound/"

#: Reserved path namespace for public forms (Batch D). Form submissions
#: share the `webhooks` table; the generic single-segment webhook route
#: never matches these two-segment paths.
FORM_TRIGGER_PREFIX = "form/"

#: Reserved path namespace for public chat (Batch D). Same table,
#: same two-segment routing as forms.
CHAT_TRIGGER_PREFIX = "chat/"


def workflow_trigger_nodes(workflow: Workflow) -> list[dict[str, Any]]:
    """(node_id, node_type, params) for every trigger node in a workflow."""
    return [
        {"node_id": n.id, "type": n.type, "params": n.parameters}
        for n in workflow.nodes
        if n.type in TRIGGER_NODE_TYPES
    ]


def schedule_rule_dicts(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a schedule node's params into a list of rule dicts.

    Every shape the codebase can produce is accepted (audit H16):

    - canonical ``rules`` list (registry/UI source of truth),
    - legacy single ``cron`` + ``timezone`` pair,
    - AI compiler/copilot shape ``rule.cronExpression`` (+ ``rule.timezone``).

    Rule ids are preserved when present and otherwise derived from the
    rule's position, so both sync passes compute the same row ids — a
    mismatch would delete and recreate the row on every save, resetting
    ``last_fired_at`` (and, for id-less rules, meant the schedule was
    never registered at all).
    """
    rules = params.get("rules")
    if isinstance(rules, list) and rules:
        out: list[dict[str, Any]] = []
        for idx, r in enumerate(rules):
            d = dict(r) if isinstance(r, dict) else {}
            if not str(d.get("id") or "").strip():
                d["id"] = f"rule{idx}"
            out.append(d)
        return out
    raw_nested = params.get("rule")
    nested = raw_nested if isinstance(raw_nested, dict) else {}
    timezone = params.get("timezone") or nested.get("timezone") or "UTC"
    cron = params.get("cron") or nested.get("cronExpression") or nested.get("cron")
    if isinstance(cron, str) and cron.strip():
        return [{"id": "legacy", "interval": "cron", "cron": cron.strip(), "timezone": timezone}]
    return []


def sync_webhooks(db: Session) -> None:
    """Reconcile webhook + schedule rows with active workflows."""
    recs = db.scalars(
        select(WorkflowRecord).where(
            WorkflowRecord.active.is_(True),
            WorkflowRecord.deleted_at.is_(None),
        )
    ).all()

    wanted_webhook_paths: set[str] = set()
    wanted_schedule_ids: set[str] = set()
    wanted_polling_ids: set[str] = set()
    for rec in recs:
        # One malformed/legacy workflow must not make every save, delete, or
        # activation request fail trigger reconciliation for all workflows.
        try:
            workflow = Workflow.model_validate(rec.data)
        except Exception as exc:
            logger.error(
                "skipping invalid workflow data during trigger sync workflow=%s: %s",
                rec.id,
                exc,
            )
            continue
        for trig in workflow_trigger_nodes(workflow):
            if trig["type"] in WEBHOOK_TRIGGER_TYPES:
                path = trig["params"].get("path")
                # The AI compiler writes `http_method`; canonical is `method`
                # (webhook node schema). Register whichever is present so a
                # GET webhook is not silently registered as POST (audit H16).
                # Upper-cased: the route compares against the upper-case
                # ASGI request method.
                method = str(
                    trig["params"].get("method") or trig["params"].get("http_method") or "POST"
                ).upper()
                if not path or path.startswith(SALESFORCE_TRIGGER_PREFIX):
                    # Reserved for the Salesforce Outbound Message endpoint.
                    continue
                wanted_webhook_paths.add(path)
                existing = db.scalar(
                    select(WebhookTrigger).where(WebhookTrigger.path == path)
                )
                if _owned_by_other_active_workflow(db, existing, rec.id, path):
                    logger.error(
                        "webhook path collision preserved owner workflow=%s claimant=%s path=%s",
                        existing.workflow_id if existing else "?", rec.id, path,
                    )
                    continue
                if existing is None:
                    db.add(WebhookTrigger(
                        id=f"whk_{uuid.uuid4().hex[:12]}",
                        workflow_id=rec.id,
                        user_id=rec.user_id,
                        workflow_version=rec.version,
                        workflow_data=rec.data,
                        path=path,
                        method=method,
                        status="active",
                    ))
                else:
                    existing.workflow_id = rec.id
                    existing.user_id = rec.user_id
                    existing.workflow_version = rec.version
                    existing.workflow_data = rec.data
                    existing.method = method
                    existing.status = "active"

            if trig["type"] == "salesforce_trigger":
                path = trig["params"].get("path")
                if not path or not path.startswith(SALESFORCE_TRIGGER_PREFIX):
                    continue
                wanted_webhook_paths.add(path)
                existing = db.scalar(
                    select(WebhookTrigger).where(WebhookTrigger.path == path)
                )
                if _owned_by_other_active_workflow(db, existing, rec.id, path):
                    logger.error(
                        "Salesforce path collision preserved owner workflow=%s claimant=%s path=%s",
                        existing.workflow_id if existing else "?", rec.id, path,
                    )
                    continue
                if existing is None:
                    db.add(WebhookTrigger(
                        id=f"whk_{uuid.uuid4().hex[:12]}",
                        workflow_id=rec.id,
                        user_id=rec.user_id,
                        workflow_version=rec.version,
                        workflow_data=rec.data,
                        path=path,
                        method="POST",
                        status="active",
                    ))
                else:
                    existing.workflow_id = rec.id
                    existing.user_id = rec.user_id
                    existing.workflow_version = rec.version
                    existing.workflow_data = rec.data
                    existing.method = "POST"
                    existing.status = "active"

            if trig["type"] in ("form_trigger", "chat_trigger"):
                prefix = FORM_TRIGGER_PREFIX if trig["type"] == "form_trigger" else CHAT_TRIGGER_PREFIX
                path = trig["params"].get("path")
                if not path or not path.startswith(prefix):
                    continue
                wanted_webhook_paths.add(path)
                existing = db.scalar(
                    select(WebhookTrigger).where(WebhookTrigger.path == path)
                )
                if _owned_by_other_active_workflow(db, existing, rec.id, path):
                    logger.error(
                        "public trigger path collision preserved owner workflow=%s claimant=%s path=%s",
                        existing.workflow_id if existing else "?", rec.id, path,
                    )
                    continue
                if existing is None:
                    db.add(WebhookTrigger(
                        id=f"whk_{uuid.uuid4().hex[:12]}",
                        workflow_id=rec.id,
                        user_id=rec.user_id,
                        workflow_version=rec.version,
                        workflow_data=rec.data,
                        path=path,
                        method="POST",
                        status="active",
                    ))
                else:
                    existing.workflow_id = rec.id
                    existing.user_id = rec.user_id
                    existing.workflow_version = rec.version
                    existing.workflow_data = rec.data
                    existing.method = "POST"
                    existing.status = "active"

            if trig["type"] == "schedule":
                # Multi-rule: params.rules is source of truth, with fallbacks
                # to legacy cron and the AI shape rule.cronExpression (H16).
                rules = schedule_rule_dicts(trig["params"])
                if not rules:
                    tz = trig["params"].get("timezone") or "UTC"
                    rules = [{"id": "default", "interval": "minutes", "value": 5, "timezone": tz}]
                # Normalize each rule to cron/timezone via TriggerRule.to_cron()
                from app.nodes.schedule import TriggerRule
                normalized = []
                for idx, r in enumerate(rules):
                    try:
                        tr = TriggerRule.model_validate(r)
                        normalized.append(tr)
                    except Exception:
                        # Fallback: treat as cron
                        val = r.get("value")
                        cron_str = str(r.get("cron") or (f"*/{val} * * * *" if val else "*/5 * * * *"))
                        tz_str = str(r.get("timezone") or "UTC")
                        rule_id_str = str(r.get("id") or f"rule{idx}")
                        normalized.append(TriggerRule(id=rule_id_str, interval="cron", cron=cron_str, timezone=tz_str))
                for rule in normalized:
                    cron = rule.to_cron()
                    timezone = rule.timezone
                    rule_id = rule.id
                    # One DB row per rule
                    row_id = make_schedule_trigger_id(rec.id, trig["node_id"], rule_id)
                    wanted_schedule_ids.add(row_id)
                    existing = db.scalar(select(ScheduleTrigger).where(ScheduleTrigger.id == row_id))
                    if existing is None:
                        db.add(ScheduleTrigger(
                            id=row_id,
                            workflow_id=rec.id,
                            user_id=rec.user_id,
                            workflow_version=rec.version,
                            workflow_data=rec.data,
                            node_id=trig["node_id"],
                            cron=cron,
                            timezone=timezone,
                            status="active",
                            interval_type=rule.interval,
                            interval_value=rule.value,
                        ))
                        logger.info(
                            "registered schedule trigger row=%s workflow=%s node=%s cron=%s tz=%s interval=%s value=%s",
                            row_id, rec.id, trig["node_id"], cron, timezone, rule.interval, rule.value,
                        )
                    else:
                        existing.workflow_version = rec.version
                        existing.workflow_data = rec.data
                        existing.cron = cron
                        existing.timezone = timezone
                        existing.status = "active"
                        existing.interval_type = rule.interval
                        existing.interval_value = rule.value
                        logger.info(
                            "updated schedule trigger row=%s cron=%s tz=%s",
                            row_id, cron, timezone,
                        )

            if trig["type"] == "http_poll_trigger":
                from app.nodes.http_poll_trigger import HttpPollTriggerParams

                try:
                    params = HttpPollTriggerParams.model_validate(trig["params"])
                except Exception:
                    logger.warning(
                        "skipping invalid polling trigger workflow=%s node=%s",
                        rec.id, trig["node_id"],
                    )
                    continue
                row_id = make_polling_trigger_id(rec.id, trig["node_id"])
                wanted_polling_ids.add(row_id)
                existing = db.scalar(
                    select(PollingTrigger).where(PollingTrigger.id == row_id)
                )
                if existing is None:
                    db.add(PollingTrigger(
                        id=row_id,
                        workflow_id=rec.id,
                        user_id=rec.user_id,
                        workflow_version=rec.version,
                        workflow_data=rec.data,
                        node_id=trig["node_id"],
                        url=params.url,
                        method=params.method,
                        headers=params.headers,
                        json_body=params.json_body,
                        items_path=params.items_path,
                        dedupe_field=params.dedupe_field,
                        interval_seconds=params.interval_seconds,
                        status="active",
                        next_poll_at=datetime.now(UTC) + timedelta(seconds=params.interval_seconds),
                        seen_keys=[],
                    ))
                else:
                    existing.workflow_version = rec.version
                    existing.workflow_data = rec.data
                    existing.url = params.url
                    existing.method = params.method
                    existing.headers = params.headers
                    existing.json_body = params.json_body
                    existing.items_path = params.items_path
                    existing.dedupe_field = params.dedupe_field
                    existing.interval_seconds = params.interval_seconds
                    existing.status = "active"

    # Drop trigger rows whose workflow is no longer active / no longer
    # defines the same trigger (webhooks: by path; schedules: per node;
    # polling: per workflow/node).
    db.execute(
        delete(WebhookTrigger).where(~WebhookTrigger.path.in_(wanted_webhook_paths))
        if wanted_webhook_paths
        else delete(WebhookTrigger)
    )
    db.execute(
        delete(ScheduleTrigger).where(~ScheduleTrigger.id.in_(wanted_schedule_ids))
        if wanted_schedule_ids
        else delete(ScheduleTrigger)
    )
    db.execute(
        delete(PollingTrigger).where(~PollingTrigger.id.in_(wanted_polling_ids))
        if wanted_polling_ids
        else delete(PollingTrigger)
    )
    db.commit()


def get_webhook(db: Session, path: str) -> WebhookTrigger | None:
    return db.scalar(
        select(WebhookTrigger).where(WebhookTrigger.path == path, WebhookTrigger.status == "active")
    )
