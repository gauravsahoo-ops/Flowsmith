"""Built-in tools the AI node can call (Phase 8).

Each tool has an OpenAI function-calling schema and a run handler.
`http_request` / `database_query` reuse the node's `http` / `database`
credentials when present; the database tool is read-only by design
(SELECT/EXPLAIN/PRAGMA/WITH only) because an LLM drives it.
"""

from __future__ import annotations

import asyncio
import datetime
import json
from dataclasses import dataclass
from typing import Any, Callable

from app.engine.node_base import NodeContext

MAX_TOOL_RESULT_CHARS = 4000


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[NodeContext, dict[str, Any]], Any]


def _to_message(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "... (truncated)"
    return text


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str], handler: Callable) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        handler=handler,
    )


def _current_time_handler(ctx: NodeContext, args: dict[str, Any]) -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _database_query_handler(ctx: NodeContext, args: dict[str, Any]) -> Any:
    sql = args.get("sql")
    if not sql:
        raise ValueError("'sql' is required.")
    stripped = sql.lstrip()
    if not stripped[:20].upper().split()[0] in ("SELECT", "EXPLAIN", "PRAGMA", "WITH"):
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


# The HTTP tool performs its own request (mirrors the http_request node):
async def _http_tool_async(ctx: NodeContext, args: dict[str, Any]) -> Any:
    import httpx

    url = args.get("url")
    if not url:
        raise ValueError("'url' is required.")
    method = str(args.get("method") or "GET").upper()
    headers: dict[str, str] = dict(args.get("headers") or {})
    http_cred = ctx.credentials.get("http") or {}
    lowered = {k.lower() for k in headers}
    if http_cred.get("api_key") and "authorization" not in lowered:
        headers["Authorization"] = f"Bearer {http_cred['api_key']}"
    elif http_cred.get("username") or http_cred.get("password"):
        import base64

        user, pwd = http_cred.get("username", ""), http_cred.get("password", "")
        headers["Authorization"] = f"Basic {base64.b64encode(f'{user}:{pwd}'.encode()).decode()}"
    body = args.get("body")
    kwargs: dict[str, Any] = {}
    if isinstance(body, (dict, list)):
        kwargs["json"] = body
    elif body is not None:
        kwargs["content"] = str(body)
    resp = await ctx.http_client.request(method, url, headers=headers, **kwargs)
    try:
        payload = resp.json()
    except ValueError:
        payload = resp.text[:MAX_TOOL_RESULT_CHARS]
    return {"status": resp.status_code, "body": payload}


def openai_tools(names: list[str] | None) -> list[dict[str, Any]]:
    """OpenAI tool definitions for the selected tool names."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for name, spec in TOOLS.items()
        if names is None or name in names
    ]


async def run_tool(ctx: NodeContext, name: str, args: dict[str, Any]) -> str:
    """Execute a tool; returns the message content for the LLM."""
    spec = TOOLS.get(name)
    if spec is None:
        raise ValueError(f"Unknown tool '{name}'.")
    if spec.name == "http_request":
        value = await _http_tool_async(ctx, args)
    elif spec.name == "database_query":
        value = await asyncio.to_thread(_database_query_handler, ctx, args)
    else:
        value = spec.handler(ctx, args)
    return _to_message(value)


TOOLS: dict[str, ToolSpec] = {
    "current_time": _tool(
        "current_time",
        "Get the current UTC date and time as an ISO-8601 string.",
        {},
        [],
        _current_time_handler,
    ),
    "http_request": _tool(
        "http_request",
        "Perform an HTTP(S) request and return the status and body. "
        "Uses the workflow's 'http' credential for authentication when configured.",
        {
            "url": {"type": "string", "description": "Absolute URL."},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "description": "HTTP method."},
            "headers": {"type": "object", "description": "Extra headers."},
            "body": {"description": "JSON body for POST/PUT/PATCH."},
        },
        ["url"],
        _current_time_handler,  # unused; the async variant handles http_request
    ),
    "database_query": _tool(
        "database_query",
        "Run a READ-ONLY SQL query (SELECT/EXPLAIN/PRAGMA/WITH) against the workflow's "
        "'database' credential and return the rows.",
        {"sql": {"type": "string", "description": "Read-only SQL statement."}},
        ["sql"],
        _database_query_handler,
    ),
}