"""Environment, API Key, and Workflow Template API endpoints."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.audit import log_event
from app.db import get_db
from app.environments import decrypt_env_value
from app.models import Environment, User, UserAPIKey, Workspace, WorkflowTemplate
from app.security.crypto import encrypt_text

router = APIRouter()

ENV_CREATED = "environment.created"
ENV_DELETED = "environment.deleted"
KEY_CREATED = "apikey.created"
KEY_REVOKED = "apikey.revoked"
TEMPLATE_CREATED = "template.created"
TEMPLATE_UPDATED = "template.updated"
TEMPLATE_DELETED = "template.deleted"


class EnvironmentCreate(BaseModel):
    workspace_id: str
    key: str
    value: str
    is_secret: bool = False


class EnvironmentBulkUpdate(BaseModel):
    workspace_id: str
    variables: list[dict[str, Any]]


class APIKeyCreate(BaseModel):
    name: str


class TemplateCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "general"
    workflow_data: dict
    is_public: bool = False


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    is_public: bool | None = None


# --- Environment CRUD ---

def _require_ws_exists(db: Session, ws_id: str) -> Workspace:
    ws = db.get(Workspace, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return ws


def _require_ws_read_access(db: Session, ws_id: str, user: User) -> None:
    """Tenant isolation (spec 28.1): only workspace/org members may read
    a workspace's environment variables (existence is hidden otherwise)."""
    from app.api.workspaces import _require_ws_member

    ws = db.get(Workspace, ws_id)
    if ws is None or not _require_ws_member(db, ws_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")


def _mask(value: str) -> str:
    return "***" + value[-4:] if len(value) > 4 else "***"


@router.get("/api/environments/{workspace_id}")
def list_env(workspace_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """List environment variables for a workspace.

    Secret values are masked; non-secret values decrypt at rest and are
    readable by workspace members (spec 12: secrets are never exposed).
    """
    _require_ws_exists(db, workspace_id)
    _require_ws_read_access(db, workspace_id, user)
    page, size = page_params(1, 100)
    stmt = select(Environment).where(Environment.workspace_id == workspace_id).order_by(Environment.key).limit(size)
    envs = db.execute(stmt).scalars().all()
    return ok([{
        "id": e.id,
        "key": e.key,
        "value": _mask(decrypt_env_value(e.value)) if e.is_secret else decrypt_env_value(e.value),
        "is_secret": e.is_secret,
        "created_at": str(e.created_at),
    } for e in envs])


@router.post("/api/environments")
def create_env(payload: EnvironmentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Create or update an environment variable."""
    ws = _require_ws_exists(db, payload.workspace_id)
    if ws.creator_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only workspace owner can manage environment.")

    # Encrypted at rest with the credential keyring (spec 29); values
    # decrypt only at execution time inside the worker.
    stored = encrypt_text(payload.value).decode()

    # Upsert: check if key already exists
    existing = db.execute(
        select(Environment).where(
            Environment.workspace_id == payload.workspace_id,
            Environment.key == payload.key,
        )
    ).scalar_one_or_none()

    if existing:
        existing.value = stored
        existing.is_secret = payload.is_secret
        env_id = existing.id
    else:
        env = Environment(
            workspace_id=payload.workspace_id,
            key=payload.key,
            value=stored,
            is_secret=payload.is_secret,
        )
        db.add(env)
        db.flush()
        env_id = env.id

    db.commit()
    log_event(db, ENV_CREATED, target_type="environment", target_id=str(env_id), user_id=user.id)
    return ok({"id": env_id, "key": payload.key})


@router.delete("/api/environments/{env_id}")
def delete_env(env_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Delete an environment variable."""
    env = db.get(Environment, env_id)
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    ws = db.get(Workspace, env.workspace_id)
    if ws is None or ws.creator_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only workspace owner can manage environment.")
    db.delete(env)
    db.commit()
    log_event(db, ENV_DELETED, target_type="environment", target_id=str(env_id), user_id=user.id)
    return ok({"deleted": True})


# --- API Keys ---

@router.get("/api/apikeys")
def list_apikeys(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """List user's API keys."""
    keys = db.execute(
        select(UserAPIKey).where(UserAPIKey.user_id == user.id, UserAPIKey.is_active == True)
    ).scalars().all()
    return ok([{
        "id": k.id,
        "name": k.name,
        "prefix": k.prefix,
        "last_used_at": str(k.last_used_at) if k.last_used_at else None,
        "expires_at": str(k.expires_at) if k.expires_at else None,
        "created_at": str(k.created_at),
    } for k in keys])


@router.post("/api/apikeys")
def create_apikey(payload: APIKeyCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Create a new API key. Returns the raw key once."""
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:12]
    key = UserAPIKey(
        user_id=user.id,
        name=payload.name,
        key_hash=key_hash,
        prefix=prefix,
    )
    db.add(key)
    db.commit()
    log_event(db, KEY_CREATED, target_type="apikey", target_id=str(key.id), user_id=user.id)
    return ok({"id": key.id, "key": raw_key, "prefix": prefix, "name": payload.name})


@router.delete("/api/apikeys/{key_id}")
def revoke_apikey(key_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Revoke (deactivate) an API key."""
    key = db.get(UserAPIKey, key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    key.is_active = False
    db.commit()
    log_event(db, KEY_REVOKED, target_type="apikey", target_id=str(key_id), user_id=user.id)
    return ok({"revoked": True})


# --- Workflow Templates ---

DEFAULT_TEMPLATES = [
    {
        "name": "Webhook to Slack & Teams Notification",
        "description": "Receive an incoming webhook payload, format the alert message, and dispatch to Slack or Microsoft Teams.",
        "category": "notifications",
        "workflow_data": {
            "name": "Webhook Notification Dispatcher",
            "nodes": [
                {"id": "trigger_1", "type": "webhook", "name": "Webhook Ingest", "position": {"x": 100, "y": 200}, "parameters": {"path": "alert-hook-1234567890abcdef1234", "http_method": "POST"}},
                {"id": "code_1", "type": "code", "name": "Format Alert", "position": {"x": 380, "y": 200}, "parameters": {"language": "javascript", "code": "const input = $json || {};\nreturn {\n  title: input.event || 'System Alert',\n  message: input.message || 'Notification triggered',\n  timestamp: new Date().toISOString()\n};"}},
                {"id": "http_1", "type": "http_request", "name": "Send Alert Webhook", "position": {"x": 660, "y": 200}, "parameters": {"url": "https://httpbin.org/post", "method": "POST", "send_body": True, "body": "{{ JSON.stringify($json) }}"}}
            ],
            "connections": [
                {"source": "trigger_1", "sourceHandle": "main", "target": "code_1", "targetHandle": "main"},
                {"source": "code_1", "sourceHandle": "main", "target": "http_1", "targetHandle": "main"}
            ]
        }
    },
    {
        "name": "Salesforce Lead Routing & AI Summary",
        "description": "Capture new business leads, generate an AI qualification summary, and record directly in Salesforce CRM.",
        "category": "salesforce",
        "workflow_data": {
            "name": "Salesforce Lead Routing & AI Summary",
            "nodes": [
                {"id": "webhook_1", "type": "webhook", "name": "Inbound Lead", "position": {"x": 100, "y": 200}, "parameters": {"path": "sales-lead-1234567890abcdef1234", "http_method": "POST"}},
                {"id": "ai_summary", "type": "ai", "name": "AI Lead Qualification", "position": {"x": 380, "y": 200}, "parameters": {"prompt": "Analyze lead interest and assign priority (High, Medium, Low): {{ JSON.stringify($json) }}"}},
                {"id": "sf_lead", "type": "salesforce", "name": "Upsert Salesforce Lead", "position": {"x": 660, "y": 200}, "parameters": {"resource": "Lead", "operation": "create"}}
            ],
            "connections": [
                {"source": "webhook_1", "sourceHandle": "main", "target": "ai_summary", "targetHandle": "main"},
                {"source": "ai_summary", "sourceHandle": "main", "target": "sf_lead", "targetHandle": "main"}
            ]
        }
    },
    {
        "name": "Stripe Payment Failure to Resend & Supabase",
        "description": "Listen for Stripe payment_intent.payment_failed webhooks, notify customer via Resend, and log to Supabase.",
        "category": "automation",
        "workflow_data": {
            "name": "Stripe Payment Recovery Pipeline",
            "nodes": [
                {"id": "stripe_hook", "type": "webhook", "name": "Stripe Event Webhook", "position": {"x": 100, "y": 200}, "parameters": {"path": "stripe-webhook-1234567890abcdef", "http_method": "POST"}},
                {"id": "resend_notify", "type": "resend", "name": "Send Dunning Email", "position": {"x": 380, "y": 140}, "parameters": {"operation": "send_email", "from": "billing@flowsmith.io", "subject": "Action Required: Payment Failed"}},
                {"id": "supabase_log", "type": "supabase", "name": "Log Audit in Supabase", "position": {"x": 380, "y": 280}, "parameters": {"operation": "insert_row", "table": "payment_failures"}}
            ],
            "connections": [
                {"source": "stripe_hook", "sourceHandle": "main", "target": "resend_notify", "targetHandle": "main"},
                {"source": "stripe_hook", "sourceHandle": "main", "target": "supabase_log", "targetHandle": "main"}
            ]
        }
    },
    {
        "name": "Sentry Error Triage to AI Root Cause & Jira",
        "description": "Trigger on Sentry error alerts, diagnose root cause with AI, and create a prioritized Jira bug ticket.",
        "category": "automation",
        "workflow_data": {
            "name": "Sentry Error Triage Pipeline",
            "nodes": [
                {"id": "sentry_hook", "type": "webhook", "name": "Sentry Alert Webhook", "position": {"x": 100, "y": 200}, "parameters": {"path": "sentry-alert-1234567890abcdef", "http_method": "POST"}},
                {"id": "ai_diagnose", "type": "ai", "name": "AI Root Cause Diagnosis", "position": {"x": 380, "y": 200}, "parameters": {"prompt": "Diagnose root cause and suggest fix for error: {{ JSON.stringify($json) }}"}},
                {"id": "jira_ticket", "type": "jira", "name": "Create Jira Bug", "position": {"x": 660, "y": 200}, "parameters": {"operation": "create_issue"}}
            ],
            "connections": [
                {"source": "sentry_hook", "sourceHandle": "main", "target": "ai_diagnose", "targetHandle": "main"},
                {"source": "ai_diagnose", "sourceHandle": "main", "target": "jira_ticket", "targetHandle": "main"}
            ]
        }
    },
    {
        "name": "Cloud Archival: Webhook to AWS S3 & Database",
        "description": "Ingest high-throughput JSON payloads, back up raw blobs to AWS S3 / MinIO, and insert structured rows into PostgreSQL.",
        "category": "automation",
        "workflow_data": {
            "name": "S3 & Database Archival",
            "nodes": [
                {"id": "ingest_hook", "type": "webhook", "name": "Raw Ingest Webhook", "position": {"x": 100, "y": 200}, "parameters": {"path": "raw-ingest-1234567890abcdef", "http_method": "POST"}},
                {"id": "s3_backup", "type": "s3", "name": "Store S3 Object", "position": {"x": 380, "y": 140}, "parameters": {"operation": "upload_file", "key": "backups/raw_{{ $now }}.json"}},
                {"id": "db_insert", "type": "database_query", "name": "Insert Database Row", "position": {"x": 380, "y": 280}, "parameters": {"operation": "insert"}}
            ],
            "connections": [
                {"source": "ingest_hook", "sourceHandle": "main", "target": "s3_backup", "targetHandle": "main"},
                {"source": "ingest_hook", "sourceHandle": "main", "target": "db_insert", "targetHandle": "main"}
            ]
        }
    },
    {
        "name": "AI Vector Search via Pinecone & Chat Model",
        "description": "Embed user queries, search nearest vectors in Pinecone index, and generate context-aware LLM answers.",
        "category": "ai",
        "workflow_data": {
            "name": "Pinecone RAG Search",
            "nodes": [
                {"id": "chat_in", "type": "chat_trigger", "name": "Chat Message Ingest", "position": {"x": 100, "y": 200}, "parameters": {}},
                {"id": "pinecone_query", "type": "pinecone", "name": "Query Vector Embeddings", "position": {"x": 380, "y": 200}, "parameters": {"operation": "query_vectors", "top_k": 5}},
                {"id": "ai_respond", "type": "ai", "name": "Synthesize AI Answer", "position": {"x": 660, "y": 200}, "parameters": {"prompt": "Answer question based on matched Pinecone context: {{ JSON.stringify($json) }}"}}
            ],
            "connections": [
                {"source": "chat_in", "sourceHandle": "main", "target": "pinecone_query", "targetHandle": "main"},
                {"source": "pinecone_query", "sourceHandle": "main", "target": "ai_respond", "targetHandle": "main"}
            ]
        }
    },
    {
        "name": "Daily Scheduled Sync & Data Table Report",
        "description": "Run on a scheduled cron timer, query external APIs or endpoints, and store aggregate records in a Data Table.",
        "category": "automation",
        "workflow_data": {
            "name": "Daily Scheduled Sync",
            "nodes": [
                {"id": "sched_1", "type": "schedule", "name": "Daily 9:00 AM", "position": {"x": 100, "y": 200}, "parameters": {"cron": "0 9 * * *"}},
                {"id": "code_metrics", "type": "code", "name": "Compute Aggregates", "position": {"x": 380, "y": 200}, "parameters": {"language": "javascript", "code": "return { report_date: new Date().toLocaleDateString(), status: 'healthy', active_workflows: 4 };"}},
                {"id": "dt_write", "type": "data_table", "name": "Store Report Row", "position": {"x": 660, "y": 200}, "parameters": {"operation": "insert_row"}}
            ],
            "connections": [
                {"source": "sched_1", "sourceHandle": "main", "target": "code_metrics", "targetHandle": "main"},
                {"source": "code_metrics", "sourceHandle": "main", "target": "dt_write", "targetHandle": "main"}
            ]
        }
    },
    {
        "name": "Human Approval Order Review",
        "description": "Safely pause execution before executing high-impact actions and resume automatically when reviewed by a team member.",
        "category": "approvals",
        "workflow_data": {
            "name": "Order Approval Pipeline",
            "nodes": [
                {"id": "manual_1", "type": "manual_trigger", "name": "Order Initiated", "position": {"x": 100, "y": 200}, "parameters": {}},
                {"id": "approval_node", "type": "human_approval", "name": "Manager Review", "position": {"x": 380, "y": 200}, "parameters": {"message": "Please review high-value invoice order before fulfillment."}},
                {"id": "http_fulfill", "type": "http_request", "name": "Fulfill Order", "position": {"x": 660, "y": 200}, "parameters": {"url": "https://httpbin.org/post", "method": "POST"}}
            ],
            "connections": [
                {"source": "manual_1", "sourceHandle": "main", "target": "approval_node", "targetHandle": "main"},
                {"source": "approval_node", "sourceHandle": "main", "target": "http_fulfill", "targetHandle": "main"}
            ]
        }
    }
]


def ensure_default_templates(db: Session, user_id: int) -> None:
    public_templates = db.execute(select(WorkflowTemplate).where(WorkflowTemplate.is_public == True)).scalars().all()
    if not public_templates:
        for t in DEFAULT_TEMPLATES:
            tmpl = WorkflowTemplate(
                name=t["name"],
                description=t["description"],
                category=t["category"],
                workflow_data=json.dumps(t["workflow_data"]),
                is_public=True,
                created_by=user_id,
            )
            db.add(tmpl)
        db.commit()
    else:
        # Sync all public default templates with updated definitions
        for pt in public_templates:
            for dt in DEFAULT_TEMPLATES:
                if dt["name"] == pt.name:
                    pt.workflow_data = json.dumps(dt["workflow_data"])
                    break
        db.commit()


@router.get("/api/templates")
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """List public templates and user's own templates."""
    ensure_default_templates(db, user.id)
    page, size = page_params(1, 50)
    stmt = select(WorkflowTemplate).where(
        (WorkflowTemplate.is_public == True) | (WorkflowTemplate.created_by == user.id)
    ).order_by(WorkflowTemplate.use_count.desc()).offset((page - 1) * size).limit(size)
    templates = db.execute(stmt).scalars().all()
    return ok([{
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "category": t.category,
        "is_public": t.is_public,
        "use_count": t.use_count,
        "is_mine": t.created_by == user.id,
        "created_at": str(t.created_at),
    } for t in templates])


@router.delete("/api/templates/{template_id}")
def delete_template(template_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Delete a template (creator only)."""
    tmpl = db.get(WorkflowTemplate, template_id)
    if tmpl is None or tmpl.created_by != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    db.delete(tmpl)
    db.commit()
    log_event(db, TEMPLATE_DELETED, target_type="template", target_id=str(template_id), user_id=user.id)
    return ok({"deleted": True})


@router.patch("/api/templates/{template_id}")
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Update template metadata (creator only)."""
    tmpl = db.get(WorkflowTemplate, template_id)
    if tmpl is None or tmpl.created_by != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    if payload.name is not None:
        tmpl.name = payload.name
    if payload.description is not None:
        tmpl.description = payload.description
    if payload.category is not None:
        tmpl.category = payload.category
    if payload.is_public is not None:
        tmpl.is_public = payload.is_public
    db.commit()
    log_event(db, TEMPLATE_UPDATED, target_type="template", target_id=str(template_id), user_id=user.id)
    return ok({"id": tmpl.id, "name": tmpl.name})


@router.post("/api/templates")
def create_template(payload: TemplateCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Create a workflow template."""
    tmpl = WorkflowTemplate(
        name=payload.name,
        description=payload.description,
        category=payload.category,
        workflow_data=json.dumps(payload.workflow_data),
        is_public=payload.is_public,
        created_by=user.id,
    )
    db.add(tmpl)
    db.commit()
    log_event(db, TEMPLATE_CREATED, target_type="template", target_id=str(tmpl.id), user_id=user.id)
    return ok({"id": tmpl.id, "name": tmpl.name})


@router.post("/api/templates/{template_id}/use")
def use_template(template_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Get template data and increment use count."""
    tmpl = db.get(WorkflowTemplate, template_id)
    if tmpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    if not tmpl.is_public and tmpl.created_by != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
    tmpl.use_count += 1
    db.commit()
    raw = tmpl.workflow_data
    data = json.loads(raw if isinstance(raw, str) else json.dumps(raw))
    if isinstance(data, dict) and isinstance(data.get("connections"), dict):
        conns = []
        for src, handles in data["connections"].items():
            for hname, out_lists in (handles or {}).items():
                if isinstance(out_lists, list):
                    for out_list in out_lists or []:
                        if isinstance(out_list, list):
                            for item in out_list or []:
                                if isinstance(item, dict) and "node" in item:
                                    conns.append({
                                        "source": str(src),
                                        "sourceHandle": str(hname),
                                        "target": str(item["node"]),
                                        "targetHandle": str(item.get("type", "main")),
                                    })
        data["connections"] = conns
    if isinstance(data, dict):
        import re
        import uuid
        for node in data.get("nodes", []):
            if node.get("type") in ("webhook", "salesforce_trigger"):
                params = node.setdefault("parameters", {})
                curr = str(params.get("path") or "hook")
                prefix = re.sub(r"[^A-Za-z0-9_.-]", "", curr)[:12] or "hook"
                params["path"] = f"{prefix}-{uuid.uuid4().hex[:18]}"

    return ok({
        "id": tmpl.id,
        "name": tmpl.name,
        "workflow_data": data,
    })
