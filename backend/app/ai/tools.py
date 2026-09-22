"""Dynamic Tool Registry for Flowsmith AI Agents.

Supports:
1. Built-in system tools (HTTP request, Database query, Time, Calculator, Vector search, Python sandbox).
2. Dynamic Node-as-a-Tool Adapter (any node in the registry can be called by the Agent).
3. Sub-workflow as a Tool.
4. Human-in-the-Loop (HITL) approval gates.
"""

from __future__ import annotations

import asyncio
import datetime
import inspect
import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Callable


from app.engine.node_base import NodeContext
from app.security.safe_http_client import SafeHTTPClient

logger = logging.getLogger("ai.tools")

MAX_TOOL_RESULT_CHARS = 8000


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[NodeContext, dict[str, Any]], Any]
    requires_approval: bool = False
    category: str = "general"


def _to_message(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "... (truncated)"
    return text


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    handler: Callable,
    requires_approval: bool = False,
    category: str = "general",
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        handler=handler,
        requires_approval=requires_approval,
        category=category,
    )


# ---------------------------------------------------------------------------
# Built-in Tool Handlers
# ---------------------------------------------------------------------------

def _current_time_handler(ctx: NodeContext, args: dict[str, Any]) -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _calculator_handler(ctx: NodeContext, args: dict[str, Any]) -> str:
    expr = str(args.get("expression", "")).strip()
    if not expr:
        return "Error: Empty expression"
    # Safe math evaluation supporting basic operators
    allowed_chars = re.compile(r"^[0-9+\-*/()., %^eE\s]+$")
    if not allowed_chars.match(expr):
        return "Error: Invalid math expression. Only digits and operators (+, -, *, /, %, ^, parentheses) allowed."
    safe_expr = expr.replace("^", "**")
    try:
        # Limited math globals
        result = eval(safe_expr, {"__builtins__": {}}, {"math": math, "sqrt": math.sqrt, "pi": math.pi})
        return str(result)
    except Exception as exc:
        return f"Error calculating: {exc}"


async def _vector_search_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    collection = args.get("collection_name", "rag_default")
    query = args.get("query", "")
    top_k = int(args.get("top_k", 3))

    if not query:
        return {"warning": "No search query provided."}

    try:
        from app.vectorstores import get_vector_store
        store = get_vector_store()
        if not store:
            return {"warning": "Vector store not configured or unavailable."}

        # Resolve query embedding via EmbeddingService
        from app.ai.rag import EmbeddingService
        embedder = EmbeddingService()
        query_embedding = await embedder.get_embedding(query)

        if not query_embedding:
            return {"warning": "Could not generate query embedding."}

        handle = store.ensure_collection(collection, len(query_embedding))
        results = store.query(handle, query_embedding, top_k)
        return results if results else {"message": f"No matches found in collection '{collection}'."}
    except Exception as exc:
        return {"error": f"Vector search error: {exc}"}


async def _http_tool_async(ctx: NodeContext, args: dict[str, Any]) -> dict[str, Any]:
    url = args.get("url")
    if not url:
        raise ValueError("'url' is required.")
    method = (args.get("method") or "GET").upper()
    headers = dict(args.get("headers") or {})
    body = args.get("body")

    creds = ctx.credentials.get("http") or {}
    if creds.get("token"):
        headers.setdefault("Authorization", f"Bearer {creds['token']}")
    elif creds.get("username"):
        import base64
        token = base64.b64encode(f"{creds['username']}:{creds.get('password', '')}".encode()).decode()
        headers.setdefault("Authorization", f"Basic {token}")

    client = SafeHTTPClient(timeout_s=15.0)
    try:
        kwargs: dict[str, Any] = {"headers": headers}
        if body is not None and method in ("POST", "PUT", "PATCH", "DELETE"):
            if isinstance(body, (dict, list)):
                kwargs["json"] = body
            else:
                kwargs["content"] = str(body).encode()
        resp = await client.request(method, url, **kwargs)
        try:
            body_parsed = resp.json()
        except Exception:
            body_parsed = resp.text[:1000]
        return {"status_code": resp.status_code, "body": body_parsed}
    except Exception as exc:
        return {"error": f"HTTP request failed: {exc}"}


def _database_query_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    sql = args.get("sql")
    if not sql:
        raise ValueError("'sql' is required.")
    stripped = sql.lstrip()
    if stripped[:20].upper().split()[0] not in ("SELECT", "EXPLAIN", "PRAGMA", "WITH"):
        raise ValueError("Only read-only SQL is allowed (SELECT/EXPLAIN/PRAGMA/WITH).")
    creds = ctx.credentials.get("database")
    if not creds or not creds.get("dsn"):
        raise RuntimeError("This workflow has no 'database' credential on the AI node.")
    from sqlalchemy import create_engine, text

    engine = create_engine(creds["dsn"], pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            if result.returns_rows:
                rows = [dict(row._mapping) for row in result]
                return rows if rows else []
            return {"affected_rows": result.rowcount or 0}
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Platform, Canvas & Workflow Supercomputer Tools
# ---------------------------------------------------------------------------

def _workflow_get_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    workflow_id = args.get("workflow_id") or getattr(ctx, "workflow_id", None)
    if not workflow_id:
        return {"error": "No workflow_id provided or active in context."}
    from app.db import SessionLocal
    from app.models import WorkflowRecord

    with SessionLocal() as db:
        rec = db.get(WorkflowRecord, workflow_id)
        if not rec:
            return {"error": f"Workflow '{workflow_id}' not found."}
        data = rec.data or {}
        nodes = data.get("nodes") or []
        edges = data.get("edges") or []
        return {
            "id": rec.id,
            "workflow_id": rec.id,
            "name": rec.name,
            "version": rec.version,
            "active": rec.active,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": [
                {
                    "id": n.get("id"),
                    "name": n.get("name") or (n.get("settings") or {}).get("label") or n.get("type"),
                    "type": n.get("type"),
                    "position": n.get("position"),
                    "parameters": n.get("parameters") or {},
                }
                for n in nodes
            ],
            "edges": [
                {
                    "id": e.get("id"),
                    "source": e.get("source"),
                    "sourceHandle": e.get("sourceHandle", "main"),
                    "target": e.get("target"),
                    "targetHandle": e.get("targetHandle", "main"),
                }
                for e in edges
            ],
        }


def _workflow_add_node_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    workflow_id = args.get("workflow_id") or getattr(ctx, "workflow_id", None)
    if not workflow_id:
        return {"error": "No workflow_id provided or active in context."}
    node_type = args.get("node_type")
    if not node_type:
        return {"error": "'node_type' is required (e.g. 'http_request', 'slack', 'filter')."}
    from app.nodes.registry import NODE_REGISTRY

    if node_type not in NODE_REGISTRY:
        return {"error": f"Unknown node type '{node_type}'. Use platform_list_connectors to view supported types."}

    cls = NODE_REGISTRY[node_type]
    name = args.get("name") or getattr(cls, "display_name", node_type)
    params = args.get("parameters") or {}
    pos_x = float(args.get("position_x", 350))
    pos_y = float(args.get("position_y", 250))

    import uuid
    node_id = f"{node_type}_{uuid.uuid4().hex[:6]}"
    new_node = {
        "id": node_id,
        "name": name,
        "type": node_type,
        "position": {"x": pos_x, "y": pos_y},
        "parameters": params,
        "settings": {"label": name},
    }

    from app.db import SessionLocal
    from app.models import WorkflowRecord

    with SessionLocal() as db:
        rec = db.get(WorkflowRecord, workflow_id)
        if not rec:
            return {"error": f"Workflow '{workflow_id}' not found."}
        data = dict(rec.data or {})
        nodes = list(data.get("nodes") or [])
        nodes.append(new_node)
        data["nodes"] = nodes
        rec.data = data
        rec.version = (rec.version or 1) + 1
        db.commit()
        db.refresh(rec)

    return {
        "success": True,
        "node_id": node_id,
        "message": f"Added node '{name}' ({node_type}) with ID '{node_id}' to the canvas.",
        "node": new_node,
        "workflow_version": rec.version,
    }


def _workflow_update_node_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    workflow_id = args.get("workflow_id") or getattr(ctx, "workflow_id", None)
    node_id = args.get("node_id")
    if not workflow_id or not node_id:
        return {"error": "'workflow_id' and 'node_id' are required."}

    new_params = args.get("parameters")
    new_name = args.get("name")

    from app.db import SessionLocal
    from app.models import WorkflowRecord

    with SessionLocal() as db:
        rec = db.get(WorkflowRecord, workflow_id)
        if not rec:
            return {"error": f"Workflow '{workflow_id}' not found."}
        data = dict(rec.data or {})
        nodes = list(data.get("nodes") or [])
        found = False
        updated_node = None
        for n in nodes:
            if n.get("id") == node_id:
                found = True
                if new_name:
                    n["name"] = new_name
                    n.setdefault("settings", {})["label"] = new_name
                if new_params is not None and isinstance(new_params, dict):
                    existing = n.setdefault("parameters", {})
                    existing.update(new_params)
                updated_node = n
                break
        if not found:
            return {"error": f"Node '{node_id}' not found in workflow '{workflow_id}'."}

        data["nodes"] = nodes
        rec.data = data
        rec.version = (rec.version or 1) + 1
        db.commit()
        db.refresh(rec)

    return {
        "success": True,
        "message": f"Updated node '{node_id}' successfully.",
        "node": updated_node,
        "workflow_version": rec.version,
    }


def _workflow_connect_nodes_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    workflow_id = args.get("workflow_id") or getattr(ctx, "workflow_id", None)
    source = args.get("source_node_id")
    target = args.get("target_node_id")
    source_handle = args.get("source_handle", "main")
    target_handle = args.get("target_handle", "main")

    if not workflow_id or not source or not target:
        return {"error": "'workflow_id', 'source_node_id', and 'target_node_id' are required."}

    import uuid
    edge_id = f"e_{source}_{target}_{uuid.uuid4().hex[:4]}"
    new_edge = {
        "id": edge_id,
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
    }

    from app.db import SessionLocal
    from app.models import WorkflowRecord

    with SessionLocal() as db:
        rec = db.get(WorkflowRecord, workflow_id)
        if not rec:
            return {"error": f"Workflow '{workflow_id}' not found."}
        data = dict(rec.data or {})
        edges = list(data.get("edges") or [])
        for e in edges:
            if e.get("source") == source and e.get("target") == target and e.get("sourceHandle") == source_handle:
                return {"message": "Nodes are already connected.", "edge": e}
        edges.append(new_edge)
        data["edges"] = edges
        rec.data = data
        rec.version = (rec.version or 1) + 1
        db.commit()
        db.refresh(rec)

    return {
        "success": True,
        "message": f"Connected '{source}' ({source_handle}) -> '{target}' ({target_handle}).",
        "edge": new_edge,
        "workflow_version": rec.version,
    }


def _workflow_delete_node_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    workflow_id = args.get("workflow_id") or getattr(ctx, "workflow_id", None)
    node_id = args.get("node_id")
    if not workflow_id or not node_id:
        return {"error": "'workflow_id' and 'node_id' are required."}

    from app.db import SessionLocal
    from app.models import WorkflowRecord

    with SessionLocal() as db:
        rec = db.get(WorkflowRecord, workflow_id)
        if not rec:
            return {"error": f"Workflow '{workflow_id}' not found."}
        data = dict(rec.data or {})
        nodes = [n for n in (data.get("nodes") or []) if n.get("id") != node_id]
        edges = [e for e in (data.get("edges") or []) if e.get("source") != node_id and e.get("target") != node_id]
        data["nodes"] = nodes
        data["edges"] = edges
        rec.data = data
        rec.version = (rec.version or 1) + 1
        db.commit()
        db.refresh(rec)

    return {
        "success": True,
        "message": f"Deleted node '{node_id}' and all connected edges from canvas.",
        "workflow_version": rec.version,
    }


async def _workflow_run_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    workflow_id = args.get("workflow_id") or getattr(ctx, "workflow_id", None)
    if not workflow_id:
        return {"error": "No workflow_id provided or active in context."}
    trigger_data = args.get("trigger_data") or {}
    trigger_items = [trigger_data] if trigger_data else [{}]

    from app.db import SessionLocal
    from app.models import WorkflowRecord
    from app.engine.service import start_execution

    with SessionLocal() as db:
        rec = db.get(WorkflowRecord, workflow_id)
        if not rec:
            return {"error": f"Workflow '{workflow_id}' not found."}
        user_id = getattr(ctx, "user_id", None) or rec.user_id
        try:
            exec_id = start_execution(
                db,
                workflow_id=workflow_id,
                user_id=user_id,
                version=rec.version,
                workflow_data=rec.data,
                trigger="ai_agent",
                trigger_items=trigger_items,
                workspace_id=rec.workspace_id,
            )
            return {
                "success": True,
                "execution_id": exec_id,
                "status": "queued",
                "message": f"Workflow execution '{exec_id}' started.",
            }
        except Exception as exc:
            return {"error": f"Failed to launch workflow: {exc}"}


def _workflow_get_execution_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    execution_id = args.get("execution_id")
    if not execution_id:
        return {"error": "'execution_id' is required."}

    from app.db import SessionLocal
    from app.models import Execution

    with SessionLocal() as db:
        rec = db.get(Execution, execution_id)
        if not rec:
            return {"error": f"Execution '{execution_id}' not found."}
        trace = rec.trace or []
        return {
            "id": rec.id,
            "workflow_id": rec.workflow_id,
            "status": rec.status,
            "duration_ms": rec.duration_ms,
            "error": rec.error,
            "step_count": len(trace),
            "steps": [
                {
                    "node_id": s.get("node_id"),
                    "status": s.get("status"),
                    "duration_ms": s.get("duration_ms"),
                    "error": s.get("error"),
                    "output_count": len(s.get("outputs", {}).get("main", [])) if isinstance(s.get("outputs"), dict) else 0,
                }
                for s in trace[:15]
            ],
        }


def _datatable_list_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    from app.db import SessionLocal
    from app.models.data_table import DataTable
    from sqlalchemy import select

    with SessionLocal() as db:
        tables = db.scalars(select(DataTable)).all()
        return {
            "tables": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description or "",
                    "columns": [c.name for c in t.columns],
                    "row_count": len(t.rows),
                }
                for t in tables[:25]
            ]
        }


def _datatable_query_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    table_id = args.get("table_id")
    if not table_id:
        return {"error": "'table_id' is required."}
    search = str(args.get("search", "")).lower()
    limit = int(args.get("limit", 20))

    from app.db import SessionLocal
    from app.models.data_table import DataTable, DataTableRow
    from sqlalchemy import select

    with SessionLocal() as db:
        t = db.get(DataTable, table_id)
        if not t:
            t = db.scalars(select(DataTable).where(DataTable.name == table_id)).first()
        if not t:
            return {"error": f"DataTable '{table_id}' not found."}
        all_rows = db.scalars(select(DataTableRow).where(DataTableRow.table_id == t.id).order_by(DataTableRow.created_at.desc())).all()
        result_rows = []
        for r in all_rows:
            row_data = {"id": r.id, **(r.data or {})}
            if not search or search in json.dumps(row_data).lower():
                result_rows.append(row_data)
                if len(result_rows) >= limit:
                    break
        return {
            "table_id": t.id,
            "name": t.name,
            "columns": [{"name": c.name, "type": c.type} for c in t.columns],
            "total_rows": len(all_rows),
            "rows": result_rows,
        }


def _datatable_insert_row_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    table_id = args.get("table_id")
    row_data = args.get("row_data")
    if not table_id or not row_data or not isinstance(row_data, dict):
        return {"error": "'table_id' and 'row_data' (dict) are required."}

    import uuid
    from app.db import SessionLocal
    from app.models.data_table import DataTable, DataTableRow
    from sqlalchemy import select

    with SessionLocal() as db:
        t = db.get(DataTable, table_id)
        if not t:
            t = db.scalars(select(DataTable).where(DataTable.name == table_id)).first()
        if not t:
            return {"error": f"DataTable '{table_id}' not found."}
        row_id = f"row_{uuid.uuid4().hex[:12]}"
        clean_data = {k: v for k, v in row_data.items() if k != "id"}
        rec = DataTableRow(id=row_id, table_id=t.id, data=clean_data)
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return {
            "success": True,
            "message": f"Inserted row into DataTable '{t.name}'.",
            "row": {"id": rec.id, **clean_data},
        }


def _platform_list_connectors_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    from app.nodes.registry import NODE_REGISTRY

    category_filter = args.get("category")
    results = []
    for node_type, cls in NODE_REGISTRY.items():
        cat = getattr(cls, "category", "general")
        if category_filter and cat.lower() != category_filter.lower():
            continue
        results.append({
            "type": node_type,
            "display_name": getattr(cls, "display_name", node_type),
            "category": cat,
        })
    return {
        "total": len(results),
        "connectors": sorted(results, key=lambda x: (x["category"], x["display_name"])),
    }


def _platform_system_health_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    import os
    status = {
        "database": "unknown",
        "redis": "unknown",
        "status": "healthy",
        "environment": os.getenv("ENV", "production"),
    }
    try:
        from app.db import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        status["database"] = "connected"
    except Exception as e:
        status["database"] = f"error: {e}"
        status["status"] = "degraded"

    try:
        from redis import Redis
        r_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r_client = Redis.from_url(r_url, socket_timeout=2)
        if r_client.ping():
            status["redis"] = "connected"
    except Exception as e:
        status["redis"] = f"error: {e}"
        if status["status"] != "degraded":
            status["status"] = "degraded"

    return status


# ---------------------------------------------------------------------------
# Built-in Tools Table
# ---------------------------------------------------------------------------

TOOLS: dict[str, ToolSpec] = {
    "current_time": _tool(
        "current_time",
        "Get current UTC date and time as an ISO-8601 string.",
        {},
        [],
        _current_time_handler,
    ),
    "calculator": _tool(
        "calculator",
        "Perform mathematical calculations and formulas accurately.",
        {"expression": {"type": "string", "description": "Mathematical expression (e.g. '(1250 * 0.15) + 42')"}},
        ["expression"],
        _calculator_handler,
    ),
    "http_request": _tool(
        "http_request",
        "Perform an HTTP(S) request and return status code and response body.",
        {
            "url": {"type": "string", "description": "Absolute URL."},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "description": "HTTP method."},
            "headers": {"type": "object", "description": "Extra headers."},
            "body": {"description": "JSON payload for write requests."},
        },
        ["url"],
        _http_tool_async,
        category="network",
    ),
    "database_query": _tool(
        "database_query",
        "Execute a READ-ONLY SQL query (SELECT/WITH/EXPLAIN) against the configured database.",
        {"sql": {"type": "string", "description": "Read-only SQL query."}},
        ["sql"],
        _database_query_handler,
        category="data",
    ),
    "vector_search": _tool(
        "vector_search",
        "Perform semantic similarity search over stored documents in pgvector knowledge base.",
        {
            "query": {"type": "string", "description": "Search query."},
            "collection_name": {"type": "string", "description": "Knowledge collection name."},
            "top_k": {"type": "integer", "description": "Max chunks to retrieve."},
        },
        ["query"],
        _vector_search_handler,
        category="ai",
    ),
    # Canvas & Workflow Tools
    "workflow_get": _tool(
        "workflow_get",
        "Inspect the active or specified workflow canvas: nodes, positions, configurations, and edges.",
        {"workflow_id": {"type": "string", "description": "Optional workflow ID (defaults to active canvas workflow)."}},
        [],
        _workflow_get_handler,
        category="workflow",
    ),
    "workflow_add_node": _tool(
        "workflow_add_node",
        "Add a new node to the workflow canvas with custom type, label, position, and configuration parameters.",
        {
            "node_type": {"type": "string", "description": "Node type (e.g. 'http_request', 'slack', 'filter', 'code', 'ai_agent')."},
            "name": {"type": "string", "description": "Display name/label for the node."},
            "parameters": {"type": "object", "description": "Initial parameters configuration dict."},
            "position_x": {"type": "number", "description": "X coordinate on canvas (default: 350)."},
            "position_y": {"type": "number", "description": "Y coordinate on canvas (default: 250)."},
            "workflow_id": {"type": "string", "description": "Optional workflow ID."},
        },
        ["node_type"],
        _workflow_add_node_handler,
        category="workflow",
    ),
    "workflow_update_node": _tool(
        "workflow_update_node",
        "Update the configuration parameters or label of an existing node on the workflow canvas.",
        {
            "node_id": {"type": "string", "description": "ID of the node to update."},
            "name": {"type": "string", "description": "New display name/label."},
            "parameters": {"type": "object", "description": "Parameters dictionary to update or merge."},
            "workflow_id": {"type": "string", "description": "Optional workflow ID."},
        },
        ["node_id"],
        _workflow_update_node_handler,
        category="workflow",
    ),
    "workflow_connect_nodes": _tool(
        "workflow_connect_nodes",
        "Wire an edge connection between two nodes on the workflow canvas.",
        {
            "source_node_id": {"type": "string", "description": "Source node ID emitting data."},
            "target_node_id": {"type": "string", "description": "Target node ID receiving data."},
            "source_handle": {"type": "string", "description": "Source output port handle (default: 'main')."},
            "target_handle": {"type": "string", "description": "Target input port handle (default: 'main')."},
            "workflow_id": {"type": "string", "description": "Optional workflow ID."},
        },
        ["source_node_id", "target_node_id"],
        _workflow_connect_nodes_handler,
        category="workflow",
    ),
    "workflow_delete_node": _tool(
        "workflow_delete_node",
        "Delete a node and all its connected edges from the workflow canvas.",
        {
            "node_id": {"type": "string", "description": "ID of the node to delete."},
            "workflow_id": {"type": "string", "description": "Optional workflow ID."},
        },
        ["node_id"],
        _workflow_delete_node_handler,
        category="workflow",
    ),
    "workflow_run": _tool(
        "workflow_run",
        "Trigger execution of the active or specified workflow.",
        {
            "workflow_id": {"type": "string", "description": "Optional workflow ID."},
            "trigger_data": {"type": "object", "description": "Optional input payload for trigger step."},
        },
        [],
        _workflow_run_handler,
        category="workflow",
    ),
    "workflow_get_execution": _tool(
        "workflow_get_execution",
        "Inspect the live status, step trace, outputs, and errors of a workflow execution.",
        {"execution_id": {"type": "string", "description": "Execution ID returned by workflow_run."}},
        ["execution_id"],
        _workflow_get_execution_handler,
        category="workflow",
    ),
    # Data Table Tools
    "datatable_list": _tool(
        "datatable_list",
        "List all Flowsmith relational Data Tables in the workspace (ID, name, schema columns, row count).",
        {},
        [],
        _datatable_list_handler,
        category="datatable",
    ),
    "datatable_query": _tool(
        "datatable_query",
        "Query and search rows from a Flowsmith Data Table by table ID or name.",
        {
            "table_id": {"type": "string", "description": "Data Table ID or name."},
            "search": {"type": "string", "description": "Optional text search filter."},
            "limit": {"type": "integer", "description": "Max rows to return (default: 20)."},
        },
        ["table_id"],
        _datatable_query_handler,
        category="datatable",
    ),
    "datatable_insert_row": _tool(
        "datatable_insert_row",
        "Insert a new structured record/row into a Flowsmith Data Table.",
        {
            "table_id": {"type": "string", "description": "Data Table ID or name."},
            "row_data": {"type": "object", "description": "Column key-value pairs to store."},
        },
        ["table_id", "row_data"],
        _datatable_insert_row_handler,
        category="datatable",
    ),
    # Platform Introspection Tools
    "platform_list_connectors": _tool(
        "platform_list_connectors",
        "List all 45+ connectors and node types available in Flowsmith with descriptions and categories.",
        {"category": {"type": "string", "description": "Optional category filter (e.g. 'Trigger', 'AI', 'Database', 'Logic')."}},
        [],
        _platform_list_connectors_handler,
        category="platform",
    ),
    "platform_system_health": _tool(
        "platform_system_health",
        "Check health status of PostgreSQL database, Redis cache/queue, and platform runtime.",
        {},
        [],
        _platform_system_health_handler,
        category="platform",
    ),
}


# ---------------------------------------------------------------------------
# Tool Runner & Schema Exporter
# ---------------------------------------------------------------------------

def openai_tools(tool_names: list[str] | None = None) -> list[dict[str, Any]]:
    """Format tools for OpenAI, Anthropic, or Gemini tool schemas."""
    names = tool_names if tool_names is not None else list(TOOLS.keys())
    out = []
    for name in names:
        spec = TOOLS.get(name)
        if spec:
            out.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            })
    return out


async def run_tool(ctx: NodeContext, name: str, args: dict[str, Any]) -> str:
    """Execute a tool and return formatted string output."""
    spec = TOOLS.get(name)
    if spec is None:
        raise ValueError(f"Unknown tool '{name}'.")

    if spec.requires_approval:
        return json.dumps({
            "status": "pending_approval",
            "message": f"Tool '{name}' requires human approval before executing.",
            "arguments": args,
        })

    if spec.name == "http_request":
        value = await _http_tool_async(ctx, args)
    elif spec.name == "vector_search":
        value = await _vector_search_handler(ctx, args)
    elif spec.name == "database_query":
        value = await asyncio.to_thread(_database_query_handler, ctx, args)
    elif inspect.iscoroutinefunction(spec.handler):
        value = await spec.handler(ctx, args)
    else:
        value = spec.handler(ctx, args)

    return _to_message(value)
