"""Seed the built-in template library (Phase 36).

Idempotent: templates are matched by name; existing rows are updated
(workflow_data/description/category) so the library stays fresh without
duplicating. Run after deployments or on demand:

    python scripts/seed_templates.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db import init_db  # noqa: E402
from app.models import User, WorkflowTemplate  # noqa: E402


def _wf(nodes: list[dict], connections: list[dict]) -> dict:
    return {"nodes": nodes, "connections": connections, "settings": {}}


LIBRARY: list[dict] = [
    {
        "name": "Salesforce Lead Sync",
        "description": "Find a Lead by email and update it, or create it when missing.",
        "category": "salesforce",
        "is_public": True,
        "workflow_data": _wf(
            [
                {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                {"id": "find", "type": "salesforce", "credentials": {"salesforce": "{{SF_CREDENTIAL_ID}}"},
                 "parameters": {"operation": "search", "object_name": "Lead",
                                "search_field": "Email", "search_value": "{{ $json.email }}"}},
                {"id": "gate", "type": "if_condition",
                 "parameters": {"field": "{{ $node.find.json.found }}", "operator": "equals", "value": "True"}},
                {"id": "update", "type": "salesforce", "credentials": {"salesforce": "{{SF_CREDENTIAL_ID}}"},
                 "parameters": {"operation": "update", "object_name": "Lead",
                                "record_id": "{{ $node.find.json.record.Id }}",
                                "record": {"Company": "{{ $json.company }}"}}},
                {"id": "create", "type": "salesforce", "credentials": {"salesforce": "{{SF_CREDENTIAL_ID}}"},
                 "parameters": {"operation": "create", "object_name": "Lead",
                                "record": {"LastName": "{{ $json.last_name }}", "Email": "{{ $json.email }}",
                                           "Company": "{{ $json.company }}"}}},
            ],
            [
                {"source": "trigger", "target": "find"},
                {"source": "find", "target": "gate"},
                {"source": "gate", "target": "update", "sourceHandle": "true"},
                {"source": "gate", "target": "create", "sourceHandle": "false"},
            ],
        ),
    },
    {
        "name": "HubSpot Contact Upsert",
        "description": "Search a HubSpot contact by email; update it when found, create it otherwise.",
        "category": "hubspot",
        "is_public": True,
        "workflow_data": _wf(
            [
                {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                {"id": "find", "type": "hubspot", "credentials": {"hubspot": "{{HS_CREDENTIAL_ID}}"},
                 "parameters": {"operation": "search", "object_type": "contacts",
                                "search_field": "email", "search_value": "{{ $json.email }}"}},
                {"id": "gate", "type": "if_condition",
                 "parameters": {"field": "{{ $node.find.json.found }}", "operator": "equals", "value": "True"}},
                {"id": "update", "type": "hubspot", "credentials": {"hubspot": "{{HS_CREDENTIAL_ID}}"},
                 "parameters": {"operation": "update", "object_type": "contacts",
                                "record_id": "{{ $node.find.json.record.id }}",
                                "properties": {"firstname": "{{ $json.first_name }}"}}},
                {"id": "create", "type": "hubspot", "credentials": {"hubspot": "{{HS_CREDENTIAL_ID}}"},
                 "parameters": {"operation": "create", "object_type": "contacts",
                                "properties": {"email": "{{ $json.email }}",
                                               "firstname": "{{ $json.first_name }}"}}},
            ],
            [
                {"source": "trigger", "target": "find"},
                {"source": "find", "target": "gate"},
                {"source": "gate", "target": "update", "sourceHandle": "true"},
                {"source": "gate", "target": "create", "sourceHandle": "false"},
            ],
        ),
    },
    {
        "name": "Human Approval Gate",
        "description": "Pause for a human decision before an HTTP call; rejection fails the run.",
        "category": "logic",
        "is_public": True,
        "workflow_data": _wf(
            [
                {"id": "trigger", "type": "manual_trigger", "parameters": {}},
                {"id": "approval", "type": "human_approval",
                 "parameters": {"message": "Ship this change?", "timeout_hours": 48}},
                {"id": "notify", "type": "http_request",
                 "parameters": {"method": "POST", "url": "{{ $env.WEBHOOK_URL }}",
                                "headers": {"Authorization": "Bearer {{ $env.API_TOKEN }}"},
                                "body": {"approved_by": "human"}}},
            ],
            [
                {"source": "trigger", "target": "approval"},
                {"source": "approval", "target": "notify"},
            ],
        ),
    },
    {
        "name": "Webhook -> Enrich -> Respond",
        "description": "Receive a webhook, enrich via HTTP API, branch on the result.",
        "category": "http",
        "is_public": True,
        "workflow_data": _wf(
            [
                {"id": "hook", "type": "webhook", "parameters": {"path": "enrich"}},
                {"id": "enrich", "type": "http_request",
                 "parameters": {"method": "GET", "url": "{{ $env.API_URL }}?q={{ $json.query }}",
                                "headers": {"X-API-Key": "{{ $cred.http.api_key }}"},
                                "credential_types": ["http"]}},
                {"id": "route", "type": "if_condition",
                 "parameters": {"field": "{{ $node.enrich.json.status }}", "operator": "equals", "value": "ok"}},
                {"id": "ok", "type": "set_data", "parameters": {"fields": {"result": "enriched"}}},
                {"id": "fallback", "type": "set_data", "parameters": {"fields": {"result": "unavailable"}}},
            ],
            [
                {"source": "hook", "target": "enrich"},
                {"source": "enrich", "target": "route"},
                {"source": "route", "target": "ok", "sourceHandle": "true"},
                {"source": "route", "target": "fallback", "sourceHandle": "false"},
            ],
        ),
    },
    {
        "name": "AI Weekly Digest",
        "description": "Fetch data over HTTP, summarize with an LLM, email the digest.",
        "category": "ai",
        "is_public": True,
        "workflow_data": _wf(
            [
                {"id": "schedule", "type": "schedule", "parameters": {"cron": "0 9 * * 1", "timezone": "UTC"}},
                {"id": "fetch", "type": "http_request",
                 "parameters": {"method": "GET", "url": "{{ $env.SOURCE_URL }}"}},
                {"id": "summarize", "type": "ai", "credentials": {"llm": "{{LLM_CREDENTIAL_ID}}"},
                 "parameters": {"prompt": "Summarize this data in 5 bullets:\n{{ $node.fetch.json | json }}"}},
                {"id": "send", "type": "send_email", "credentials": {"smtp": "{{SMTP_CREDENTIAL_ID}}"},
                 "parameters": {"to": "{{ $env.DIGEST_TO }}", "subject": "Weekly digest",
                                "body": "{{ $node.summarize.json.text }}"}},
            ],
            [
                {"source": "schedule", "target": "fetch"},
                {"source": "fetch", "target": "summarize"},
                {"source": "summarize", "target": "send"},
            ],
        ),
    },
]


def _system_user_id(db) -> int:
    """Owner for seeded templates: first admin, else a dedicated system user."""
    admin = db.query(User).filter_by(role="admin").order_by(User.id).first()
    if admin is not None:
        return admin.id
    from app.models import User as UserModel

    system = db.query(UserModel).filter_by(email="system@flowsmith.dev").first()
    if system is not None:
        return system.id
    from app.security.jwt import hash_password

    system = UserModel(
        email="system@flowsmith.dev",
        password_hash=hash_password("system-owned-template-library"),
        role="member",
        active=True,
    )
    db.add(system)
    db.commit()
    db.refresh(system)
    return system.id


def main() -> int:
    from app.config import get_settings

    init_db(get_settings().database_url)
    from app.db import get_session

    db = get_session()
    created = updated = 0
    try:
        owner_id = _system_user_id(db)
        for spec in LIBRARY:
            row = (
                db.query(WorkflowTemplate)
                .filter(WorkflowTemplate.name == spec["name"])
                .one_or_none()
            )
            if row is None:
                row = WorkflowTemplate(name=spec["name"], created_by=owner_id)
                created += 1
            else:
                updated += 1
            row.description = spec["description"]
            row.category = spec["category"]
            row.is_public = spec["is_public"]
            row.workflow_data = json.dumps(spec["workflow_data"])
            db.add(row)
        db.commit()
        print(f"templates seeded: {created} created, {updated} updated")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
