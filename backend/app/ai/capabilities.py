"""AI Capability Registry and Search Layer.

Indexes all available Flowsmith built-in nodes, connector definitions,
operations, schemas, triggers, and credential requirements.

Provides targeted capability search so the LLM prompt only receives
relevant capabilities instead of dumping the entire multi-megabyte catalog.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from pydantic import BaseModel, Field

from app.connectors import ensure_builtin_connectors, get_registry as get_connector_registry
from app.nodes.registry import NODE_REGISTRY


class CapabilityOperation(BaseModel):
    operation_id: str
    display_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_fields: list[str] = Field(default_factory=list)
    credential_type: Optional[str] = None
    node_types: list[str] = Field(default_factory=list)


class CapabilityResource(BaseModel):
    resource_id: str
    display_name: str
    operations: dict[str, CapabilityOperation] = Field(default_factory=dict)


class CapabilityConnector(BaseModel):
    connector_id: str
    display_name: str
    category: str = "General"
    description: str = ""
    auth_type: str = "none"
    credential_types: list[str] = Field(default_factory=list)
    node_types: list[str] = Field(default_factory=list)
    supported_triggers: list[str] = Field(default_factory=list)
    supported_actions: list[str] = Field(default_factory=list)
    operations: dict[str, CapabilityOperation] = Field(default_factory=dict)
    resources: dict[str, CapabilityResource] = Field(default_factory=dict)


class CapabilityNode(BaseModel):
    node_type: str
    display_name: str
    category: str = "Flow"
    description: str = ""
    is_trigger: bool = False
    credential_types: list[str] = Field(default_factory=list)
    input_handles: list[str] = Field(default_factory=lambda: ["main"])
    output_handles: list[str] = Field(default_factory=lambda: ["main"])
    parameters_schema: dict[str, Any] = Field(default_factory=dict)


class CapabilityRegistry:
    """In-memory searchable registry of all platform capabilities."""

    _instance: Optional[CapabilityRegistry] = None

    def __init__(self) -> None:
        self._connectors: dict[str, CapabilityConnector] = {}
        self._nodes: dict[str, CapabilityNode] = {}
        self._keyword_index: dict[str, set[str]] = {}
        self.reload()

    @classmethod
    def get_instance(cls) -> CapabilityRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reload(self) -> None:
        """Rebuild the capability graph from live node and connector registries."""
        ensure_builtin_connectors()
        conn_reg = get_connector_registry()
        self._connectors.clear()
        self._nodes.clear()
        self._keyword_index.clear()

        # 1. Index Built-in Node Classes
        for node_type, cls in NODE_REGISTRY.items():
            try:
                p_schema = cls.parameters_schema.model_json_schema()
            except Exception:
                p_schema = {}

            node_cap = CapabilityNode(
                node_type=node_type,
                display_name=getattr(cls, "display_name", node_type),
                category=getattr(cls, "category", "Flow"),
                description=getattr(cls, "description", "") or "",
                is_trigger=node_type in ("manual_trigger", "webhook", "schedule", "salesforce_trigger", "error_trigger", "form_trigger", "chat_trigger"),
                credential_types=list(getattr(cls, "credential_types", []) or []),
                input_handles=list(getattr(cls, "input_handles", ["main"])),
                output_handles=list(getattr(cls, "output_handles", ["main"])),
                parameters_schema=p_schema,
            )
            self._nodes[node_type] = node_cap
            self._index_keywords(f"node:{node_type}", f"{node_type} {node_cap.display_name} {node_cap.description} {node_cap.category}")

        # 2. Index Connectors & Operations
        for defn in conn_reg.list_definitions():
            c_key = defn.connector_key
            cred_types = set()
            node_types = set()
            ops_map: dict[str, CapabilityOperation] = {}
            triggers_list = []
            actions_list = []

            for op_key, op in (defn.operations or {}).items():
                in_schema = op.input_schema or {}
                req = in_schema.get("required") or []
                cred = getattr(op, "credential_require", None)
                if cred:
                    cred_types.add(str(cred))
                n_types = getattr(op, "node_types", None) or []
                node_types.update(n_types)

                op_cap = CapabilityOperation(
                    operation_id=op_key,
                    display_name=getattr(op, "display_name", op_key) or op_key,
                    description=getattr(op, "description", "") or "",
                    input_schema=in_schema,
                    output_schema=getattr(op, "output_schema", {}) or {},
                    required_fields=list(req),
                    credential_type=str(cred) if cred else None,
                    node_types=list(n_types),
                )
                ops_map[op_key] = op_cap

                if "trigger" in op_key.lower() or "watch" in op_key.lower():
                    triggers_list.append(op_key)
                else:
                    actions_list.append(op_key)

                self._index_keywords(
                    f"conn:{c_key}:{op_key}",
                    f"{c_key} {defn.display_name} {op_key} {op_cap.display_name} {op_cap.description}"
                )

            # Build Resources (e.g. Lead, Contact, Account for Salesforce)
            resources_map: dict[str, CapabilityResource] = {}
            for op_key, op_cap in ops_map.items():
                parts = op_key.split("_", 1)
                r_name = parts[1].title() if len(parts) > 1 else "Default"
                if r_name not in resources_map:
                    resources_map[r_name] = CapabilityResource(resource_id=r_name.lower(), display_name=r_name)
                resources_map[r_name].operations[op_key] = op_cap

            conn_cap = CapabilityConnector(
                connector_id=c_key,
                display_name=defn.display_name,
                category=getattr(defn, "category", "General") or "General",
                description=getattr(defn, "description", "") or "",
                auth_type=getattr(defn, "auth_type", "none") or "none",
                credential_types=sorted(cred_types),
                node_types=sorted(node_types),
                supported_triggers=triggers_list,
                supported_actions=actions_list,
                operations=ops_map,
                resources=resources_map,
            )
            self._connectors[c_key] = conn_cap
            self._index_keywords(f"conn:{c_key}", f"{c_key} {defn.display_name} {conn_cap.category} {conn_cap.description}")

    def _index_keywords(self, target_id: str, text: str) -> None:
        words = re.findall(r"\w+", text.lower())
        for w in words:
            if len(w) >= 2:
                self._keyword_index.setdefault(w, set()).add(target_id)

    def search_capabilities(self, query: str, limit: int = 15) -> dict[str, Any]:
        """Search capabilities based on natural language keywords and concepts."""
        tokens = re.findall(r"\w+", query.lower())
        scores: dict[str, int] = {}

        for token in tokens:
            # Exact matches
            for target in self._keyword_index.get(token, set()):
                scores[target] = scores.get(target, 0) + 3
            # Prefix matches
            for indexed_w, targets in self._keyword_index.items():
                if indexed_w.startswith(token) and indexed_w != token:
                    for target in targets:
                        scores[target] = scores.get(target, 0) + 1

        sorted_targets = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]

        matched_nodes: list[dict[str, Any]] = []
        matched_connectors: list[dict[str, Any]] = []

        seen_connectors: set[str] = set()

        for target_id, score in sorted_targets:
            if target_id.startswith("node:"):
                ntype = target_id.split(":", 1)[1]
                node = self._nodes.get(ntype)
                if node:
                    matched_nodes.append({
                        "node_type": node.node_type,
                        "display_name": node.display_name,
                        "category": node.category,
                        "description": node.description,
                        "is_trigger": node.is_trigger,
                        "credential_types": node.credential_types,
                        "handles": {"input": node.input_handles, "output": node.output_handles},
                    })
            elif target_id.startswith("conn:"):
                parts = target_id.split(":")
                c_key = parts[1]
                if c_key in seen_connectors:
                    continue
                seen_connectors.add(c_key)
                conn = self._connectors.get(c_key)
                if conn:
                    # Provide compact operations
                    ops_summary = {}
                    for op_key, op in conn.operations.items():
                        ops_summary[op_key] = {
                            "display_name": op.display_name,
                            "description": op.description,
                            "required_fields": op.required_fields,
                            "credential_type": op.credential_type,
                        }
                    matched_connectors.append({
                        "connector_id": conn.connector_id,
                        "display_name": conn.display_name,
                        "category": conn.category,
                        "description": conn.description,
                        "credential_types": conn.credential_types,
                        "operations": ops_summary,
                    })

        # Always include essential flow nodes if not already matched
        essential_types = ["webhook", "schedule", "if_condition", "http_request", "ai_agent"]
        matched_types = {n["node_type"] for n in matched_nodes}
        for et in essential_types:
            if et not in matched_types and et in self._nodes:
                n = self._nodes[et]
                matched_nodes.append({
                    "node_type": n.node_type,
                    "display_name": n.display_name,
                    "category": n.category,
                    "description": n.description,
                    "is_trigger": n.is_trigger,
                    "credential_types": n.credential_types,
                    "handles": {"input": n.input_handles, "output": n.output_handles},
                })

        return {
            "query": query,
            "nodes": matched_nodes,
            "connectors": matched_connectors,
        }

    def resolve_capability(self, system_or_node: str, operation: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Resolve exact capability details for a node or connector operation."""
        norm_key = system_or_node.strip().lower()

        # Check nodes
        if norm_key in self._nodes:
            node = self._nodes[norm_key]
            return {
                "kind": "node",
                "node_type": node.node_type,
                "display_name": node.display_name,
                "schema": node.parameters_schema,
                "credential_types": node.credential_types,
                "handles": {"input": node.input_handles, "output": node.output_handles},
            }

        # Check connectors
        if norm_key in self._connectors:
            conn = self._connectors[norm_key]
            if operation and operation in conn.operations:
                op = conn.operations[operation]
                return {
                    "kind": "connector",
                    "connector_id": conn.connector_id,
                    "operation_id": op.operation_id,
                    "required_fields": op.required_fields,
                    "input_schema": op.input_schema,
                    "credential_type": op.credential_type or (conn.credential_types[0] if conn.credential_types else None),
                }
            return {
                "kind": "connector",
                "connector_id": conn.connector_id,
                "operations": list(conn.operations.keys()),
                "credential_types": conn.credential_types,
            }

        # Check by connector display name
        for c in self._connectors.values():
            if c.display_name.lower() == norm_key:
                return self.resolve_capability(c.connector_id, operation)

        return None


class CapabilitySearch:
    """Static convenience facade for dynamic capability querying."""

    @classmethod
    def search(cls, query: str, category: Optional[str] = None, limit: int = 10) -> list[Any]:
        reg = CapabilityRegistry.get_instance()
        res = reg.search_capabilities(query, limit=limit)
        # Return merged list of matched operations and nodes
        items = []
        for c in res.get("connectors", []):
            for op in c.get("operations", {}).values() if isinstance(c, dict) else c.operations.values():
                items.append(op)
        for n in res.get("nodes", []):
            items.append(n)
        return items[:limit] if items else [op for c in reg._connectors.values() for op in c.operations.values() if query.lower() in getattr(op, "connector", "").lower()][:limit]



class CapabilityResolver:
    """Resolves specific operations, nodes, and schemas."""

    @classmethod
    def resolve(cls, system_or_node: str, operation: Optional[str] = None) -> Optional[dict[str, Any]]:
        return CapabilityRegistry.get_instance().resolve_capability(system_or_node, operation)


class SchemaResolver:
    """Resolves input and output schemas for node and connector operations."""

    @classmethod
    def get_input_schema(cls, system_or_node: str, operation: Optional[str] = None) -> dict[str, Any]:
        info = CapabilityResolver.resolve(system_or_node, operation)
        if not info:
            return {}
        if info.get("kind") == "connector":
            return info.get("input_schema", {})
        return info.get("schema", {})


class CredentialResolver:
    """Resolves required credential types for capabilities."""

    @classmethod
    def get_required_credentials(cls, system_or_node: str, operation: Optional[str] = None) -> list[str]:
        info = CapabilityResolver.resolve(system_or_node, operation)
        if not info:
            return []
        if info.get("kind") == "connector":
            cred = info.get("credential_type")
            return [cred] if cred else info.get("credential_types", [])
        return info.get("credential_types", [])

