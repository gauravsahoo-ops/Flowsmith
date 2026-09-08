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

TRIGGER_NODE_TYPES = {"webhook", "schedule", "salesforce_trigger"}

#: Reserved path namespace owned by the Salesforce Outbound Message
#: endpoint (Phase 10); generic webhook routes refuse it.
SALESFORCE_TRIGGER_PREFIX = "sf-outbound/"


def workflow_trigger_nodes(workflow: Workflow) -> list[dict[str, Any]]:
    """(node_id, node_type, params) for every trigger node in a workflow."""
    return [
        {"node_id": n.id, "type": n.type, "params": n.parameters}
        for n in workflow.nodes
        if n.type in TRIGGER_NODE_TYPES
    ]


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
                method = trig["params"].get("method", "POST")
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

            if trig["type"] == "schedule":
                # Multi-rule: params.rules is source of truth, fallback to legacy cron
                rules = trig["params"].get("rules")
                if not rules:
                    # Legacy single cron
                    cron = trig["params"].get("cron")
                    timezone = trig["params"].get("timezone", "UTC")
                    if cron:
                        rules = [{"id": "legacy", "cron": cron, "timezone": timezone, "interval": "cron"}]
                    else:
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
                        tz = r.get("timezone", "UTC")
                        normalized.append(TriggerRule(id=r.get("id", uuid.uuid4().hex[:8]), interval="cron", cron=cron, timezone=tz))
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
    # Multi-rule: one row per rule
    wanted_schedule_ids: set[str] = set()
    for rec in recs:
        for trig in workflow_trigger_nodes(Workflow.model_validate(rec.data)):
            if trig["type"] != "schedule":
                continue
            rules = trig["params"].get("rules")
            if not rules:
                cron = trig["params"].get("cron")
                if cron:
                    rules = [{"id": "legacy"}]
                else:
                    continue
            for r in rules:
                rule_id = r.get("id", "legacy")
                wanted_schedule_ids.add(f"sch_{rec.id}_{trig['node_id']}_{rule_id}")
    for row in db.scalars(select(ScheduleTrigger)).all():
        if row.id not in wanted_schedule_ids:
            db.delete(row)
    db.commit()


def get_webhook(db: Session, path: str) -> WebhookTrigger | None:
    return db.scalar(
        select(WebhookTrigger).where(WebhookTrigger.path == path, WebhookTrigger.status == "active")
    )
