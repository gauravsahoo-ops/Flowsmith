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

import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import ScheduleTrigger, WebhookTrigger, WorkflowRecord
from app.schemas.workflow import Workflow

logger = logging.getLogger("triggers.registry")

TRIGGER_NODE_TYPES = {"webhook", "schedule", "salesforce_trigger", "form_trigger", "chat_trigger"}

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
        select(WorkflowRecord).where(WorkflowRecord.active.is_(True))
    ).all()

    wanted_webhook_paths: set[str] = set()
    for rec in recs:
        workflow = Workflow.model_validate(rec.data)
        for trig in workflow_trigger_nodes(workflow):
            if trig["type"] == "webhook":
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
                    continue
                # Normalize each rule to cron/timezone via TriggerRule.to_cron()
                from app.nodes.schedule import TriggerRule
                normalized = []
                for r in rules:
                    try:
                        tr = TriggerRule.model_validate(r)
                        normalized.append(tr)
                    except Exception:
                        # Fallback: treat as cron
                        cron = r.get("cron") or r.get("value") and f"*/{r.get('value')} * * * *" or "*/5 * * * *"
                        tz = r.get("timezone") or "UTC"
                        normalized.append(TriggerRule(id=r.get("id") or uuid.uuid4().hex[:8], interval="cron", cron=cron, timezone=tz))
                for rule in normalized:
                    cron = rule.to_cron()
                    timezone = rule.timezone
                    rule_id = rule.id
                    # One DB row per rule
                    row_id = f"sch_{rec.id}_{trig['node_id']}_{rule_id}"
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

    # Drop trigger rows whose workflow is no longer active / no longer
    # defines the same trigger (webhooks: by path; schedules: per node).
    db.execute(
        delete(WebhookTrigger).where(~WebhookTrigger.path.in_(wanted_webhook_paths))
        if wanted_webhook_paths
        else delete(WebhookTrigger)
    )
    # Multi-rule: one row per rule (ids from the SAME normalization as the
    # create/update pass above, so both passes agree on the row id — audit H16)
    wanted_schedule_ids: set[str] = set()
    for rec in recs:
        for trig in workflow_trigger_nodes(Workflow.model_validate(rec.data)):
            if trig["type"] != "schedule":
                continue
            for r in schedule_rule_dicts(trig["params"]):
                rule_id = str(r.get("id") or "legacy")
                wanted_schedule_ids.add(f"sch_{rec.id}_{trig['node_id']}_{rule_id}")
    for row in db.scalars(select(ScheduleTrigger)).all():
        if row.id not in wanted_schedule_ids:
            db.delete(row)
    db.commit()


def get_webhook(db: Session, path: str) -> WebhookTrigger | None:
    return db.scalar(
        select(WebhookTrigger).where(WebhookTrigger.path == path, WebhookTrigger.status == "active")
    )
