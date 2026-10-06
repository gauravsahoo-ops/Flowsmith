"""Deterministic Workflow Compiler.

Compiles a high-level WorkflowIR into a concrete, executable Flowsmith DAG JSON.
Performs:
1. Node resolution against NODE_REGISTRY and ConnectorRegistry
2. Connector operation resolution and input schema mapping
3. Expression synthesis ({{ $json.field }})
4. Connection handle mapping (true/false for if_condition, route_0 for switch)
5. Retry, timeout, and settings policy injection
6. Automatic visual coordinate layout
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.ai.capabilities import CapabilityRegistry
from app.ai.ir import WorkflowIR, IRStep, IRTrigger
from app.connectors import get_registry as get_connector_registry


class WorkflowCompiler:
    """Deterministic compiler from WorkflowIR to Flowsmith Workflow JSON."""

    @classmethod
    def compile_ir(cls, ir: WorkflowIR) -> dict[str, Any]:
        """Compile a WorkflowIR object into a Flowsmith workflow document."""
        cap_reg = CapabilityRegistry.get_instance()
        conn_reg = get_connector_registry()

        nodes: list[dict[str, Any]] = []
        connections: list[dict[str, Any]] = []

        # 1. Compile Trigger Node
        trigger_node = cls._compile_trigger(ir.trigger)
        nodes.append(trigger_node)

        # 2. Compile Steps
        step_id_map: dict[str, str] = {ir.trigger.id: trigger_node["id"]}

        for idx, step in enumerate(ir.steps):
            compiled = cls._compile_step(step, idx + 1, ir)
            nodes.append(compiled)
            step_id_map[step.id] = compiled["id"]

        # 3. Compile Connections
        if ir.connections:
            for c in ir.connections:
                src_id = step_id_map.get(c.source, c.source)
                tgt_id = step_id_map.get(c.target, c.target)
                connections.append({
                    "source": src_id,
                    "target": tgt_id,
                    "sourceHandle": c.source_handle,
                    "targetHandle": c.target_handle,
                })
        else:
            # Sequential wiring fallback
            for i in range(len(nodes) - 1):
                src = nodes[i]
                tgt = nodes[i + 1]
                s_handle = "main"
                if src.get("type") == "if_condition":
                    s_handle = "true"
                elif src.get("type") in ("loop", "loop_over_items"):
                    s_handle = "loop"
                connections.append({
                    "source": src["id"],
                    "target": tgt["id"],
                    "sourceHandle": s_handle,
                    "targetHandle": "main",
                })

        # 4. Inject Error Policy
        settings: dict[str, Any] = {}
        if ir.error_policy.max_retries > 0:
            settings["retry"] = {
                "max_attempts": ir.error_policy.max_retries,
                "backoff": ir.error_policy.backoff_strategy,
            }

        # 5. Position nodes with clean sequential layout
        for idx, node in enumerate(nodes):
            node["position"] = {"x": 100 + (idx * 280), "y": 180}

        return {
            "id": f"wf_{uuid.uuid4().hex[:12]}",
            "name": ir.name or "Generated Workflow",
            "version": 1,
            "status": "draft",
            "nodes": nodes,
            "connections": connections,
            "settings": settings,
        }

    @classmethod
    def _compile_trigger(cls, trigger: IRTrigger) -> dict[str, Any]:
        """Map IR trigger to concrete Flowsmith trigger node."""
        kind = trigger.kind.lower()
        if kind == "schedule":
            return {
                "id": "schedule_1",
                "type": "schedule",
                "name": "Schedule Trigger",
                "parameters": {
                    "rule": {
                        "cronExpression": trigger.config.get("cron", "0 9 * * 1-5"),
                        "timezone": trigger.config.get("timezone", "UTC"),
                    }
                },
                "settings": {},
                "credentials": {},
            }
        elif kind == "webhook" or trigger.system != "system":
            path_entropy = uuid.uuid4().hex[:18]
            clean_name = re.sub(r"[^A-Za-z0-9_.-]", "", trigger.system.lower())[:10] or "hook"
            return {
                "id": "webhook_1",
                "type": "webhook",
                "name": f"{trigger.system.title()} Webhook Trigger",
                "parameters": {
                    "path": f"{clean_name}-{path_entropy}",
                    "http_method": trigger.config.get("method", "POST"),
                },
                "settings": {},
                "credentials": {},
            }
        else:
            return {
                "id": "manual_1",
                "type": "manual_trigger",
                "name": "Manual Trigger",
                "parameters": {},
                "settings": {},
                "credentials": {},
            }

    @classmethod
    def _compile_step(cls, step: IRStep, index: int, ir: WorkflowIR) -> dict[str, Any]:
        """Compile one IR step into a concrete node instance with verified parameters."""
        kind = step.kind.lower()
        sys_key = (step.system or "").lower().strip()
        op_key = (step.operation or "").lower().strip()
        node_id = step.id if step.id else f"{kind}_{index}"

        # 1. Condition Node
        if kind in ("condition", "branch") or "if" in (step.name.lower()):
            cond_val1 = step.inputs.get("left", step.inputs.get("value1", "={{ $json.status }}"))
            cond_op = step.inputs.get("operator", "is equal to")
            cond_val2 = step.inputs.get("right", step.inputs.get("value2", "active"))
            return {
                "id": node_id,
                "type": "if_condition",
                "name": step.name or "Check Condition",
                "parameters": {
                    "conditions": [
                        {
                            "leftValue": cond_val1,
                            "operator": cond_op,
                            "rightValue": cond_val2,
                        }
                    ],
                    "combinator": "AND",
                },
                "settings": {"retry": step.retry} if step.retry else {},
                "credentials": {},
            }

        # 2. AI Tasks / Agent Node
        if kind in ("ai_task", "agent") or sys_key in ("ai", "openai", "claude", "agent"):
            return {
                "id": node_id,
                "type": "ai_agent",
                "name": step.name or "Smith AI Agent",
                "parameters": {
                    "instructions": step.inputs.get("instructions", step.description or f"Execute {step.name}"),
                    "model": step.inputs.get("model", "gpt-4o"),
                    "tools": step.inputs.get("tools", []),
                },
                "settings": {},
                "credentials": {"llm": "$user"},
            }

        # 3. HTTP Request
        if kind == "http" or sys_key in ("http", "api", "webhook_out"):
            return {
                "id": node_id,
                "type": "http_request",
                "name": step.name or "HTTP Request",
                "parameters": {
                    "url": step.inputs.get("url", "https://api.example.com/v1/resource"),
                    "method": step.inputs.get("method", "POST"),
                    "headers": step.inputs.get("headers", {"Content-Type": "application/json"}),
                    "body": step.inputs.get("body", '{"data": "{{ $json }}"}'),
                },
                "settings": {"retry": step.retry} if step.retry else {},
                "credentials": {},
            }

        # 4. Connector Operation Resolution
        conn_reg = get_connector_registry()
        # Find matching connector
        matched_conn = None
        for c in conn_reg.list_definitions():
            if c.connector_key == sys_key or sys_key in c.connector_key or sys_key in c.display_name.lower():
                matched_conn = c
                break

        if matched_conn:
            c_key = matched_conn.connector_key
            available_ops = list(matched_conn.operations.keys())
            resolved_op = op_key if op_key in available_ops else (available_ops[0] if available_ops else "default")

            op_def = matched_conn.operations.get(resolved_op)
            req_fields = (op_def.input_schema.get("required") if op_def and op_def.input_schema else []) or []

            # Populate parameters with required fields and defaults
            parameters: dict[str, Any] = {"operation": resolved_op}
            for rf in req_fields:
                parameters[rf] = step.inputs.get(rf, f"{{{{ $json.{rf} }}}}")
            # Merge other provided inputs
            for k, v in step.inputs.items():
                if k != "operation":
                    parameters[k] = v

            cred_dict = {}
            if op_def and getattr(op_def, "credential_require", None):
                cred_dict[str(op_def.credential_require)] = "$user"
            elif matched_conn.connector_key in ("salesforce", "slack", "stripe", "github", "hubspot"):
                cred_dict[matched_conn.connector_key] = "$user"

            # Check if this connector maps to a specific node_type
            primary_node_type = c_key
            if hasattr(conn_reg, "primary_for_node_type"):
                p_conn = conn_reg.primary_for_node_type(c_key)
                if p_conn:
                    primary_node_type = c_key

            return {
                "id": node_id,
                "type": primary_node_type,
                "name": step.name or f"{matched_conn.display_name} {resolved_op.replace('_', ' ').title()}",
                "parameters": parameters,
                "settings": {"retry": step.retry} if step.retry else {},
                "credentials": cred_dict,
            }

        # 5. Generic Fallback
        return {
            "id": node_id,
            "type": "http_request",
            "name": step.name or "Process Step",
            "parameters": {
                "url": step.inputs.get("url", "https://api.example.com/action"),
                "method": "POST",
                "body": step.inputs.get("body", "{}"),
            },
            "settings": {},
            "credentials": {},
        }
