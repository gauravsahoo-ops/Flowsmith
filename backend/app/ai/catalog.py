"""Grounded planner catalog (Phase 15: natural-language workflow generation).

The generation prompt is BUILT FROM THE LIVE REGISTRIES, never hardcoded:
every node type comes from ``NODE_REGISTRY`` (with its real parameter
JSON schema) and every connector/operation from the ConnectorRegistry
definitions. The model literally cannot be told about a node or
operation that does not exist, which is the first half of "the AI must
not invent unavailable connectors, nodes, operations or fields" — the
second half is the validator in app/ai/validation.py.

Rendering is deterministic (sorted keys/types, stable formatting) so
evaluation tests can compare prompts byte-for-byte.
"""

from __future__ import annotations

import json
from typing import Any

from app.connectors import get_registry as get_connector_registry
from app.nodes.registry import NODE_REGISTRY

TRIGGER_NODE_TYPES = frozenset({"manual_trigger", "webhook", "schedule", "salesforce_trigger", "error_trigger"})

_MAX_PROPS_PER_OP = 60


def _compact_props(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Compact a JSON schema into {prop: {type, enum?, default?, required}}."""
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    out: dict[str, Any] = {}
    chosen = sorted(props, key=lambda n: (n not in required, n))[:_MAX_PROPS_PER_OP]
    for name in sorted(chosen):
        spec = props.get(name) or {}
        entry: dict[str, Any] = {"type": spec.get("type", "any")}
        if spec.get("enum"):
            entry["enum"] = list(spec["enum"])
        if spec.get("default") is not None:
            entry["default"] = spec["default"]
        desc = spec.get("description")
        if isinstance(desc, str) and desc.strip():
            entry["description"] = desc.strip()[:160]
        if name in required:
            entry["required"] = True
        out[name] = entry
    return out


def build_node_entries() -> list[dict[str, Any]]:
    """One entry per registered node class, sorted by type for stability."""
    entries: list[dict[str, Any]] = []
    for node_type in sorted(NODE_REGISTRY):
        cls = NODE_REGISTRY[node_type]
        try:
            schema = cls.parameters_schema.model_json_schema()
        except Exception:  # defensive: a broken schema must not kill planning
            schema = {}
        props = _compact_props(schema)
        entries.append({
            "type": node_type,
            "display_name": cls.display_name,
            "category": cls.category,
            "description": (cls.description or "").strip(),
            "trigger": node_type in TRIGGER_NODE_TYPES,
            "credential_types": sorted(cls.credential_types or []),
            "parameters": props,
        })
    return entries


def build_connector_entries() -> list[dict[str, Any]]:
    """One entry per registered connector definition with its real ops."""
    from app.connectors import ensure_builtin_connectors

    ensure_builtin_connectors()
    registry = get_connector_registry()
    entries: list[dict[str, Any]] = []
    definitions = sorted(registry.list_definitions(), key=lambda d: d.connector_key)
    for definition in definitions:
        ops: dict[str, Any] = {}
        cred_requirements: set[str] = set()
        node_types: set[str] = set()
        for op_key, op in sorted((definition.operations or {}).items()):
            ops[op_key] = {
                "description": (op.description or "").strip()[:200],
                "parameters": _compact_props(op.input_schema),
            }
            if getattr(op, "credential_require", None):
                cred_requirements.add(str(op.credential_require))
            node_types.update(getattr(op, "node_types", None) or [])
        if not ops:
            continue
        entries.append({
            "connector": definition.connector_key,
            "display_name": definition.display_name,
            "node_types": sorted(node_types),
            "credential_types": sorted(cred_requirements),
            "operations": ops,
        })
    return entries


_catalog_cache: dict[str, Any] | None = None
_catalog_cache_ts: float = 0.0
_prompt_cache: str | None = None
_prompt_cache_ts: float = 0.0


def build_planner_catalog() -> dict[str, Any]:
    """Build the planner catalog with a 60-second TTL cache."""
    global _catalog_cache, _catalog_cache_ts
    import time
    now = time.monotonic()
    if _catalog_cache is not None and now - _catalog_cache_ts < 60:
        return _catalog_cache
    _catalog_cache = {"nodes": build_node_entries(), "connectors": build_connector_entries()}
    _catalog_cache_ts = now
    return _catalog_cache


def render_system_prompt(catalog: dict[str, Any] | None = None) -> str:
    """The generation system prompt, rendered from live registries.

    Rules section pins the anti-invention contract and the response shape.
    """
    global _prompt_cache, _prompt_cache_ts
    import time
    if catalog is None:
        now = time.monotonic()
        if _prompt_cache is not None and now - _prompt_cache_ts < 60:
            return _prompt_cache

    actual_catalog = catalog or build_planner_catalog()
    payload = json.dumps(actual_catalog, ensure_ascii=False, sort_keys=True)
    rendered = (
        "You generate workflows for a workflow automation platform.\n"
        "Respond with ONLY a JSON object (no markdown fences, no commentary):\n"
        '{"name": "short name", '
        '"nodes": [{"id": "unique_id", "type": "...", "parameters": {...},'
        ' "credentials": {"<credential_type>": "$user"} }],'
        ' "connections": [{"source": "id", "target": "id"}], "settings": {}}\n\n'
        "You may ONLY use the node types, connectors and operations listed "
        "below. NEVER invent node types, connectors, operations, parameter "
        "names or fields that are not listed. If the request needs something "
        "not available, use the closest supported equivalent.\n\n"
        "Rules:\n"
        "- ids: unique lowercase strings; connections only reference existing ids.\n"
        "- Exactly one trigger node; every other node has an incoming connection.\n"
        "- Acyclic graph (no cycles), 2-8 nodes, branch with if_condition where needed.\n"
        "- For connector nodes set parameters.operation to one of the listed operations"
        " and provide each operation's required parameters. Use {{ $json.field }}"
        " expressions to pass data between nodes; pipes like | upper are allowed.\n"
        '- Set "credentials" on a node only with a credential_type LISTED FOR THAT NODE'
        ' and the value "$user" (the user\'s saved credential of that type is resolved at run time).\n'
        "- Never invent credentials, connection strings or secrets.\n\n"
        f"AVAILABLE NODES AND CONNECTORS:\n{payload}"
    )
    if catalog is None:
        _prompt_cache = rendered
        _prompt_cache_ts = time.monotonic()
    return rendered
