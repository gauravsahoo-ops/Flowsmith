"""Phase 8 AI endpoints: error assistant, natural-language workflow
generation, provider status.

Both features use the requesting user's first `llm` credential (or an
explicit `credential_id`). Nothing is cached or stored by these
endpoints; generation returns a VALIDATED candidate the client must
explicitly approve (create) — Phase 15: the plan is grounded in the live
node/connector registries and every candidate is checked against
reality before it is shown.
"""

from __future__ import annotations

import json
import logging
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
import httpx
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.client import LLMError, chat_completion
from app.ai.generation import GenerationError, generate_workflow_spec
from app.ai.memory import get_memory_manager
from app.api.access import get_permission
from app.api.auth import get_current_user
from app.api.common import ok
from app.audit import AI_ASSIST, AI_GENERATE, log_event
from app.credentials import service as credential_service
from app.db import get_db
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.models import Execution, User
from app.nodes.ai_agent import AIAgentNode, AgentParams

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = logging.getLogger("api.ai")


def _client_error(exc: LLMError | NodeExecutionError) -> str:
    """Sanitize provider/network errors for API responses: strip query
    strings (they may carry API keys) and cap the length."""
    msg = exc.message
    head, sep, _ = msg.partition("?")
    if sep:
        msg = head + "?[redacted]"
    return msg[:400]


class ExplainRequest(BaseModel):
    execution_id: str = Field(min_length=1)
    credential_id: str | None = None


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    credential_id: str | None = None
    existing_workflow: dict | None = None
    history: list[dict] | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    session_id: str = "default"
    workflow_id: str | None = None
    credential_id: str | None = None
    model: str | None = None
    tools: list[str] | None = None
    instructions: str | None = None
    memory_type: str = "window"
    allow_builtin: bool = False


class EntityUpsertRequest(BaseModel):
    entities: dict[str, Any] = Field(default_factory=dict)
    text_to_extract: str | None = None
    workflow_id: str | None = None


class NoteUpsertRequest(BaseModel):
    key: str
    content: str
    tags: list[str] | None = None
    workflow_id: str | None = None


class SuggestMappingRequest(BaseModel):
    workflow_id: str
    node_id: str
    intent: str = ""
    credential_id: str | None = None


class SuggestExpressionRequest(BaseModel):
    description: str = Field(min_length=3, max_length=2000)
    workflow_id: str | None = None
    node_id: str | None = None
    sample_item: dict | None = None
    credential_id: str | None = None


class SuggestConfigRequest(BaseModel):
    node_type: str
    operation: str | None = None
    intent: str = Field(min_length=1, max_length=4000)
    credential_id: str | None = None


class WorkflowRefRequest(BaseModel):
    workflow_id: str
    credential_id: str | None = None


def _llm_credentials(db: Session, user: User, credential_id: str | None) -> list[dict]:
    allowed_types = ("llm", "openai", "anthropic", "ollama")
    metas = [m for m in credential_service.list_for_user(db, user.id) if m["type"] in allowed_types]
    if credential_id is not None:
        metas = [m for m in metas if m["id"] == credential_id]
    resolved: list[dict] = []
    for meta in metas:
        mtype = meta.get("type", "llm")
        try:
            data = credential_service.resolve_credentials(db, user.id, {mtype: meta["id"]})
            cred_data = data.get(mtype) or data.get("llm") or {}
            cred_dict = {"id": meta["id"], "name": meta.get("name"), **cred_data}
            # Synchronize model and provider fields with dynamic LLM platform
            sel_model = cred_dict.get("selected_model")
            if sel_model:
                cred_dict["model"] = sel_model
            if not cred_dict.get("provider"):
                cred_dict["provider"] = cred_dict.get("provider_id") or mtype
            resolved.append(cred_dict)
        except credential_service.CredentialError:
            continue
    return resolved


def _pick_llm(db: Session, user: User, credential_id: str | None) -> dict:
    if credential_id in ("builtin", "zero-llm"):
        return {"provider": "builtin", "model": "builtin", "api_key": "builtin_local"}
    if credential_id in ("ollama", "local-ollama"):
        return {
            "id": "ollama",
            "name": "Ollama (Local AI)",
            "provider": "ollama",
            "model": "llama3.2:1b",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
        }
    creds = _llm_credentials(db, user, credential_id)
    if not creds:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No usable 'llm' credential on this account. Create one in Credentials first.",
        )
    return creds[0]


@router.get("/status")
def ai_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    creds = _llm_credentials(db, user, None)
    configured = len(creds) > 0

    all_models: list[dict[str, Any]] = [
        {
            "id": "builtin",
            "name": "Zero-LLM (Deterministic Engine)",
            "provider": "builtin",
            "model": "rule-based",
            "type": "builtin",
        },
        {
            "id": "ollama",
            "name": "Local Ollama (Offline AI)",
            "provider": "ollama",
            "model": "llama3.2:1b",
            "type": "local",
        },
    ]

    for c in creds:
        all_models.append({
            "id": c.get("id"),
            "name": c.get("name") or c.get("provider") or "LLM Credential",
            "provider": c.get("provider") or c.get("provider_id") or "openai",
            "model": c.get("selected_model") or c.get("model") or "default",
            "type": "cloud",
        })

    if configured:
        first = creds[0]
        active_info = {
            "id": first.get("id"),
            "name": first.get("name") or "LLM Provider",
            "provider": first.get("provider") or first.get("provider_id") or "openai",
            "model": first.get("selected_model") or first.get("model") or "default",
        }
    else:
        active_info = all_models[0]

    return ok({
        "configured": configured,
        "credentials": [
            {
                "id": c.get("id"),
                "name": c.get("name") or c.get("provider") or "LLM Credential",
                "provider": c.get("provider") or c.get("provider_id") or "openai",
                "model": c.get("selected_model") or c.get("model") or "default",
            }
            for c in creds
        ],
        "models": all_models,
        "active": active_info,
    })


@router.post("/explain")
async def explain_failure(
    body: ExplainRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """AI error assistant: explain the failing step of an execution."""
    rec = db.get(Execution, body.execution_id)
    if rec is None or get_permission(db, rec.workflow_id, user) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Execution not found.")
    steps = rec.trace or []
    failing = [s for s in steps if s.get("status") == "error"]
    if not failing:
        raise HTTPException(status.HTTP_409_CONFLICT, "This execution has no failing step.")

    llm = _pick_llm(db, user, body.credential_id)
    preview = []
    for step in steps[-12:]:
        entry = {
            "node": step.get("node_id"),
            "type": step.get("node_type"),
            "status": step.get("status"),
        }
        if step.get("error"):
            entry["error"] = step["error"]
        if step.get("note"):
            entry["note"] = step["note"]
        preview.append(entry)
    preview.append({"FAILING_STEP": failing[-1].get("error")})

    messages = [
        {
            "role": "system",
            "content": (
                "You are a debugging assistant for a workflow automation platform. "
                "Explain, in plain language (max 150 words), what went wrong in the failing "
                "step and how to fix it. Do not invent details."
            ),
        },
        {"role": "user", "content": json.dumps(preview, ensure_ascii=False)},
    ]
    try:
        message = await chat_completion(llm, messages, temperature=0.2, max_tokens=600)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _client_error(exc))
    return ok({"explanation": message.get("content") or ""})


@router.post("/generate-workflow")
async def generate_workflow(
    body: GenerateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Natural-language workflow generation (Phase 15).

    The planner prompt is rendered from the LIVE node/connector
    registries, and the candidate is validated against reality (node
    existence, operations, parameter schemas, connections, expressions,
    credentials). Returns a PREVIEW — nothing is persisted here; the
    client must explicitly create the workflow (user approval), and it
    is born a draft that never auto-activates.
    """
    try:
        llm = _pick_llm(db, user, body.credential_id)
    except HTTPException:
        llm = {"provider": "builtin", "model": "builtin", "api_key": "builtin_local"}
    available_credentials = {
        meta["type"] for meta in credential_service.list_for_user(db, user.id)
    }
    try:
        result = await generate_workflow_spec(
            body.prompt,
            available_credentials=available_credentials,
            chat=chat_completion,
            llm=llm,
            existing_workflow=body.existing_workflow,
            history=body.history,
        )
    except (GenerationError, LLMError) as exc:
        if llm.get("provider") != "builtin":
            try:
                builtin_llm = {"provider": "builtin", "model": "builtin", "api_key": "builtin_local"}
                result = await generate_workflow_spec(
                    body.prompt,
                    available_credentials=available_credentials,
                    chat=chat_completion,
                    llm=builtin_llm,
                    existing_workflow=body.existing_workflow,
                    history=body.history,
                )
                log_event(db, AI_GENERATE, target_type="ai", user_id=user.id,
                          detail={"prompt": body.prompt[:200], "attempts": result["attempts"], "fallback": "builtin",
                                  "warnings": len(result["validation"]["warnings"])})
                return ok({
                    "workflow": result["workflow"],
                    "validation": result["validation"],
                    "attempts": result["attempts"],
                    "fallback_used": "builtin",
                })
            except Exception:
                pass
        if isinstance(exc, GenerationError):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"message": exc.message, "validation": exc.validation},
            )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _client_error(exc))
    log_event(db, AI_GENERATE, target_type="ai", user_id=user.id,
              detail={"prompt": body.prompt[:200], "attempts": result["attempts"],
                      "warnings": len(result["validation"]["warnings"])})
    return ok({
        "workflow": result["workflow"],
        "validation": result["validation"],
        "attempts": result["attempts"],
        # Approval contract: the candidate is a preview only.
        "created": False,
    })


def _mem_key(user_id: int, workflow_id: str | None, session_id: str) -> str:
    """User-scoped memory namespace.

    Mirrors AIAgentNode's ``workflow_id_session_id`` formula with a ``u{id}:``
    prefix on the session component so no user can read/write another user's
    memory (session ids like the default "default" are globally shared).
    """
    sid = f"u{user_id}:{session_id}"
    return f"{workflow_id}_{sid}" if workflow_id else sid


@router.get("/memory/{session_id}")
async def get_ai_memory(
    session_id: str,
    workflow_id: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    """Inspect active conversation memory for a given session."""
    manager = get_memory_manager()
    key = _mem_key(user.id, workflow_id, session_id)
    info = await manager.get_session_info(key)
    if not info.get("exists") and not workflow_id:
        default_info = await manager.get_session_info(_mem_key(user.id, "default", session_id))
        if default_info.get("exists"):
            return ok(default_info)
    return ok(info)


@router.delete("/memory/{session_id}")
async def clear_ai_memory(
    session_id: str,
    workflow_id: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    """Clear active conversation memory for a given session."""
    manager = get_memory_manager()
    key = _mem_key(user.id, workflow_id, session_id)
    await manager.clear_session(key)
    if not workflow_id:
        await manager.clear_session(_mem_key(user.id, "default", session_id))
    return ok({"cleared": True, "session_id": session_id})


@router.get("/memory/{session_id}/search")
async def search_ai_memory(
    session_id: str,
    q: str,
    top_k: int = 5,
    workflow_id: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    """Semantic and lexical recall across all memory tiers without requiring an external LLM."""
    manager = get_memory_manager()
    key = _mem_key(user.id, workflow_id, session_id)
    comp_mem = await manager.get_complete_memory(key)
    results = await comp_mem.search(q, top_k=top_k)
    return ok({"session_id": session_id, "query": q, "results": results, "count": len(results)})


@router.post("/memory/{session_id}/entities")
async def upsert_ai_memory_entities(
    session_id: str,
    body: EntityUpsertRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Persist structured entity facts or extract entities from text into Complete Memory."""
    manager = get_memory_manager()
    key = _mem_key(user.id, body.workflow_id, session_id)
    comp_mem = await manager.get_complete_memory(key)
    for k, v in body.entities.items():
        comp_mem.entities.set(k, v)
    if body.text_to_extract:
        comp_mem.entities.extract_from_text(body.text_to_extract)
    await manager._persist_to_disk(key, comp_mem)
    return ok({"session_id": session_id, "entities": comp_mem.entities.get_all()})


@router.get("/memory/{session_id}/entities")
async def get_ai_memory_entities(
    session_id: str,
    workflow_id: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    """Retrieve all entity facts stored for this session."""
    manager = get_memory_manager()
    key = _mem_key(user.id, workflow_id, session_id)
    comp_mem = await manager.get_complete_memory(key)
    return ok({"session_id": session_id, "entities": comp_mem.entities.get_all()})


@router.post("/memory/{session_id}/notes")
async def upsert_ai_memory_note(
    session_id: str,
    body: NoteUpsertRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Set working scratchpad note in Complete Memory."""
    manager = get_memory_manager()
    key = _mem_key(user.id, body.workflow_id, session_id)
    comp_mem = await manager.get_complete_memory(key)
    comp_mem.scratchpad.set(body.key, body.content, tags=body.tags)
    await manager._persist_to_disk(key, comp_mem)
    return ok({"session_id": session_id, "saved": True, "key": body.key})


@router.get("/memory/{session_id}/notes")
async def list_ai_memory_notes(
    session_id: str,
    tag: str | None = None,
    workflow_id: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    """List scratchpad working notes."""
    manager = get_memory_manager()
    key = _mem_key(user.id, workflow_id, session_id)
    comp_mem = await manager.get_complete_memory(key)
    notes = comp_mem.scratchpad.list_notes(tag=tag)
    return ok({"session_id": session_id, "notes": notes, "count": len(notes)})


@router.post("/chat")
async def chat_with_agent(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Live interactive chat with Flowsmith's autonomous AI Agent and LLM."""
    is_builtin_requested = body.allow_builtin or (
        body.model is not None and body.model.lower() in ("builtin", "local", "local_ai", "offline")
    )
    if is_builtin_requested:
        try:
            llm = _pick_llm(db, user, body.credential_id)
        except HTTPException:
            llm = {"provider": "builtin", "model": body.model or "builtin", "api_key": "builtin_local"}
    else:
        llm = _pick_llm(db, user, body.credential_id)

    param_kwargs: dict[str, Any] = {
        "input": body.message,
        # User-scoped session so agent memory lands in this user's namespace
        # (same formula as _mem_key, matching AIAgentNode's key composition).
        "session_id": f"u{user.id}:{body.session_id}",
        "memory_type": body.memory_type,
        "allow_builtin_fallback": body.allow_builtin or is_builtin_requested,
    }
    model_choice = body.model or llm.get("selected_model") or llm.get("model") or llm.get("default_model")
    if model_choice:
        param_kwargs["model"] = model_choice
    if body.tools is not None:
        param_kwargs["tools"] = body.tools
    if body.instructions:
        param_kwargs["instructions"] = body.instructions

    params = AgentParams(**param_kwargs)

    async with httpx.AsyncClient(timeout=30.0) as client:
        ctx = NodeContext(
            execution_id=f"chat_{uuid.uuid4().hex[:8]}",
            workflow_id=body.workflow_id or "",
            node_id="ai_chat",
            logger=logging.getLogger("ai.chat"),
            http_client=client,
            credentials={"llm": llm},
            user_id=user.id,
        )
        try:
            res = await AIAgentNode().run(ctx, params, [{"input": body.message}])
        except NodeExecutionError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _client_error(exc))
        except Exception:
            logger.exception("agent execution failed")
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Agent execution failed.")

    output_item = (res.output_items or [{}])[0]
    log_event(
        db,
        AI_ASSIST,
        target_type="ai",
        user_id=user.id,
        detail={"session_id": body.session_id, "prompt": body.message[:100]},
    )

    return ok({
        "response": output_item.get("final_answer") or output_item.get("output") or "",
        "trace": output_item.get("trace") or [],
        "tools_used": output_item.get("tools_used") or [],
        "session_id": body.session_id,
        "model": model_choice or "default",
        "provider": llm.get("provider") or "default",
    })


# ----------------------------------------------------------------------
# Phase 16: AI automation assistant (read-only suggestion surfaces)
# ----------------------------------------------------------------------

def get_workflow_read(db: Session, workflow_id: str, user: User):
    """Read-access wrapper returning the WorkflowRecord itself.

    View permission suffices for every assist surface: nothing here
    mutates workflows — suggestions are data the client may apply as a
    normal edit (which still requires the usual edit permission).
    """
    from app.api.access import get_workflow

    return get_workflow(db, workflow_id, user)


def _upstream_fields(db: Session, workflow_data: dict, node_id: str) -> list[dict]:
    from app.api.workflows import _flatten_item, _uf_impl

    try:
        uf = _uf_impl(db, workflow_data, node_id)
    except Exception:
        return []
    outputs = uf.get("outputs") or {}
    fields: list[dict] = []
    for nid in uf.get("upstream_nodes") or []:
        items = (outputs.get(nid) or {}).get("main") or []
        if not items:
            continue
        for f in _flatten_item(items[0]):
            fields.append({"node_id": nid, **f})
    return fields


@router.post("/suggest-mapping")
async def suggest_mapping(
    body: SuggestMappingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Field-mapping suggestions grounded in the last execution's real
    upstream output shapes; every expression is linted before display."""
    from app.ai.assistant import AssistantError, suggest_field_mapping
    from app.schemas.workflow import Workflow

    rec = get_workflow_read(db, body.workflow_id, user)
    workflow = Workflow.model_validate(rec.data or {})
    node = next((n for n in workflow.nodes if n.id == body.node_id), None)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found.")
    source_fields = _upstream_fields(db, rec.data or {}, body.node_id)

    # Target fields: the node's existing mapping targets when it maps
    # into a dict (set_data.fields), otherwise its parameter property names.
    target_fields = list((node.parameters or {}).get("fields") or {})
    if not target_fields:
        target_fields = sorted((node.parameters or {}).keys())

    llm = _pick_llm(db, user, body.credential_id)
    try:
        result = await suggest_field_mapping(
            target_node_type=node.type,
            target_fields=target_fields,
            source_fields=source_fields,
            intent=body.intent,
            chat=chat_completion,
            llm=llm,
        )
    except AssistantError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _client_error(exc))
    log_event(db, AI_ASSIST, target_type="workflow", target_id=body.workflow_id,
              user_id=user.id, detail={"surface": "mapping", "node_id": body.node_id})
    return ok({**result, "source_fields": source_fields})


@router.post("/suggest-expression")
async def suggest_expression_endpoint(
    body: SuggestExpressionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """One validated {{ }} expression from a plain-language description,
    preview-evaluated against a sample item (provided or from history)."""
    from app.ai.assistant import AssistantError, suggest_expression

    sample = dict(body.sample_item or {})
    if not sample and body.workflow_id and body.node_id:
        sample = next(iter(_upstream_fields(db, get_workflow_read(
            db, body.workflow_id, user).data or {}, body.node_id)), {})
    llm = _pick_llm(db, user, body.credential_id)
    try:
        result = await suggest_expression(
            description=body.description, sample_item=sample,
            chat=chat_completion, llm=llm,
        )
    except AssistantError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _client_error(exc))
    log_event(db, AI_ASSIST, target_type="ai", target_id="expression", user_id=user.id)
    return ok(result)


@router.post("/suggest-node-config")
async def suggest_node_config(
    body: SuggestConfigRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Parameter suggestions for one node type, validated against the
    node's REAL schema / connector operation contract."""
    from app.ai.assistant import AssistantError, suggest_node_config as _impl

    available_credentials = {
        meta["type"] for meta in credential_service.list_for_user(db, user.id)
    }
    llm = _pick_llm(db, user, body.credential_id)
    try:
        result = await _impl(
            node_type=body.node_type,
            operation=body.operation,
            intent=body.intent,
            available_credentials=available_credentials,
            chat=chat_completion,
            llm=llm,
        )
    except AssistantError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _client_error(exc))
    log_event(db, AI_ASSIST, target_type="node", target_id=body.node_type,
              user_id=user.id, detail={"surface": "config"})
    return ok(result)


@router.post("/optimize-workflow")
async def optimize_workflow(
    body: WorkflowRefRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Deterministic reliability findings + optional advisory narrative.
    Findings are computed by rules (always correct); the model only
    explains. Fixes are PREVIEWS � nothing is applied."""
    from app.ai.assistant import analyze_workflow, suggest_optimizations

    rec = get_workflow_read(db, body.workflow_id, user)
    # Deterministic findings are the ground truth; the LLM only narrates.
    llm = _pick_llm(db, user, body.credential_id)
    result = await suggest_optimizations(rec.data or {}, chat=chat_completion, llm=llm)
    result.setdefault("findings", analyze_workflow(rec.data or {}))
    log_event(db, AI_ASSIST, target_type="workflow", target_id=body.workflow_id,
              user_id=user.id, detail={"surface": "optimize",
                                       "findings": len(result["findings"])})
    return ok(result)


@router.post("/explain-workflow")
async def explain_workflow(
    body: WorkflowRefRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Plain-language walkthrough, grounded in the actual graph."""
    from app.ai.assistant import explain_workflow as _impl

    rec = get_workflow_read(db, body.workflow_id, user)
    llm = _pick_llm(db, user, body.credential_id)
    try:
        result = await _impl(rec.data or {}, chat=chat_completion, llm=llm)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _client_error(exc))
    log_event(db, AI_ASSIST, target_type="workflow", target_id=body.workflow_id,
              user_id=user.id, detail={"surface": "explain"})
    return ok(result)


@router.post("/document-workflow")
async def document_workflow(
    body: WorkflowRefRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Markdown reference doc. The skeleton is generated deterministically;
    the model only adds the overview paragraph (and may be absent)."""
    from app.ai.assistant import document_workflow as _impl

    rec = get_workflow_read(db, body.workflow_id, user)
    llm: dict | None
    try:
        llm = _pick_llm(db, user, body.credential_id)
    except HTTPException:
        llm = None  # documentation works without an LLM credential
    result = await _impl(rec.data or {}, chat=chat_completion, llm=llm)
    log_event(db, AI_ASSIST, target_type="workflow", target_id=body.workflow_id,
              user_id=user.id, detail={"surface": "document"})
    return ok(result)


class AutoFixRequest(BaseModel):
    workflow_id: str
    node_id: str
    error_message: str
    credential_id: str | None = None


@router.post("/auto-fix")
async def auto_fix_endpoint(
    body: AutoFixRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Diagnose a node failure and propose fixed parameters to self-heal the workflow."""
    from app.ai.assistant import repair_node_failure
    from app.schemas.workflow import Workflow

    rec = get_workflow_read(db, body.workflow_id, user)
    workflow = Workflow.model_validate(rec.data or {})
    node = next((n for n in workflow.nodes if n.id == body.node_id), None)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found in workflow.")

    upstream_samples = _upstream_fields(db, rec.data or {}, body.node_id)
    sample = upstream_samples[0] if upstream_samples else None

    llm: dict | None = None
    try:
        llm = _pick_llm(db, user, body.credential_id)
    except HTTPException:
        llm = None

    result = await repair_node_failure(
        node_type=node.type,
        operation=(node.parameters or {}).get("operation"),
        current_parameters=dict(node.parameters or {}),
        error_message=body.error_message,
        upstream_sample=sample,
        chat=chat_completion if llm else None,
        llm=llm,
    )
    log_event(db, AI_ASSIST, target_type="workflow", target_id=body.workflow_id,
              user_id=user.id, detail={"surface": "auto_fix", "node_id": body.node_id})
    return ok(result)


# ----------------------------------------------------------------------
# AI-Native Workflow Builder Endpoints
# ----------------------------------------------------------------------

@router.get("/capabilities")
def get_capabilities(
    q: str = "",
    limit: int = 15,
    user: User = Depends(get_current_user),
) -> dict:
    """Search registered nodes and connector capabilities."""
    from app.ai.capabilities import CapabilityRegistry
    reg = CapabilityRegistry.get_instance()
    results = reg.search_capabilities(q, limit=limit)
    return ok(results)


class IntentRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    mode: str = "build"  # build | modify | repair
    credential_id: str | None = None
    existing_workflow: dict | None = None
    answers: dict | None = None


@router.post("/intent")
async def extract_intent_endpoint(
    body: IntentRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Extract structured intent and clarification questions from natural language requirements."""
    from app.ai.intent import IntentEngine

    try:
        llm = _pick_llm(db, user, body.credential_id)
    except HTTPException:
        llm = None
    intent = await IntentEngine.extract_intent(
        prompt=body.prompt,
        chat=chat_completion,
        llm=llm,
        existing_workflow=body.existing_workflow,
        answers=body.answers,
        mode=body.mode,
    )
    return ok(intent.model_dump())


class CompileIRRequest(BaseModel):
    ir: dict[str, Any]
    credential_id: str | None = None


@router.post("/compile")
def compile_ir_endpoint(
    body: CompileIRRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Compile WorkflowIR into a concrete Flowsmith DAG document."""
    from app.ai.compiler import WorkflowCompiler
    from app.ai.ir import WorkflowIR

    ir_obj = WorkflowIR.model_validate(body.ir)
    compiled = WorkflowCompiler.compile_ir(ir_obj)
    return ok({"workflow": compiled})


class PipelineValidationRequest(BaseModel):
    workflow: dict[str, Any]
    credential_id: str | None = None


@router.post("/validate-pipeline")
def validate_pipeline_endpoint(
    body: PipelineValidationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Run full 6-stage validation across structural, connector, data, credential, runtime and security."""
    from app.ai.pipeline_validator import PipelineValidator

    user_creds = {meta["type"] for meta in credential_service.list_for_user(db, user.id)}
    report = PipelineValidator.validate_full(body.workflow, user_credentials=user_creds)
    return ok(report)


class SimulateRequest(BaseModel):
    workflow: dict[str, Any]
    mock_input: dict[str, Any] | None = None
    credential_id: str | None = None


@router.post("/simulate")
def simulate_endpoint(
    body: SimulateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Safely simulate workflow execution with synthetic data propagation and latency estimation."""
    from app.ai.simulator import WorkflowSimulator

    user_creds = {meta["type"] for meta in credential_service.list_for_user(db, user.id)}
    sim_res = WorkflowSimulator.simulate(body.workflow, user_credentials=user_creds, mock_input=body.mock_input)
    return ok(sim_res)


class RepairWorkflowRequest(BaseModel):
    workflow: dict[str, Any]
    error_message: str
    execution_trace: list[dict[str, Any]] | None = None
    credential_id: str | None = None


@router.post("/repair-workflow")
async def repair_workflow_endpoint(
    body: RepairWorkflowRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Analyze workflow failure and construct validated repair proposal with diff."""
    from app.ai.repair import WorkflowRepairer

    llm = _pick_llm(db, user, body.credential_id)
    user_creds = {meta["type"] for meta in credential_service.list_for_user(db, user.id)}

    proposal = await WorkflowRepairer.analyze_and_repair(
        workflow_doc=body.workflow,
        error_context=body.error_message,
        execution_trace=body.execution_trace,
        chat=chat_completion,
        llm=llm,
        user_credentials=user_creds,
    )
    return ok(proposal.model_dump())


class ModifyWorkflowRequest(BaseModel):
    workflow: dict[str, Any]
    instruction: str
    credential_id: str | None = None


@router.post("/modify-workflow")
async def modify_workflow_endpoint(
    body: ModifyWorkflowRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Apply surgical natural language modification to an existing workflow and return diff."""
    from app.ai.modification import WorkflowModifier

    try:
        llm = _pick_llm(db, user, body.credential_id)
    except HTTPException:
        llm = {"provider": "builtin", "model": "builtin", "api_key": "builtin_local"}
    user_creds = {meta["type"] for meta in credential_service.list_for_user(db, user.id)}

    diff = await WorkflowModifier.modify_workflow(
        current_workflow=body.workflow,
        instruction=body.instruction,
        chat=chat_completion,
        llm=llm,
        user_credentials=user_creds,
    )
    return ok(diff.model_dump())


class OptimizeDraftRequest(BaseModel):
    workflow: dict[str, Any]
    dimension: str = "cost"


@router.post("/optimize-draft")
def optimize_draft_endpoint(
    body: OptimizeDraftRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Propose surgical optimizations for cost, latency, or reliability on a draft workflow."""
    from app.ai.modification import WorkflowModifier
    res = WorkflowModifier.optimize_workflow(body.workflow, dimension=body.dimension)
    return ok(res)


class ExplainDraftRequest(BaseModel):
    workflow: dict[str, Any]
    failure_context: str | None = None


@router.post("/explain-draft")
def explain_draft_endpoint(
    body: ExplainDraftRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Generate business and technical explanation for a draft workflow, with optional failure diagnosis."""
    from app.ai.modification import WorkflowModifier
    res = WorkflowModifier.explain_workflow(body.workflow, failure_context=body.failure_context)
    return ok(res)



