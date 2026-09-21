#!/usr/bin/env python3
"""FlowSmith Developer CLI & Extensibility Tooling.

Commands:
  flowsmith connector create <name> [--category <cat>]
  flowsmith connector validate <name>
  flowsmith connector test <name>
  flowsmith node create <name> [--category <cat>]
  flowsmith workflow validate <path.json>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def to_snake_case(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower().replace("-", "_").replace(" ", "_")


def to_pascal_case(name: str) -> str:
    snake = to_snake_case(name)
    return "".join(word.capitalize() for word in snake.split("_"))


def cmd_connector_create(args: argparse.Namespace) -> int:
    name = args.name.strip()
    key = to_snake_case(name)
    pascal = to_pascal_case(name)
    category = args.category.upper() if args.category else "DEVELOPER_TOOLS"

    conn_dir = BACKEND_DIR / "app" / "connectors"
    conn_file = conn_dir / f"{key}_connector.py"
    def_file = conn_dir / f"{key}_definition.py"

    if conn_file.exists() or def_file.exists():
        print(f"Error: Connector '{key}' already exists at {conn_file} or {def_file}")
        return 1

    conn_code = f'''"""FlowSmith {pascal} Connector implementation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import httpx

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorHealthCheck,
    ConnectorStatus,
    ConnectorError,
    make_connector_error,
)
from app.connectors.operations import OP_HEALTH_CHECK, OP_EXECUTE, OP_GET, OP_CREATE


class {pascal}Connector(ConnectorSDK):
    name = "{pascal}"
    description = "FlowSmith integration for {pascal}."
    category = ConnectorCategory.{category}
    version = "1.0.0"
    node_types = ["{key}"]

    async def connect(self, credentials: Dict[str, Any]) -> bool:
        self.credentials = credentials
        return True

    async def disconnect(self) -> None:
        self.credentials = {{}}

    async def op_health_check(self) -> ConnectorHealthCheck:
        return ConnectorHealthCheck(
            status=ConnectorStatus.HEALTHY,
            message="{pascal} connection active",
        )

    async def op_execute(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if operation == OP_HEALTH_CHECK:
            res = await self.op_health_check()
            return res.model_dump()
        return {{"status": "ok", "operation": operation, "result": params}}
'''

    def_code = f'''"""FlowSmith {pascal} Connector declarative definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorCategory,
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
    OP_GET,
    OP_CREATE,
    OP_HEALTH_CHECK,
)

{pascal.upper()}_DEFINITION = ConnectorDefinitionV1(
    key="{key}",
    name="{pascal}",
    version="1.0.0",
    category=ConnectorCategory.{category},
    lifecycle_status=ConnectorLifecycle.GA.value,
    description="FlowSmith integration for {pascal}.",
    supported_node_types=["{key}"],
    credential_types=[
        CredentialTypeV1(
            credential_type="{key}_api_key",
            name="{pascal} API Key",
            schema={{
                "type": "object",
                "required": ["api_key"],
                "properties": {{
                    "api_key": {{"type": "string", "title": "API Key", "format": "password"}},
                    "base_url": {{"type": "string", "title": "Base URL", "default": "https://api.{key}.com/v1"}},
                }},
            }},
        )
    ],
    operations={{
        OP_HEALTH_CHECK: ConnectorOperationV1(
            name="Health Check",
            description="Verify API connectivity",
            category="System",
            input_schema={{"type": "object", "properties": {{}}}},
            output_schema={{"type": "object", "properties": {{"status": {{"type": "string"}}}}}},
        ),
        OP_GET: ConnectorOperationV1(
            name="Get Resource",
            description="Fetch a resource by ID",
            category="Read",
            input_schema={{
                "type": "object",
                "required": ["id"],
                "properties": {{"id": {{"type": "string", "title": "Resource ID"}}}},
            }},
            output_schema={{"type": "object", "properties": {{"id": {{"type": "string"}}, "data": {{"type": "object"}}}}}},
        ),
    }},
    triggers={{}},
)
'''

    conn_file.write_text(conn_code, encoding="utf-8")
    def_file.write_text(def_code, encoding="utf-8")
    print(f"Created connector files:")
    print(f"  + {conn_file.relative_to(ROOT_DIR)}")
    print(f"  + {def_file.relative_to(ROOT_DIR)}")
    return 0


def cmd_connector_validate(args: argparse.Namespace) -> int:
    name = args.name.strip()
    key = to_snake_case(name)

    try:
        from app.connectors import ensure_builtin_connectors, get_registry
        ensure_builtin_connectors()
        reg = get_registry()
        definition = reg.get_definition(key)
        if not definition:
            print(f"Error: Connector '{key}' definition not found in registry.")
            return 1

        print(f"Connector '{definition.display_name}' ({definition.connector_key}) v{definition.connector_version} is valid.")
        print(f"  Category: {definition.category}")
        print(f"  Lifecycle: {definition.lifecycle_status}")
        print(f"  Operations ({len(definition.operations)}): {list(definition.operations.keys())}")
        print(f"  Triggers ({len(definition.triggers)}): {list(definition.triggers.keys())}")
        cred_types = list(definition.credential_types.keys()) if definition.credential_types else []
        print(f"  Credential Types: {cred_types}")
        return 0
    except Exception as e:
        print(f"Validation failed: {e}")
        return 1


def cmd_node_create(args: argparse.Namespace) -> int:
    name = args.name.strip()
    node_type = to_snake_case(name)
    pascal = to_pascal_case(name)
    category = args.category or "Actions"

    node_file = BACKEND_DIR / "app" / "nodes" / f"{node_type}.py"
    if node_file.exists():
        print(f"Error: Node '{node_type}' already exists at {node_file}")
        return 1

    code = f'''"""FlowSmith {pascal} Node implementation."""

from __future__ import annotations

from typing import Any, Dict, List
from pydantic import BaseModel, Field

from app.engine.node_base import NodeBase, NodeContext, NodeResult
from app.nodes.registry import register_node


class {pascal}Parameters(BaseModel):
    operation: str = Field(default="execute", description="Operation to perform")
    resource_id: str = Field(default="", description="Target resource ID")


@register_node("{node_type}")
class {pascal}Node(NodeBase):
    name = "{pascal}"
    type = "{node_type}"
    category = "{category}"
    description = "Executes {pascal} workflow actions."
    parameters_schema = {pascal}Parameters.model_json_schema()

    async def execute(self, ctx: NodeContext) -> NodeResult:
        params = {pascal}Parameters.model_validate(ctx.parameters)
        item = ctx.first_item or {{}}
        output = {{
            "status": "success",
            "operation": params.operation,
            "resource_id": params.resource_id,
            "input_data": item,
        }}
        return NodeResult(output=[output])
'''
    node_file.write_text(code, encoding="utf-8")
    print(f"Created node file:")
    print(f"  + {node_file.relative_to(ROOT_DIR)}")
    return 0


def cmd_workflow_validate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"Error: Workflow file not found at {path}")
        return 1

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        nodes = data.get("nodes", [])
        raw_conns = data.get("connections", [])

        # Normalize connection shapes to list[Connection]
        norm_conns = []
        if isinstance(raw_conns, list):
            norm_conns = raw_conns
        elif isinstance(raw_conns, dict):
            for src_id, handles in raw_conns.items():
                if isinstance(handles, dict):
                    for handle_name, targets in handles.items():
                        for group in targets:
                            if isinstance(group, list):
                                for tgt in group:
                                    norm_conns.append({
                                        "source": src_id,
                                        "sourceHandle": handle_name,
                                        "target": tgt.get("node") if isinstance(tgt, dict) else str(tgt),
                                        "targetHandle": tgt.get("type", "main") if isinstance(tgt, dict) else "main",
                                    })
                            elif isinstance(group, dict):
                                norm_conns.append({
                                    "source": src_id,
                                    "sourceHandle": handle_name,
                                    "target": group.get("node", ""),
                                    "targetHandle": group.get("type", "main"),
                                })

        from app.engine.graph import build_graph, validate_graph, topological_sort
        from app.schemas.workflow import Workflow

        wf = Workflow(
            id=data.get("id", "validation-test"),
            name=data.get("name", "Test Workflow"),
            nodes=nodes,
            connections=norm_conns,
        )
        validate_graph(wf)
        graph = build_graph(wf)
        order = topological_sort(graph)
        print(f"Workflow '{wf.name}' is valid.")
        print(f"  Total Nodes: {len(wf.nodes)}")
        print(f"  Execution Sequence: {order}")
        return 0
    except Exception as e:
        print(f"Workflow validation error: {e}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="flowsmith",
        description="FlowSmith Developer CLI & Extensibility SDK.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # connector
    p_conn = sub.add_parser("connector", help="Connector SDK commands")
    sub_conn = p_conn.add_subparsers(dest="subcommand", required=True)

    p_cc = sub_conn.add_parser("create", help="Scaffold a new connector")
    p_cc.add_argument("name", help="Connector name (e.g. Supabase, BigQuery)")
    p_cc.add_argument("--category", default="DEVELOPER_TOOLS", help="Connector category")
    p_cc.set_defaults(func=cmd_connector_create)

    p_cv = sub_conn.add_parser("validate", help="Validate a connector definition")
    p_cv.add_argument("name", help="Connector key or name")
    p_cv.set_defaults(func=cmd_connector_validate)

    # node
    p_node = sub.add_parser("node", help="Node SDK commands")
    sub_node = p_node.add_subparsers(dest="subcommand", required=True)

    p_nc = sub_node.add_parser("create", help="Scaffold a new node")
    p_nc.add_argument("name", help="Node name (e.g. Sentry, MinIO)")
    p_nc.add_argument("--category", default="Actions", help="Node category")
    p_nc.set_defaults(func=cmd_node_create)

    # workflow
    p_wf = sub.add_parser("workflow", help="Workflow verification commands")
    sub_wf = p_wf.add_subparsers(dest="subcommand", required=True)

    p_wv = sub_wf.add_parser("validate", help="Validate a workflow DAG JSON file")
    p_wv.add_argument("file", help="Path to workflow JSON file")
    p_wv.set_defaults(func=cmd_workflow_validate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
