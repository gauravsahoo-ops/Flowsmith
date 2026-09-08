"""MCP (Model Context Protocol) server for AI agent integration.

Exposes workflow operations as MCP tools so AI agents can
discover, trigger, and monitor automations.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.auth import get_current_user
from app.api.common import ok
from app.db import get_db
from app.models import Execution, User, WorkflowRecord
from app.api.access import accessible_ids, get_permission, PERMISSION_VIEW
from app.utils.backup import create_backup, list_backups, restore_backup

logger = logging.getLogger(__name__)

router = APIRouter()


class MCPToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = {}


class MCPTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


# --- MCP Tool Definitions ---

MCP_TOOLS: list[MCPTool] = [
    MCPTool(
        name="list_workflows",
        description="List all available workflows in the workspace",
        input_schema={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID to filter by"},
            },
        },
    ),
    MCPTool(
        name="get_workflow",
        description="Get details of a specific workflow",
        input_schema={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow ID"},
            },
            "required": ["workflow_id"],
        },
    ),
    MCPTool(
        name="trigger_workflow",
        description="Trigger a workflow execution",
        input_schema={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow ID to trigger"},
                "input_data": {"type": "object", "description": "Input data for the trigger"},
            },
            "required": ["workflow_id"],
        },
    ),
    MCPTool(
        name="get_execution",
        description="Get status and result of a specific execution",
        input_schema={
            "type": "object",
            "properties": {
                "execution_id": {"type": "string", "description": "Execution ID"},
            },
            "required": ["execution_id"],
        },
    ),
    MCPTool(
        name="list_executions",
        description="List recent executions for a workflow",
        input_schema={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow ID to filter by"},
                "status": {"type": "string", "description": "Filter by status (running, completed, failed)"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
        },
    ),
    MCPTool(
        name="create_backup",
        description="Create a database backup",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Optional backup name"},
            },
        },
    ),
    MCPTool(
        name="list_backups",
        description="List available database backups",
        input_schema={"type": "object", "properties": {}},
    ),
    MCPTool(
        name="set_workflow_active",
        description="Arm (activate) or disarm a workflow's triggers",
        input_schema={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow ID"},
                "active": {"type": "boolean", "description": "true to arm, false to disarm"},
            },
            "required": ["workflow_id", "active"],
        },
    ),
    MCPTool(
        name="use_template",
        description="Create a new workflow from a template in the library",
        input_schema={
            "type": "object",
            "properties": {
                "template_id": {"type": "integer", "description": "Template ID"},
                "new_id": {"type": "string", "description": "Optional id for the new workflow"},
            },
            "required": ["template_id"],
        },
    ),
]


# --- MCP Resources & Prompts (Phase 42-lite) ---

@router.get("/api/mcp/resources")
def list_mcp_resources(user: User = Depends(get_current_user), db=Depends(get_db)) -> dict:
    """Workflows exposed as MCP resources (uri: workflow://{id})."""
    from sqlalchemy import select

    ids = accessible_ids(db, user)
    if not ids:
        return ok([])
    stmt = (
        select(WorkflowRecord)
        .where(WorkflowRecord.id.in_(ids), WorkflowRecord.deleted_at.is_(None))
        .order_by(WorkflowRecord.updated_at.desc())
        .limit(50)
    )
    wfs = db.execute(stmt).scalars().all()
    return ok([{
        "uri": f"workflow://{w.id}",
        "name": w.name,
        "description": w.description or "",
        "mimeType": "application/json",
    } for w in wfs])


@router.get("/api/mcp/resources/workflow/{workflow_id}")
def read_mcp_resource(workflow_id: str, user: User = Depends(get_current_user), db=Depends(get_db)) -> dict:
    perm = get_permission(db, workflow_id, user)
    if perm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found.")
    wf = db.get(WorkflowRecord, workflow_id)
    return ok({
        "uri": f"workflow://{wf.id}",
        "name": wf.name,
        "mimeType": "application/json",
        "text": json.dumps(wf.data),
    })


MCP_PROMPTS: list[dict[str, Any]] = [
    {
        "name": "summarize-execution",
        "description": "Human-readable summary of a workflow execution for an operator.",
        "arguments": [{"name": "execution", "description": "Execution id", "required": True}],
        "messages": [{
            "role": "user",
            "content": (
                "Summarize workflow execution {execution} for an on-call operator: "
                "final status, failing node (if any) with its error code, total duration, "
                "and the single most useful next action. Be concise."
            ),
        }],
    },
    {
        "name": "draft-lead-sync",
        "description": "Draft the Salesforce Lead sync workflow (search → branch → upsert).",
        "arguments": [
            {"name": "object", "description": "Salesforce object (default Lead)", "required": False},
        ],
        "messages": [{
            "role": "user",
            "content": (
                "Draft a workflow that searches {object} by Email and updates it when found, "
                "otherwise creates it. Use the salesforce connector operations search/update/create "
                "and an if_condition on the search result's `found` field."
            ),
        }],
    },
    {
        "name": "explain-workflow",
        "description": "Explain what a workflow does, node by node.",
        "arguments": [{"name": "workflow_uri", "description": "workflow://{id} resource uri", "required": True}],
        "messages": [{
            "role": "user",
            "content": (
                "Read resource {workflow_uri} and explain what this automation does step by step, "
                "including triggers, credentials it needs, and any external side effects."
            ),
        }],
    },
]


@router.get("/api/mcp/prompts")
def list_mcp_prompts(user: User = Depends(get_current_user)) -> dict:
    """Prompt library: reusable agent prompts with argument placeholders."""
    return ok(MCP_PROMPTS)


# --- MCP API Endpoints ---

@router.get("/api/mcp/tools")
def list_mcp_tools(user: User = Depends(get_current_user)) -> dict:
    """List available MCP tools."""
    return ok([t.model_dump() for t in MCP_TOOLS])


@router.post("/api/mcp/call")
async def call_mcp_tool(
    payload: MCPToolCall,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """Execute an MCP tool."""
    tool = next((t for t in MCP_TOOLS if t.name == payload.name), None)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tool not found: {payload.name}")

    args = payload.arguments

    try:
        if payload.name == "list_workflows":
            from sqlalchemy import select
            ids = accessible_ids(db, user)
            if not ids:
                result = []
            else:
                stmt = select(WorkflowRecord).where(
                    WorkflowRecord.id.in_(ids), WorkflowRecord.deleted_at.is_(None)
                )
                if "workspace_id" in args:
                    stmt = stmt.where(WorkflowRecord.workspace_id == args["workspace_id"])
                stmt = stmt.order_by(WorkflowRecord.updated_at.desc()).limit(20)
                wfs = db.execute(stmt).scalars().all()
                result = [{
                    "id": w.id,
                    "name": w.name,
                    "active": w.active,
                    "node_count": len((w.data or {}).get("nodes", [])),
                    "updated_at": str(w.updated_at),
                } for w in wfs]

        elif payload.name == "get_workflow":
            perm = get_permission(db, args["workflow_id"], user)
            if perm is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
            wf = db.get(WorkflowRecord, args["workflow_id"])
            result = {
                "id": wf.id,
                "name": wf.name,
                "active": wf.active,
                "data": wf.data,
            }

        elif payload.name == "trigger_workflow":
            from app.api.executions import start_execution, workflow_workspace
            perm = get_permission(db, args["workflow_id"], user)
            if perm is None or perm == PERMISSION_VIEW:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found or insufficient permissions.")
            wf = db.get(WorkflowRecord, args["workflow_id"])
            input_data = args.get("input_data") or {}
            trigger_items = input_data if isinstance(input_data, list) else [input_data]
            exec_id = start_execution(
                db,
                workflow_id=wf.id,
                user_id=user.id,
                version=wf.version,
                workflow_data=wf.data,
                trigger="mcp",
                trigger_items=trigger_items,
                workspace_id=workflow_workspace(db, wf.id),
            )
            result = {"execution_id": exec_id, "status": "queued"}

        elif payload.name == "get_execution":
            exec_rec = db.get(Execution, args["execution_id"])
            if exec_rec is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
            # Check the user has access to the execution's workflow
            perm = get_permission(db, exec_rec.workflow_id, user)
            if perm is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
            outputs = (exec_rec.results or {}).get("outputs")
            result = {
                "id": exec_rec.id,
                "status": exec_rec.status,
                "trigger": exec_rec.trigger,
                "started_at": str(exec_rec.started_at),
                "finished_at": str(exec_rec.finished_at) if exec_rec.finished_at else None,
                "error": exec_rec.error,
                "node_statuses": exec_rec.node_statuses or {},
                "outputs": outputs or {},
            }

        elif payload.name == "list_executions":
            from sqlalchemy import select
            ids = accessible_ids(db, user)
            if not ids:
                result = []
            else:
                stmt = select(Execution).where(
                    Execution.workflow_id.in_(ids)
                ).order_by(Execution.started_at.desc(), Execution.id.desc())
                if "workflow_id" in args:
                    stmt = stmt.where(Execution.workflow_id == args["workflow_id"])
                if "status" in args:
                    stmt = stmt.where(Execution.status == args["status"])
                stmt = stmt.limit(args.get("limit", 10))
                execs = db.execute(stmt).scalars().all()
                result = [{
                    "id": e.id,
                    "workflow_id": e.workflow_id,
                    "status": e.status,
                    "started_at": str(e.started_at),
                } for e in execs]

        elif payload.name == "create_backup":
            if user.role != "admin":
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required.")
            filepath = create_backup(name=args.get("name"))
            result = {"filename": filepath.name, "path": str(filepath)}

        elif payload.name == "list_backups":
            if user.role != "admin":
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required.")
            result = list_backups()

        elif payload.name == "set_workflow_active":
            from app.api.workflows import _set_active_impl

            wf = db.get(WorkflowRecord, args["workflow_id"])
            if wf is None or wf.deleted_at is not None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
            active = bool(args["active"])
            if wf.user_id != user.id:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can change activation.")
            _set_active_impl(db, wf, user, active)
            result = {"id": wf.id, "active": active}

        elif payload.name == "use_template":
            from sqlalchemy import select

            from app.models import WorkflowTemplate

            tmpl = db.get(WorkflowTemplate, args["template_id"])
            if tmpl is None or (not tmpl.is_public and tmpl.created_by != user.id):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found.")
            raw = tmpl.workflow_data
            doc = json.loads(raw) if isinstance(raw, str) else raw
            new_id = args.get("new_id") or f"wf_{uuid.uuid4().hex[:12]}"
            doc = {**doc, "id": new_id, "name": tmpl.name}
            from app.api.common import validate_workflow_payload

            workflow = validate_workflow_payload(doc)
            if db.get(WorkflowRecord, workflow.id) is not None:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Workflow '{workflow.id}' already exists.")
            rec = WorkflowRecord(
                id=workflow.id,
                user_id=user.id,
                name=workflow.name,
                description=tmpl.description,
                version=1,
                data=workflow.model_dump(mode="json"),
                workspace_id=None,
            )
            db.add(rec)
            tmpl.use_count += 1
            db.commit()
            db.refresh(rec)
            result = {"id": rec.id, "name": rec.name}

        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown tool: {payload.name}")

        return ok(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("MCP tool call failed: %s", e)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
