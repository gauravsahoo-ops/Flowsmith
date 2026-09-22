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
        embeddings = await embedder.get_embeddings([query])
        query_embedding = embeddings[0] if embeddings else []

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
