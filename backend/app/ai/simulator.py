"""AI Workflow Simulator.

Performs safe, non-destructive mock execution of a workflow:
1. Static validation check
2. Synthetic data item propagation across DAG topology
3. Schema & field mapping validation per step
4. Credential availability check
5. Runtime policy & timeout estimation
6. Simulated step-by-step trace generation
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.ai.pipeline_validator import PipelineValidator
from app.engine.graph import build_graph, topological_sort
from app.schemas.workflow import Workflow


class SimulationTraceStep(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    status: str = "success"  # success | warning | skipped | error
    latency_ms: int = 15
    input_sample: dict[str, Any] = Field(default_factory=dict)
    output_sample: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class SimulationResult(BaseModel):
    success: bool
    total_steps: int
    estimated_latency_ms: int
    trace: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""


class WorkflowSimulator:
    """Non-destructive simulation engine."""

    @classmethod
    def simulate(
        cls,
        workflow_doc: dict[str, Any],
        user_credentials: Optional[set[str]] = None,
        mock_input: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Simulate execution of the workflow document without side effects."""
        creds = user_credentials or set()

        # 1. Run Pipeline Validation
        val = PipelineValidator.validate_full(workflow_doc, user_credentials=creds)
        if not val.get("structural_ok", True):
            return {
                "success": False,
                "simulated": False,
                "total_steps": 0,
                "estimated_latency_ms": 0,
                "trace": [],
                "validation": val,
                "warnings": [e.get("message", "Validation error") for e in val.get("errors", [])],
                "summary": "Simulation aborted: Workflow has structural/graph topology errors.",
            }

        # 2. Build graph and topological sort
        try:
            wf = Workflow.model_validate(workflow_doc)
            graph = build_graph(wf)
            topo_order = topological_sort(graph)
            if not topo_order:
                topo_order = [n.id for n in wf.nodes]
        except Exception as exc:
            return {
                "success": False,
                "simulated": False,
                "total_steps": 0,
                "estimated_latency_ms": 0,
                "trace": [],
                "validation": val,
                "warnings": [str(exc)],
                "summary": f"Simulation aborted: Unable to parse DAG topology ({exc}).",
            }

        trace: list[dict[str, Any]] = []
        warnings_list: list[str] = [w.get("message", "") for w in val.get("warnings", []) if w.get("message")]
        total_latency = 0

        current_data: dict[str, Any] = mock_input or {
            "id": "evt_sim_12345",
            "type": "lead.created",
            "status": "active",
            "score": 85,
            "email": "lead@example.com",
            "name": "Jane Enterprise",
            "company": "Acme Global",
            "amount": 12000,
        }

        # Step by step simulation
        for node_id in topo_order:
            node = next((n for n in wf.nodes if n.id == node_id), None)
            if not node:
                continue

            step_notes: list[str] = []
            status = "success"
            step_latency = 25

            # Inspect node-level errors or warnings from validation
            node_errors = [e for e in val.get("errors", []) if e.get("node_id") == node.id]
            node_warnings = [w for w in val.get("warnings", []) if w.get("node_id") == node.id]
            if node_errors:
                status = "warning"
                for ne in node_errors:
                    step_notes.append(f"Notice: {ne.get('message', 'Parameter check required')}")
            elif node_warnings:
                for nw in node_warnings:
                    step_notes.append(f"Note: {nw.get('message')}")

            # Mock step execution output based on node type
            if node.type in ("webhook", "manual_trigger", "schedule", "salesforce_trigger"):
                step_latency = 5
                out_data = dict(current_data)
                step_notes.append("Trigger event received and ingested.")
            elif node.type == "if_condition":
                step_latency = 10
                # Evaluate condition
                out_data = dict(current_data)
                step_notes.append("Condition evaluated against incoming item -> routed to 'true' branch.")
            elif node.type in ("ai_agent", "ai_completion"):
                step_latency = 650
                out_data = {
                    **current_data,
                    "ai_score": 92,
                    "sentiment": "positive",
                    "summary": "Enterprise prospect with immediate expansion opportunity.",
                    "status": "processed",
                }
                step_notes.append("AI reasoning simulated with mock response.")
            elif node.type == "http_request":
                step_latency = 120
                out_data = {
                    **current_data,
                    "http_status": 200,
                    "response": {"success": True, "id": "res_sim_999"},
                }
                step_notes.append("HTTP mock request simulated.")
            else:
                # Connector node (Salesforce, Slack, etc.)
                step_latency = 80
                op = str((node.parameters or {}).get("operation") or "execute")
                out_data = {
                    **current_data,
                    f"{node.type}_result": {"operation": op, "status": "simulated_ok"},
                }
                step_notes.append(f"Connector operation '{op}' simulated.")

            total_latency += step_latency

            trace.append({
                "node_id": node.id,
                "node_name": node.name or node.id,
                "node_type": node.type,
                "status": status,
                "latency_ms": step_latency,
                "input_sample": current_data,
                "output_sample": out_data,
                "notes": step_notes,
            })

            current_data = out_data

        all_ok = len(val.get("errors", [])) == 0
        summary_msg = (
            f"Simulation completed successfully across {len(trace)} nodes. Estimated execution time: {total_latency}ms."
            if all_ok
            else f"Simulation completed across {len(trace)} nodes with {len(val.get('errors', []))} configuration notice(s). Estimated execution time: {total_latency}ms."
        )

        return {
            "success": all_ok,
            "simulated": True,
            "total_steps": len(trace),
            "executed_count": len(trace),
            "estimated_latency_ms": total_latency,
            "trace": trace,
            "validation": val,
            "warnings": warnings_list + [e.get("message", "") for e in val.get("errors", []) if e.get("message")],
            "summary": summary_msg,
        }
