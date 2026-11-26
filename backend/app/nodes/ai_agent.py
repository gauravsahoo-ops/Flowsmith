"""Production-Ready Autonomous AI Agent Node for Flowsmith.

Supports:
1. Multi-provider execution (OpenAI, Anthropic Claude, Gemini, DeepSeek, Groq, Ollama).
2. Native tool calling with multi-turn ReAct reasoning loop.
3. Tri-Tier Memory integration (Working window, Summary buffer, Episodic vector memory).
4. Structured Outputs with JSON Schema enforcement.
5. Rich execution tracing (thoughts, tool calls, arguments, outputs, execution duration).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agents.tool_execution import (
    ToolApprovalRequired,
    execute_tool,
    preflight_tool_call,
)
from app.ai.client import chat_completion
from app.ai.memory import get_memory_manager
from app.ai.tools import TOOLS, openai_tools
from app.engine.errors import NodeCancelledError, NodeExecutionError
from app.engine.node_base import NON_IDEMPOTENT, BaseNode, NodeContext, NodeResult
from app.engine.redact import redact_sensitive
from app.nodes.registry import register
from app.security.crypto import decrypt_text, encrypt_text

logger = logging.getLogger("nodes.ai_agent")

TOOL_APPROVAL_PAUSE_TYPE = "tool_approval"
APPROVAL_STORAGE_KEY = "_approval_data"


class AgentParams(BaseModel):
    instructions: str = Field(
        default=(
            "You are Flowsmith's autonomous platform intelligence and supercomputer agent. "
            "You have full programmatic control over the workflow canvas, executions, Data Tables, "
            "and external HTTP/database systems. You can inspect the canvas, add, update, wire, and delete nodes, "
            "launch workflow runs, inspect execution traces and step outputs, query and modify relational Data Tables, "
            "and check platform system health. Always inspect existing workflow state before and after modifying the canvas."
        ),
        description="System instructions and persona.",
    )
    input: str = Field(
        default="",
        description="Task or user prompt for the agent (supports {{ }} expressions).",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override (e.g. gpt-4o, claude-3-5-sonnet, gemini-2.0-flash, llama-3.3-70b).",
    )
    tools: list[str] = Field(
        default_factory=lambda: [
            "current_time",
            "calculator",
            "http_request",
            "database_query",
            "vector_search",
            "workflow_get",
            "workflow_add_node",
            "workflow_update_node",
            "workflow_connect_nodes",
            "workflow_delete_node",
            "workflow_run",
            "workflow_get_execution",
            "datatable_list",
            "datatable_query",
            "datatable_insert_row",
            "platform_list_connectors",
            "platform_system_health",
        ],
        description="Tools available to the agent.",
    )
    allow_builtin_fallback: bool = Field(
        default=False,
        description="Deprecated/no effect: built-in LLM fallback has been removed; an LLM credential is required.",
    )
    memory_type: str = Field(
        default="window",
        pattern="^(complete|window|summary|episodic|entity|scratchpad|none)$",
        description="Memory tier: complete (multi-tier), window (sliding), summary (compressed), episodic (semantic), entity (facts), scratchpad, or none.",
    )
    session_id: str = Field(
        default="default",
        description="Session identifier for persisting conversation context across runs.",
    )
    max_iterations: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Maximum reasoning/tool loops before terminating.",
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    response_format: str = Field(
        default="text",
        pattern="^(text|json)$",
        description="Desired final format: text or structured json.",
    )
    tool_approval_approvers: list[int] = Field(
        default_factory=list,
        description=(
            "User IDs allowed to approve gated tool calls. Empty means any "
            "user with edit access to the workflow."
        ),
    )
    tool_approval_timeout_hours: int = Field(
        default=24,
        ge=0,
        description=(
            "Hours before a pending tool approval auto-rejects. 0 means no "
            "timeout."
        ),
    )
    tool_approval_separation_of_duties: bool = Field(
        default=False,
        description=(
            "Require an approver other than the run's requesting user. "
            "Disabled by default so single-operator workflows remain usable."
        ),
    )


@register
class AIAgentNode(BaseNode[AgentParams]):
    node_type = "ai_agent"
    display_name = "AI Agent"
    version = 2
    description = "Autonomous ReAct agent with native tool execution, multi-provider support, and persistent memory."
    category = "AI"
    icon = "ai_agent"
    parameters_schema = AgentParams
    credential_types = ["llm", "http", "database"]
    idempotency = NON_IDEMPOTENT

    @staticmethod
    def _extract_final_answer(content: str | None) -> str | None:
        """Extract final answer string from LLM response text or JSON payload."""
        if not content or not content.strip():
            return None
        text = content.strip()

        # 1. Strip markdown fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # 2. Try parsing entire text as JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                if data.get("action") == "final":
                    return str(data.get("answer", ""))
                if "action" in data and data["action"] != "final":
                    return None
                if "answer" in data:
                    return str(data["answer"])
        except Exception:
            pass

        # 3. Look for embedded JSON object with {"action": "final", ...}
        start_idx = text.find("{")
        while start_idx != -1:
            for end_idx in range(len(text), start_idx, -1):
                if text[end_idx - 1] == "}":
                    candidate = text[start_idx:end_idx]
                    try:
                        data = json.loads(candidate)
                        if isinstance(data, dict):
                            if data.get("action") == "final":
                                return str(data.get("answer", ""))
                            if "action" in data and data["action"] != "final":
                                return None
                    except Exception:
                        pass
            start_idx = text.find("{", start_idx + 1)

        return None

    @staticmethod
    def _parse_tool_call(tc: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any]]:
        fn = tc.get("function") or {}
        name = str(fn.get("name", ""))
        raw_args = fn.get("arguments") or "{}"
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {"raw": raw_args}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {"raw": raw_args}
        return tc, name, args if isinstance(args, dict) else {"raw": args}

    @staticmethod
    def _stored_pause_state(ctx: NodeContext) -> dict[str, Any]:
        """Read the encrypted pause blob from the execution row.

        Used as a fallback for resumes queued before the state was mirrored
        into ``_approval_data``. The node normally receives the blob in the
        resume payload.
        """
        from sqlalchemy import select

        from app.db import get_session
        from app.models import Execution

        db = get_session()
        try:
            row = db.execute(
                select(Execution).where(Execution.id == ctx.execution_id)
            ).scalar_one_or_none()
            return dict(row.pause_state or {}) if row is not None else {}
        finally:
            db.close()

    def _load_tool_resume_state(
        self, ctx: NodeContext, decision: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Validate and decrypt a mid-ReAct-loop resume payload.

        Returns ``None`` for node-level approvals so the agent starts a normal
        turn. A rejected tool approval becomes ``APPROVAL_REJECTED`` so the run
        history records a deliberate decision rather than executing the tool.
        """
        if not isinstance(decision, dict):
            return None
        decision_node = decision.get("node_id")
        if decision_node is not None and str(decision_node) != str(ctx.node_id or ""):
            # A decision recorded for another node (e.g. an upstream human
            # gate in the same resumed run) must not be consumed here.
            return None
        if decision.get("pause_type") != TOOL_APPROVAL_PAUSE_TYPE:
            return None
        if not bool(decision.get("approved")):
            raise NodeExecutionError(
                "The gated tool call was rejected by the approver.",
                code="APPROVAL_REJECTED",
                node_id=self.node_type,
                retryable=False,
            )

        blob = decision.get("state")
        if not blob:
            blob = self._stored_pause_state(ctx).get("state")
        if not blob:
            raise NodeExecutionError(
                "The tool approval is missing its encrypted ReAct state.",
                code="TOOL_APPROVAL_STATE_MISSING",
                node_id=self.node_type,
                retryable=False,
            )
        try:
            state = json.loads(decrypt_text(blob))
        except Exception as exc:
            raise NodeExecutionError(
                "The tool approval state could not be decrypted.",
                code="TOOL_APPROVAL_STATE_INVALID",
                node_id=self.node_type,
                retryable=False,
            ) from exc
        if not isinstance(state, dict):
            raise NodeExecutionError(
                "The tool approval state is malformed.",
                code="TOOL_APPROVAL_STATE_INVALID",
                node_id=self.node_type,
                retryable=False,
            )
        expected_node = str(ctx.node_id or "")
        if (
            state.get("execution_id") != ctx.execution_id
            or str(state.get("node_id") or "") != expected_node
        ):
            raise NodeExecutionError(
                "The tool approval state does not belong to this execution step.",
                code="TOOL_APPROVAL_STATE_MISMATCH",
                node_id=self.node_type,
                retryable=False,
            )
        tool_calls = state.get("tool_calls")
        pending_index = state.get("pending_index")
        if (
            not isinstance(tool_calls, list)
            or not isinstance(pending_index, int)
            or not 0 <= pending_index < len(tool_calls)
        ):
            raise NodeExecutionError(
                "The tool approval state has no pending tool call.",
                code="TOOL_APPROVAL_STATE_INVALID",
                node_id=self.node_type,
                retryable=False,
            )
        return state

    async def _pause_for_tool_approval(
        self,
        ctx: NodeContext,
        params: AgentParams,
        required: ToolApprovalRequired,
        *,
        state: dict[str, Any],
    ) -> NodeResult:
        """Persist an encrypted ReAct checkpoint and a durable approval record.

        The pause row is committed before the approval record is created, so a
        broker failure can never cause the gated tool to run. On resume the
        worker re-enters this node, restores ``messages``/trace/tool cursor,
        executes exactly the approved call, and continues the loop.
        """
        from sqlalchemy import select

        from app.db import get_session
        from app.models import Execution

        now = datetime.now(UTC).isoformat()
        state = {
            **state,
            "execution_id": ctx.execution_id,
            "workflow_id": ctx.workflow_id,
            "node_id": str(ctx.node_id or ""),
            "tool_name": required.tool_name,
            "arguments": required.arguments,
            "paused_at": now,
        }
        blob = encrypt_text(
            json.dumps(state, default=str, separators=(",", ":"))
        ).decode("ascii")
        message = (
            f"Agent wants to run '{required.tool_name}' "
            f"({required.risk_class.replace('_', ' ')}); human approval is "
            "required before this tool can execute."
        )
        timeout_hours = max(0, int(params.tool_approval_timeout_hours))
        pause_state: dict[str, Any] = {
            "type": TOOL_APPROVAL_PAUSE_TYPE,
            "node_id": str(ctx.node_id or ""),
            "tool_name": required.tool_name,
            "arguments": redact_sensitive(required.arguments),
            "message": message,
            "approvers": list(params.tool_approval_approvers),
            "timeout_hours": timeout_hours,
            "paused_at": now,
            "risk_class": required.risk_class,
            "risk_tier": required.risk_tier,
            "quorum": required.quorum,
            "iteration": int(state.get("iteration") or 0) + 1,
            "state": blob,
            "approval_id": None,
        }

        db = get_session()
        try:
            execution = db.execute(
                select(Execution).where(Execution.id == ctx.execution_id)
            ).scalar_one_or_none()
            if execution is None:
                raise NodeExecutionError(
                    "Cannot pause for tool approval: execution record not found.",
                    code="TOOL_APPROVAL_PERSIST_FAILED",
                    node_id=self.node_type,
                    retryable=False,
                )
            if execution.status in ("cancelling", "cancelled"):
                raise NodeCancelledError(ctx.node_id)
            existing = execution.pause_state or {}
            if (
                execution.status == "waiting_approval"
                and existing.get("node_id") not in (None, pause_state["node_id"])
            ):
                raise NodeExecutionError(
                    "Another approval pause is already active for this run.",
                    code="APPROVAL_PAUSE_CONFLICT",
                    node_id=self.node_type,
                    retryable=False,
                )

            workflow_id = execution.workflow_id
            organization_id = execution.organization_id
            workspace_id = execution.workspace_id
            requested_by = execution.user_id
            # Durable nested approvals: the checkpoint stays on this run's
            # row, but the root ApprovalRequest belongs to the top-level
            # execution that owns the resume authority.
            owner = ctx.approval_owner if isinstance(ctx.approval_owner, dict) else {}

            def _owner(key: str, fallback: Any) -> Any:
                return owner[key] if key in owner else fallback

            approval_run_id = owner.get("run_id") or ctx.execution_id
            approval_node_id = owner.get("node_id") or pause_state["node_id"]
            workflow_id = _owner("workflow_id", workflow_id)
            organization_id = _owner("organization_id", organization_id)
            workspace_id = _owner("workspace_id", workspace_id)
            requested_by = _owner("requested_by", requested_by)
            execution.status = "waiting_approval"
            execution.pause_state = pause_state
            execution.node_statuses = {
                **(execution.node_statuses or {}),
                pause_state["node_id"]: "waiting_approval",
            }
            db.commit()

            try:
                from app.approvals import service as approvals
                from app.models import ApprovalRequest

                pending = db.execute(
                    select(ApprovalRequest).where(
                        ApprovalRequest.run_id == approval_run_id,
                        ApprovalRequest.node_id == approval_node_id,
                        ApprovalRequest.status == "pending",
                    )
                ).scalars().first()
                if pending is None:
                    request = approvals.create_request(
                        db,
                        run_id=approval_run_id,
                        node_id=approval_node_id,
                        workflow_id=workflow_id,
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        reason=message,
                        summary=f"Agent tool approval: {required.tool_name}",
                        tool_name=required.tool_name,
                        risk_tier=required.risk_tier,
                        arguments=required.arguments,
                        requested_by=requested_by,
                        approvers=list(params.tool_approval_approvers),
                        quorum=required.quorum,
                        # Teams can require an independent approver; the
                        # default keeps single-operator workflows usable.
                        separation_of_duties=bool(
                            params.tool_approval_separation_of_duties
                        ),
                        ttl_seconds=(
                            timeout_hours * 3600 if timeout_hours > 0 else 30 * 86400
                        ),
                    )
                    pause_state["approval_id"] = request.id
                else:
                    pause_state["approval_id"] = pending.id
                execution.pause_state = pause_state
                db.commit()
            except Exception:
                logger.warning(
                    "Could not create a durable approval request for execution %s node %s",
                    ctx.execution_id,
                    pause_state["node_id"],
                    exc_info=True,
                )
                db.rollback()
        finally:
            db.close()

        ctx.emit_event(
            "node.waiting_approval",
            node_id=pause_state["node_id"],
            status="waiting_approval",
            tool_name=required.tool_name,
            approval_id=pause_state.get("approval_id"),
            risk_tier=required.risk_tier,
        )
        return NodeResult(
            output_items=[],
            metadata={
                "waiting_approval": True,
                "type": TOOL_APPROVAL_PAUSE_TYPE,
                "tool_name": required.tool_name,
                "message": message,
                "approvers": list(params.tool_approval_approvers),
                "timeout_hours": timeout_hours,
                "risk_tier": required.risk_tier,
                "approval_id": pause_state.get("approval_id"),
                # Runtime fallback: if the node's pause row was not visible to
                # the execution finalizer, it can still persist this state.
                "pause_state": pause_state,
            },
        )

    async def run(
        self,
        ctx: NodeContext,
        params: AgentParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        llm_cred = ctx.credentials.get("llm")
        if not llm_cred:
            raise NodeExecutionError(
                "The AI Agent node requires a configured 'llm' credential. "
                "Built-in/offline LLM fallback has been removed.",
                code="CREDENTIALS_REQUIRED",
                node_id=self.node_type,
                retryable=False,
            )

        # Clone cred and apply model override if set
        effective_cred = dict(llm_cred)
        if params.model:
            effective_cred["model"] = params.model
        elif effective_cred.get("selected_model"):
            effective_cred["model"] = effective_cred["selected_model"]

        # Determine prompt / user input
        user_input = params.input.strip()
        if not user_input and input_items:
            first_item = input_items[0]
            user_input = first_item.get("prompt") or first_item.get("text") or first_item.get("input") or json.dumps(first_item)

        if not user_input:
            user_input = "Hello! What can you help me with?"

        # Resolve available tools
        declared_tools = [t for t in params.tools if t in TOOLS]
        active_tools_schema = openai_tools(declared_tools)

        # A resumed tool approval restores the encrypted ReAct checkpoint. The
        # pending call is executed with approval_granted=True; the rest of the
        # batch then continues (and pauses again if another call is gated).
        resume_decision = await ctx.storage.get(APPROVAL_STORAGE_KEY)
        resume_state = self._load_tool_resume_state(ctx, resume_decision)

        # Handle Multi-Tier Memory
        mem_manager = get_memory_manager()
        session_key = (
            f"{ctx.workflow_id}_{params.session_id}"
            if getattr(ctx, "workflow_id", None)
            else params.session_id
        )

        messages: list[dict[str, Any]]
        execution_trace: list[dict[str, Any]]
        tools_used_set: set[str]
        step_trace: dict[str, Any] = {}
        tool_calls: list[dict[str, Any]] = []
        pending_index = -1

        if resume_state is not None:
            messages = list(resume_state.get("messages") or [])
            user_input = str(resume_state.get("user_input") or user_input)
            execution_trace = list(resume_state.get("execution_trace") or [])
            tools_used_set = set(resume_state.get("tools_used") or [])
            step_trace = dict(resume_state.get("step_trace") or {})
            tool_calls = list(resume_state.get("tool_calls") or [])
            pending_index = int(resume_state["pending_index"])
        else:
            # Initialize conversation messages
            messages = [
                {"role": "system", "content": params.instructions},
            ]

            if params.memory_type == "complete":
                complete_mem = await mem_manager.get_complete_memory(session_key)
                context_prompt = await complete_mem.format_prompt_context(query=user_input)
                if context_prompt:
                    messages.append({"role": "system", "content": context_prompt})
                messages.extend(complete_mem.working.get_messages())
            elif params.memory_type == "window":
                working_mem = await mem_manager.get_working_memory(session_key)
                messages.extend(working_mem.get_messages())
            elif params.memory_type == "summary":
                summary_mem = await mem_manager.get_summary_memory(session_key)
                messages.extend(summary_mem.get_messages())
            elif params.memory_type == "episodic":
                episodic_mem = await mem_manager.get_episodic_memory(session_key)
                recalled = await episodic_mem.recall_relevant_memories(user_input, top_k=3)
                if recalled:
                    messages.append({
                        "role": "system",
                        "content": "[Relevant Historical Memories]:\n" + "\n- ".join(recalled),
                    })
            elif params.memory_type == "entity":
                complete_mem = await mem_manager.get_complete_memory(session_key)
                entities = complete_mem.entities.get_all()
                if entities:
                    ent_lines = [f"- {k}: {v}" for k, v in entities.items()]
                    messages.append({"role": "system", "content": "[Known Entities & Facts]:\n" + "\n".join(ent_lines)})
                messages.extend(complete_mem.working.get_messages())
            elif params.memory_type == "scratchpad":
                complete_mem = await mem_manager.get_complete_memory(session_key)
                notes = complete_mem.scratchpad.list_notes()
                if notes:
                    note_lines = [f"- {n['key']}: {n['content']}" for n in notes]
                    messages.append({"role": "system", "content": "[Working Scratchpad Notes]:\n" + "\n".join(note_lines)})
                messages.extend(complete_mem.working.get_messages())

            # Append current user prompt
            messages.append({"role": "user", "content": user_input})
            execution_trace = []
            tools_used_set = set()

        final_answer: str | None = None
        structured_json: Any = None

        def _record_tool_result(
            tc: dict[str, Any],
            t_name: str,
            t_args: dict[str, Any],
            tool_output: str,
            tool_duration: float,
        ) -> None:
            tools_used_set.add(t_name)
            step_trace.setdefault("tool_calls", []).append({
                "name": t_name,
                "arguments": t_args,
                "output": tool_output[:1000],
                "duration_ms": tool_duration,
            })
            # Compact tool output fed back to LLM context to prevent token explosion
            llm_content = tool_output if len(tool_output) <= 1500 else tool_output[:1500] + "... (truncated)"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "name": t_name,
                "content": llm_content,
            })

        async def _execute_resumed_batch(state: dict[str, Any]) -> NodeResult | None:
            """Finish the tool batch that was interrupted by an approval pause."""
            for idx in range(pending_index, len(tool_calls)):
                tc, t_name, t_args = self._parse_tool_call(tool_calls[idx])
                if idx != pending_index:
                    try:
                        preflight_tool_call(
                            ctx, t_name, t_args, declared_tools=declared_tools
                        )
                    except ToolApprovalRequired as required:
                        return await self._pause_for_tool_approval(
                            ctx,
                            params,
                            required,
                            state={
                                "iteration": int(state.get("iteration") or 0),
                                "messages": messages,
                                "execution_trace": execution_trace,
                                "tools_used": sorted(tools_used_set),
                                "step_trace": step_trace,
                                "tool_calls": tool_calls,
                                "pending_index": idx,
                                "user_input": user_input,
                            },
                        )
                tool_start = time.monotonic()
                try:
                    tool_output = await execute_tool(
                        ctx,
                        t_name,
                        t_args,
                        declared_tools=declared_tools,
                        policy_enabled=(
                            True if idx == pending_index else None
                        ),
                        approval_granted=(idx == pending_index),
                        raise_on_approval=True,
                    )
                except ToolApprovalRequired as required:
                    return await self._pause_for_tool_approval(
                        ctx,
                        params,
                        required,
                        state={
                            "iteration": int(state.get("iteration") or 0),
                            "messages": messages,
                            "execution_trace": execution_trace,
                            "tools_used": sorted(tools_used_set),
                            "step_trace": step_trace,
                            "tool_calls": tool_calls,
                            "pending_index": idx,
                            "user_input": user_input,
                        },
                    )
                except Exception as t_err:
                    tool_output = f"Tool '{t_name}' execution error: {t_err}"
                _record_tool_result(
                    tc,
                    t_name,
                    t_args,
                    tool_output,
                    round((time.monotonic() - tool_start) * 1000, 2),
                )
            execution_trace.append(step_trace)
            return None

        iteration = 0
        # A durable pause must not consume the agent's reasoning budget: the
        # approved tool result still needs one model turn to be synthesized.
        max_iterations = params.max_iterations + (
            1 if resume_state is not None else 0
        )
        if resume_state is not None:
            paused_result = await _execute_resumed_batch(resume_state)
            if paused_result is not None:
                return paused_result
            iteration = int(resume_state.get("iteration") or 0) + 1

        # ReAct loop
        while iteration < max_iterations:
            step_start = time.monotonic()
            try:
                msg = await chat_completion(
                    effective_cred,
                    messages=messages,
                    tools=active_tools_schema if active_tools_schema else None,
                    temperature=params.temperature,
                )
            except Exception as exc:
                raise NodeExecutionError(
                    f"Agent LLM turn failed on iteration {iteration + 1}: {exc}",
                    code="AGENT_LLM_ERROR",
                    node_id=self.node_type,
                ) from exc

            messages.append(msg)
            tool_calls = msg.get("tool_calls") or []
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""

            step_trace = {
                "iteration": iteration + 1,
                "thought": content or reasoning,
                "tool_calls": [],
                "duration_ms": round((time.monotonic() - step_start) * 1000, 2),
            }

            # If no tool calls, model has reached final answer!
            if not tool_calls:
                extracted = self._extract_final_answer(content)
                final_answer = extracted if extracted is not None else content
                step_trace["thought"] = final_answer
                execution_trace.append(step_trace)
                break

            # Preflight the whole batch before executing any call. A gated call
            # pauses the run without producing partial side effects from its
            # siblings.
            parsed_calls = [self._parse_tool_call(tc) for tc in tool_calls]
            for idx, (_tc, t_name, t_args) in enumerate(parsed_calls):
                try:
                    preflight_tool_call(
                        ctx, t_name, t_args, declared_tools=declared_tools
                    )
                except ToolApprovalRequired as required:
                    return await self._pause_for_tool_approval(
                        ctx,
                        params,
                        required,
                        state={
                            "iteration": iteration,
                            "messages": messages,
                            "execution_trace": execution_trace,
                            "tools_used": sorted(tools_used_set),
                            "step_trace": step_trace,
                            "tool_calls": tool_calls,
                            "pending_index": idx,
                            "user_input": user_input,
                        },
                    )

            # Execute tool calls concurrently using asyncio.gather for speed
            async def _run_single_tool(tc: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any], str, float]:
                tc, t_name, t_args = self._parse_tool_call(tc)

                tool_start = time.monotonic()
                try:
                    tool_output = await execute_tool(
                        ctx, t_name, t_args, declared_tools=declared_tools
                    )
                except Exception as t_err:
                    tool_output = f"Tool '{t_name}' execution error: {t_err}"

                tool_duration = round((time.monotonic() - tool_start) * 1000, 2)
                return tc, t_name, t_args, tool_output, tool_duration

            tool_results = await asyncio.gather(*[_run_single_tool(tc) for tc in tool_calls])

            for tc, t_name, t_args, tool_output, tool_duration in tool_results:
                _record_tool_result(tc, t_name, t_args, tool_output, tool_duration)

            execution_trace.append(step_trace)
            iteration += 1

        if final_answer is None:
            raise NodeExecutionError(
                f"Agent reached max iterations ({params.max_iterations}) without producing a final answer.",
                code="AI_MAX_ITERATIONS",
                node_id=self.node_type,
            )

        # Parse JSON if response_format is json
        if params.response_format == "json":
            try:
                # Find JSON block if wrapped in markdown fences
                cleaned = final_answer.strip()
                if "```json" in cleaned:
                    cleaned = cleaned.split("```json")[1].split("```")[0].strip()
                elif "```" in cleaned:
                    cleaned = cleaned.split("```")[1].split("```")[0].strip()
                structured_json = json.loads(cleaned)
            except Exception:
                structured_json = {"raw": final_answer}

        # Update persistent memory
        if params.memory_type == "complete":
            comp_mem = await mem_manager.get_complete_memory(session_key)
            await comp_mem.record_turn(
                user_content=user_input,
                assistant_content=final_answer,
                llm_func=chat_completion,
                llm_cred=effective_cred,
            )
        elif params.memory_type == "window":
            mem = await mem_manager.get_working_memory(session_key)
            mem.add_message("user", user_input)
            mem.add_message("assistant", final_answer)
        elif params.memory_type == "summary":
            mem_sum = await mem_manager.get_summary_memory(session_key)
            mem_sum.add_message("user", user_input)
            mem_sum.add_message("assistant", final_answer)
            await mem_sum.compress_if_needed(chat_completion, effective_cred)
        elif params.memory_type == "episodic":
            mem_epi = await mem_manager.get_episodic_memory(session_key)
            await mem_epi.store_memory(f"User asked: {user_input} | Answer: {final_answer[:200]}")
        elif params.memory_type == "entity":
            comp_mem = await mem_manager.get_complete_memory(session_key)
            comp_mem.entities.extract_from_text(user_input)
            comp_mem.entities.extract_from_text(final_answer)
            comp_mem.working.add_message("user", user_input)
            comp_mem.working.add_message("assistant", final_answer)
        elif params.memory_type == "scratchpad":
            comp_mem = await mem_manager.get_complete_memory(session_key)
            comp_mem.scratchpad.set(f"turn_{int(time.time())}", final_answer[:300])
            comp_mem.working.add_message("user", user_input)
            comp_mem.working.add_message("assistant", final_answer)

        if params.memory_type != "none":
            await mem_manager.save_session_to_disk(session_key)

        # Assemble clean output item
        output_payload: dict[str, Any] = {
            "result": structured_json if structured_json is not None else final_answer,
            "output": structured_json if structured_json is not None else final_answer,
            "final_answer": final_answer,
            "tools_used": sorted(tools_used_set),
            "iterations": len(execution_trace),
            "trace": execution_trace,
            "session_id": params.session_id,
        }
        if structured_json is not None:
            output_payload["json"] = structured_json

        return NodeResult(output_items=[output_payload])
