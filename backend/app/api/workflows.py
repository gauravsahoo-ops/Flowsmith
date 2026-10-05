"""Workflow CRUD endpoints (spec 9).

The canvas will PUT the full workflow JSON on every debounced save;
validation reuses the engine's graph checks so a broken graph is
rejected before it is stored. `version` bumps on each save so
executions can run the exact saved version (spec 24.2/24.3).

Access control (security phase): owners have full control, shared
users have view or edit, everything else is a 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import (
    WORKFLOW_ACTIVATE,
    WORKFLOW_CREATE,
    WORKFLOW_DEACTIVATE,
    WORKFLOW_DELETE,
    WORKFLOW_SHARE,
    WORKFLOW_UPDATE,
    log_event,
)
from app.api.access import (
    PERMISSION_VIEW,
    accessible_ids,
    batch_permissions,
    get_permission,
    get_workflow,
    is_owner,
)
from app.api.auth import get_current_user
from app.api.common import ok, page_params, validate_workflow_payload
from app.db import get_db
from app.importexport import WorkflowImportError, build_export, parse_import
from app.models import AuditEvent, Credential, User, WorkflowRecord, WorkflowShare, WorkflowVersionRecord
from app.nodes.registry import NODE_REGISTRY
from app.schemas.workflow import Workflow
from app.engine.expressions import resolve as resolve_expression
from app.triggers.registry import sync_webhooks

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

SHARE_TARGET = "workflow"


def _sync_triggers(db: Session) -> None:
    """Reconcile webhook/schedule registrations with active workflows."""
    sync_webhooks(db)


def _validate_webhook_paths(workflow: Workflow, db: Session, exclude_id: str | None = None) -> None:
    """Reject webhook paths already claimed by another active workflow."""
    import re

    from app.models import WebhookTrigger

    # Phase 23/38: these paths are the ONLY authentication for the
    # unauthenticated trigger endpoints, so they must have real entropy.
    # 24+ chars of [A-Za-z0-9/_.-] gives ~2^120+ search space for random
    # ids and blocks guessable names like "my-hook".
    _PATH_RE = re.compile(r"^[A-Za-z0-9/_.\-]{24,}$")

    def _check_trigger_path(node_type: str, raw_path) -> None:
        if not raw_path:
            return
        path = str(raw_path)
        if not _PATH_RE.match(path):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{node_type} path '{path}' is too weak. It is the only "
                "authentication for an unauthenticated endpoint: use at least "
                "24 characters of [A-Za-z0-9/_.-] (a generated id works well).",
            )

    for node in workflow.nodes:
        if node.type == "webhook":
            _check_trigger_path(node.type, node.parameters.get("path"))
        elif node.type == "salesforce_trigger":
            _check_trigger_path(node.type, node.parameters.get("path"))
        elif node.type == "form_trigger":
            _check_trigger_path(node.type, node.parameters.get("path"))
        elif node.type == "chat_trigger":
            _check_trigger_path(node.type, node.parameters.get("path"))
        else:
            continue
        node_id_path = node.parameters.get("path")
        if not node_id_path:
            continue
        path = str(node_id_path)
        other = db.scalar(
            select(WebhookTrigger).where(
                WebhookTrigger.path == path,
                WebhookTrigger.workflow_id != exclude_id,
            )
        )
        if other is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Webhook path '{path}' is already used by another active workflow.",
            )


def _validate_credential_refs(
    workflow: Workflow, user: User, db: Session, allow_unbound: bool = False
) -> None:
    """Validate credentials referenced by nodes.

    If allow_unbound is True (e.g. on import, templates, or AI workflow drafts),
    unresolvable or placeholder credentials are removed from node.credentials so the
    workflow can be loaded into the canvas for configuration without raising 422.
    If the user has a valid credential of the matching type, it is automatically bound.
    """
    for node in workflow.nodes:
        if not node.credentials:
            continue
        node_cls = NODE_REGISTRY.get(node.type)
        supported_cred_types: set[str] = set()
        if node_cls is not None:
            supported_cred_types = set(node_cls.credential_types or [])
        else:
            # Check registered connectors
            from app.connectors import ensure_builtin_connectors, get_registry as get_connector_registry
            ensure_builtin_connectors()
            c_reg = get_connector_registry()
            p_conn = c_reg.primary_for_node_type(node.type)
            if p_conn is not None:
                c_id = getattr(p_conn, "connector_id", None) or node.type
                supported_cred_types.add(c_id)
                try:
                    c_def = c_reg.get_definition(c_id)
                    if c_def and getattr(c_def, "operations", None):
                        for op in c_def.operations.values():
                            if getattr(op, "credential_require", None):
                                supported_cred_types.add(op.credential_require)
                except Exception:
                    pass

        for cred_type, cred_id in list(node.credentials.items()):
            is_placeholder = (
                not cred_id
                or cred_id.startswith("$")
                or cred_id.lower() in ("placeholder", "none", "null", "undefined")
            )

            # If node class explicitly specifies credentials and cred_type is not supported
            if supported_cred_types and cred_type not in supported_cred_types:
                if allow_unbound or is_placeholder:
                    node.credentials.pop(cred_type, None)
                    continue
                else:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_CONTENT,
                        f"Node '{node.id}' ({node.type}) does not support '{cred_type}' credentials.",
                    )

            rec = None if is_placeholder else db.get(Credential, cred_id)
            if rec is not None and rec.user_id == user.id:
                # Valid existing credential owned by this user
                continue

            # Auto-heal: if user has a valid credential of this type, link it
            user_cred = (
                db.query(Credential)
                .filter(Credential.user_id == user.id, Credential.type == cred_type)
                .order_by(Credential.created_at.desc())
                .first()
            )
            if user_cred is not None:
                node.credentials[cred_type] = user_cred.id
            elif allow_unbound or is_placeholder:
                # User has not connected this credential yet: remove unbound reference
                # so the workflow imports/creates safely and node is ready for config in canvas
                node.credentials.pop(cred_type, None)
            else:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"Node '{node.id}' references an unknown credential.",
                )


def _to_dict(rec: WorkflowRecord, permission: str) -> dict[str, Any]:
    """The stored JSON plus record-level metadata.

    NOTE: We intentionally do NOT redact node parameters here. The frontend
    needs real values (auth_token, auth_password, etc.) to display and persist
    them correctly. Redaction is applied only to execution traces/logs, not
    the workflow definition itself.
    """
    data = dict(rec.data)
    pinned = bool(data.get("settings", {}).get("pinned", False))
    return {
        **data,
        "id": rec.id,
        "name": data.get("name", rec.name),
        "version": rec.version,
        "active": rec.active,
        "pinned": pinned,
        "permission": permission,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
    }


@router.get("")
def list_workflows(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = 1,
    pageSize: int = 50,
) -> dict:
    page, size = page_params(page=page, pageSize=pageSize)
    ids = accessible_ids(db, user)
    if not ids:
        return ok([], {"page": page, "pageSize": size, "total": 0})
    total = (
        db.scalar(select(func.count()).select_from(WorkflowRecord).where(WorkflowRecord.id.in_(ids))) or 0
    )
    recs = db.scalars(
        select(WorkflowRecord)
        .where(WorkflowRecord.id.in_(ids))
        .order_by(WorkflowRecord.updated_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    perms = batch_permissions(db, {r.id for r in recs}, user)
    return ok(
        [_to_dict(r, perms.get(r.id, "view")) for r in recs],
        {"page": page, "pageSize": size, "total": total},
    )


@router.get("/{workflow_id}/export")
def export_workflow(
    workflow_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Export a workflow as a portable JSON document (native format)."""
    rec = get_workflow(db, workflow_id, user)
    return ok(build_export(rec.data))


@router.post("/import", status_code=status.HTTP_201_CREATED)
def import_workflow(
    body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Import a workflow from the export envelope, a native document, or
    a standard workflow JSON export (best-effort conversion of supported node types).

    A fresh workflow id is generated when the source id is missing or
    already taken, so re-importing never clobbers an existing workflow.
    """
    try:
        native = parse_import(body)
    except WorkflowImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    source_id = native.get("id")
    if not source_id or db.get(WorkflowRecord, source_id) is not None:
        native["id"] = f"wf_import_{uuid.uuid4().hex[:12]}"
    workflow = validate_workflow_payload(native)
    _validate_credential_refs(workflow, user, db, allow_unbound=True)

    # Ensure imported webhook/trigger paths meet 24+ char entropy and uniqueness requirements
    import re
    from app.models import WebhookTrigger

    for node in workflow.nodes:
        if node.type in ("webhook", "salesforce_trigger", "form_trigger", "chat_trigger"):
            curr_path = str(node.parameters.get("path") or "")
            clean_prefix = re.sub(r"[^A-Za-z0-9_.-]", "", curr_path)[:12] or "hook"
            if len(curr_path) < 24:
                node.parameters["path"] = f"{clean_prefix}-{uuid.uuid4().hex[:18]}"
            other = db.scalar(select(WebhookTrigger).where(WebhookTrigger.path == node.parameters["path"]))
            if other is not None:
                node.parameters["path"] = f"{clean_prefix}-{uuid.uuid4().hex[:18]}"

    _validate_webhook_paths(workflow, db, exclude_id=workflow.id)

    if db.get(WorkflowRecord, workflow.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Workflow '{workflow.id}' already exists.")
    rec = WorkflowRecord(
        id=workflow.id,
        user_id=user.id,
        name=workflow.name,
        description=workflow.settings.get("description", ""),
        version=workflow.version,
        data=workflow.model_dump(mode="json"),
    )
    db.add(rec)
    ver = WorkflowVersionRecord(
        id=f"ver_{uuid.uuid4().hex[:12]}",
        workflow_id=workflow.id,
        version=workflow.version,
        data=workflow.model_dump(mode="json"),
        user_id=user.id,
        is_active=True,
    )
    db.add(ver)
    db.commit()
    db.refresh(rec)
    log_event(db, WORKFLOW_CREATE, target_type=SHARE_TARGET, target_id=rec.id, user_id=user.id)
    return ok(_to_dict(rec, "owner"), meta={"imported": True, "source_id": source_id})


@router.get("/{workflow_id}")
def get_workflow_endpoint(
    workflow_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rec = get_workflow(db, workflow_id, user)
    return ok(_to_dict(rec, get_permission(db, workflow_id, user) or "view"))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_workflow(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workflow = validate_workflow_payload(body)
    _validate_credential_refs(workflow, user, db, allow_unbound=True)
    # Phase 23/38: trigger-path entropy + uniqueness on CREATE too (it
    # previously ran only on update, so weak/duplicate paths slipped in).
    _validate_webhook_paths(workflow, db)
    # Optional workspace assignment (Phase 31): env vars are scoped per
    # workspace, so a workflow must belong to one to use {{ $env.* }}.
    workspace_id = body.get("workspace_id")
    if workspace_id is not None:
        from app.api.workspaces import _require_ws_member
        from app.billing.service import enforce_plan_limit

        _require_ws_member(db, str(workspace_id), user)
        enforce_plan_limit(db, str(workspace_id), "workflows")
    # Check if a workflow with this id already exists (by record id)
    if db.get(WorkflowRecord, workflow.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Workflow '{workflow.id}' already exists.")
    # Create the workflow record (version starts at 1)
    rec = WorkflowRecord(
        id=workflow.id,
        user_id=user.id,
        name=workflow.name,
        description=workflow.settings.get("description", ""),
        version=workflow.version,
        data=workflow.model_dump(mode="json"),
        workspace_id=str(workspace_id) if workspace_id else None,
    )
    db.add(rec)
    # Create immutable version snapshot
    ver = WorkflowVersionRecord(
        id=f"ver_{uuid.uuid4().hex[:12]}",
        workflow_id=workflow.id,
        version=workflow.version,
        data=workflow.model_dump(mode="json"),
        user_id=user.id,
        is_active=(workflow.version == 1),  # First version is active by default
    )
    db.add(ver)
    db.commit()
    db.refresh(rec)
    db.refresh(ver)
    log_event(db, WORKFLOW_CREATE, target_type=SHARE_TARGET, target_id=rec.id, user_id=user.id)
    return ok(_to_dict(rec, "owner"), meta={"version_id": ver.id, "version": ver.version})


@router.put("/{workflow_id}")
def update_workflow(
    workflow_id: str, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rec = get_workflow(db, workflow_id, user, require_edit=True)
    workflow = validate_workflow_payload(body)
    _validate_credential_refs(workflow, user, db)
    _validate_webhook_paths(workflow, db, exclude_id=workflow_id)
    if workflow.id != workflow_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow id in body does not match the URL.")
    new_version = rec.version + 1
    # Immutable snapshot of the new version (workflow_versions row)
    ver_id = f"ver_{uuid.uuid4().hex[:12]}"
    ver = WorkflowVersionRecord(
        id=ver_id,
        workflow_id=workflow_id,
        version=new_version,
        data=workflow.model_dump(mode="json"),
        user_id=user.id,
        is_active=True,
    )
    db.add(ver)
    # Deactivate all older snapshots
    db.query(WorkflowVersionRecord).filter(
        WorkflowVersionRecord.workflow_id == workflow_id,
        WorkflowVersionRecord.version != new_version,
    ).update({"is_active": False})
    # Update the mutable latest record in place (workflows.id is the PK)
    rec.name = workflow.name
    rec.description = workflow.settings.get("description", "")
    rec.version = new_version
    rec.data = workflow.model_dump(mode="json")
    db.commit()
    db.refresh(rec)
    log_event(db, WORKFLOW_UPDATE, target_type=SHARE_TARGET, target_id=rec.id, user_id=user.id)
    _sync_triggers(db)
    return ok(_to_dict(rec, get_permission(db, workflow_id, user) or "edit"), meta={"version_id": ver_id, "version": new_version})


@router.patch("/{workflow_id}/active")
def set_active(
    workflow_id: str, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rec = get_workflow(db, workflow_id, user, require_edit=True)
    active = body.get("active")
    if not isinstance(active, bool):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Field 'active' must be a boolean.")
    return ok(_set_active_impl(db, rec, user, active))


@router.patch("/{workflow_id}/pinned")
def set_pinned(
    workflow_id: str, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rec = get_workflow(db, workflow_id, user, require_edit=True)
    pinned = body.get("pinned")
    if not isinstance(pinned, bool):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Field 'pinned' must be a boolean.")
    data = dict(rec.data or {})
    settings = dict(data.get("settings") or {})
    settings["pinned"] = pinned
    data["settings"] = settings
    rec.data = data
    db.commit()
    db.refresh(rec)
    return ok({"id": rec.id, "pinned": pinned})


def _set_active_impl(db: Session, rec: WorkflowRecord, user: User, active: bool) -> dict:
    """Shared activation logic (route + MCP tool)."""
    if active:
        _validate_webhook_paths(Workflow.model_validate(rec.data), db, exclude_id=rec.id)
    rec.active = active
    db.commit()
    db.refresh(rec)
    log_event(
        db,
        WORKFLOW_ACTIVATE if active else WORKFLOW_DEACTIVATE,
        target_type=SHARE_TARGET, target_id=rec.id, user_id=user.id,
    )
    _sync_triggers(db)
    return {"id": rec.id, "active": rec.active}


@router.get("/{workflow_id}/upstream-fields")
def upstream_fields(
    workflow_id: str,
    node_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Typed, flattened output fields of every upstream node (Phase 5).

    Reads the most recent execution that produced results for this
    workflow and flattens the first main-output item per upstream node.
    """
    rec = get_workflow(db, workflow_id, user)
    uf = _uf_impl(db, rec.data or {}, node_id)
    upstream = uf["upstream_nodes"]
    outputs = uf["outputs"]

    fields = []
    for nid in upstream:
        by_handle = outputs.get(nid) or {}
        items = by_handle.get("main") or []
        if not items:
            continue
        first = items[0]
        for f in _flatten_item(first):
            fields.append({"node_id": nid, **f})
    return ok({
        "node_id": node_id,
        "upstream_nodes": upstream,
        "fields": fields,
        "has_execution_data": bool(fields),
    })


def _uf_impl(db: Session, workflow_data: dict, node_id: str) -> dict:
    """Shared implementation returning upstream ids + latest outputs."""
    from app.models import Execution as ExecutionModel

    conns = (workflow_data or {}).get("connections", [])
    incoming: dict[str, list[str]] = {}
    for c in conns:
        incoming.setdefault(c.get("target"), []).append(c.get("source"))
    stack, seen = [node_id], []
    while stack:
        cur = stack.pop()
        for src in incoming.get(cur, []):
            if src not in seen:
                seen.append(src)
                stack.append(src)
    upstream = list(reversed(seen))

    wf_id = workflow_data.get("id")
    rows = db.execute(
        select(ExecutionModel)
        .where(ExecutionModel.workflow_id == wf_id, ExecutionModel.results.is_not(None))
        .order_by(ExecutionModel.started_at.desc())
        .limit(5)
    ).scalars().all()
    outputs = {}
    for row in rows:
        if not isinstance(row.results, dict):
            continue
        candidate = row.results.get("outputs") or {}
        # Skip executions where every node has empty items
        has_data = any(
            items
            for handles in candidate.values()
            for items in ((handles.get("main") or []) if isinstance(handles, dict) else [])
            if items
        )
        if has_data:
            outputs = candidate
            break
    return {"upstream_nodes": upstream, "outputs": outputs}


def _flatten_item(item: Any, prefix: str = "", depth: int = 0) -> list[dict[str, Any]]:
    """Flatten one output item into typed leaf paths (depth-capped)."""
    out: list[dict[str, Any]] = []
    if depth > 6:
        return out
    if isinstance(item, dict):
        for key, val in item.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_flatten_item(val, path, depth + 1))
    elif isinstance(item, list):
        for i, val in enumerate(item[:5]):
            out.extend(_flatten_item(val, f"{prefix}[{i}]", depth + 1))
    else:
        sample = item if isinstance(item, (str, int, float, bool)) else None
        tname = "null" if item is None else type(item).__name__
        out.append({"path": prefix or "(root)", "type": tname, "sample": sample})
    return out


class PreviewExpressionRequest(BaseModel):
    expression: str
    node_id: str


@router.post("/{workflow_id}/preview-expression")
def preview_expression(
    workflow_id: str,
    body: PreviewExpressionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Resolve one expression against the latest upstream context.

    Returns the resolved value + detected type; ``missing`` is True when
    the expression still contains unresolved {{ ... }} placeholders after
    resolution (i.e. a referenced field doesn't exist upstream).
    Secret env values are never included in the preview context.
    """
    rec = get_workflow(db, workflow_id, user)

    uf = _uf_impl(db, rec.data or {}, body.node_id)
    node_ctx: dict[str, Any] = {}
    json_first: dict[str, Any] | None = None
    # Build node name→id map for $('Node Name') expressions
    node_name_map: dict[str, str] = {}
    for n in (rec.data or {}).get("nodes") or []:
        nid = n.get("id", "")
        # Priority: explicit name > settings.label > display_name from registry
        node_name = n.get("name", "") or ""
        if not node_name:
            node_name = (n.get("settings") or {}).get("label", "") or ""
        if not node_name:
            node_cls = NODE_REGISTRY.get(n.get("type", ""))
            if node_cls is not None:
                node_name = getattr(node_cls, "display_name", "") or ""
        if node_name:
            node_name_map[node_name] = nid
            node_name_map[node_name.lower()] = nid
    for nid in uf["upstream_nodes"]:
        by_handle = uf["outputs"].get(nid) or {}
        items = by_handle.get("main") or []
        if items:
            node_ctx[nid] = {"json": items[0]}
            if json_first is None:
                json_first = items[0]

    context: dict[str, Any] = {
        "$json": json_first or {},
        "$node": node_ctx,
        "$env": _non_secret_env(db, rec.workspace_id, user),
        "$workflow": {"id": workflow_id},
        "$execution": {"id": "preview"},
        "$now": datetime.now(UTC).isoformat(),
        "_node_name_map": node_name_map,
    }

    value = resolve_expression(body.expression, context)
    rendered = str(value)
    missing = "{{" in rendered and "}}" in rendered
    vtype = (
        "null" if value is None
        else "boolean" if isinstance(value, bool)
        else "number" if isinstance(value, (int, float))
        else "string" if isinstance(value, str)
        else "array" if isinstance(value, list)
        else "object" if isinstance(value, dict)
        else "unknown"
    )
    return ok({
        "expression": body.expression,
        "value": None if missing else value,
        "rendered": rendered,
        "type": vtype,
        "missing": missing,
    })


def _non_secret_env(db: Session, workspace_id: str | None, user: User) -> dict[str, str]:
    """Env var values excluding secrets (never expose secrets anywhere)."""
    from sqlalchemy import select

    from app.api.workspaces import _require_ws_member

    from app.models import Environment

    if not workspace_id:
        return {}
    try:
        _require_ws_member(db, workspace_id, user)
        from app.environments import decrypt_env_value

        rows = db.execute(
            select(Environment).where(Environment.workspace_id == workspace_id)
        ).scalars().all()
        return {
            r.key: decrypt_env_value(r.value)
            for r in rows
            if not r.is_secret  # secrets excluded entirely (Phase 5)
        }
    except Exception:
        return {}


@router.get("/{workflow_id}/expression-context")
def expression_context(
    workflow_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Autocomplete context for the expression editor (Phase 40).

    Exposes variable metadata and node names — NEVER secret values. Env
    var keys are included only when the workflow belongs to a workspace
    the user can read.
    """
    rec = get_workflow(db, workflow_id, user)

    variables = [
        {"name": "$json", "description": "First input item of this node", "example": "{{ $json.field }}"},
        {"name": "$node.<id>.json", "description": "Output of a specific node (dot path or [\"Name\"])", "example": '{{ $node["My Node"].json.value }}'},
        {"name": "$execution.id", "description": "Current execution id", "example": "{{ $execution.id }}"},
        {"name": "$workflow.id", "description": "Workflow id", "example": "{{ $workflow.id }}"},
        {"name": "$now", "description": "Current ISO timestamp", "example": "{{ $now }}"},
        {"name": "$cred.<type>.<field>", "description": "Resolved credential values", "example": "{{ $cred.http.api_key }}"},
    ]

    env_keys = []
    if rec.workspace_id:
        from app.api.workspaces import _require_ws_member
        from sqlalchemy import select

        from app.models import Environment

        try:
            _require_ws_member(db, rec.workspace_id, user)
            rows = db.execute(
                select(Environment.key).where(Environment.workspace_id == rec.workspace_id)
            ).scalars().all()
            env_keys = sorted(rows)
        except HTTPException:
            env_keys = []

    nodes = [
        {
            "id": n.get("id"),
            "type": n.get("type"),
            "name": n.get("id"),
        }
        for n in (rec.data or {}).get("nodes", [])
    ]

    return ok({
        "variables": variables,
        "env_keys": env_keys,
        "env_example": '{{ $env.KEY }}',
        "nodes": nodes,
        "pipes": ["upper", "lower", "trim", "length", "int", "float", "bool",
                  "typeof", "contains(x)", "replace(a,b)"],
    })


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(workflow_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    """Soft-delete a workflow (owner only).

    The row is marked `deleted_at` and deactivated so it vanishes from
    every access path, but the record (plus versions and execution
    history) stays in the database for auditability — executions store
    their own workflow snapshot, so history remains inspectable by the
    owner. Shares are removed (they grant access to a dead workflow;
    the share schema cascades on delete). Trigger registrations are
    reconciled by sync_webhooks. The audit trail records the delete.
    """
    if not is_owner(db, workflow_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    rec = db.get(WorkflowRecord, workflow_id)
    assert rec is not None
    rec.deleted_at = datetime.now(timezone.utc)
    rec.active = False
    for share in db.scalars(
        select(WorkflowShare).where(WorkflowShare.workflow_id == workflow_id)
    ).all():
        db.delete(share)
    db.commit()
    log_event(db, WORKFLOW_DELETE, target_type=SHARE_TARGET, target_id=workflow_id, user_id=user.id)
    _sync_triggers(db)


class ShareRequest(BaseModel):
    email: EmailStr
    permission: str = Field(default=PERMISSION_VIEW, pattern="^(view|edit)$")


class ShareUpdateRequest(BaseModel):
    permission: str = Field(pattern="^(view|edit)$")


@router.get("/{workflow_id}/shares")
def list_shares(workflow_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    get_workflow(db, workflow_id, user, require_edit=True)
    shares = db.scalars(
        select(WorkflowShare).where(WorkflowShare.workflow_id == workflow_id)
    ).all()
    return ok([
        {
            "user_id": s.user_id,
            "email": (u.email if (u := db.get(User, s.user_id)) else "?"),
            "permission": s.permission,
        }
        for s in shares
    ])


@router.post("/{workflow_id}/shares", status_code=status.HTTP_201_CREATED)
def share_workflow(
    workflow_id: str, body: ShareRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if not is_owner(db, workflow_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    target = db.scalar(select(User).where(User.email == body.email.lower()))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No account with that email.")
    if target.id == user.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You already own this workflow.")
    existing = db.scalar(
        select(WorkflowShare).where(
            WorkflowShare.workflow_id == workflow_id,
            WorkflowShare.user_id == target.id,
        )
    )
    if existing is not None:
        existing.permission = body.permission
    else:
        db.add(WorkflowShare(workflow_id=workflow_id, user_id=target.id, permission=body.permission))
    db.commit()
    log_event(
        db, WORKFLOW_SHARE, target_type=SHARE_TARGET, target_id=workflow_id, user_id=user.id,
        detail={"email": body.email.lower(), "permission": body.permission},
    )
    return ok({"user_id": target.id, "email": target.email, "permission": body.permission})


@router.patch("/{workflow_id}/shares/{share_user_id}")
def update_share(
    workflow_id: str,
    share_user_id: int,
    body: ShareUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not is_owner(db, workflow_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    share = db.scalar(
        select(WorkflowShare).where(
            WorkflowShare.workflow_id == workflow_id,
            WorkflowShare.user_id == share_user_id,
        )
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share not found.")
    share.permission = body.permission
    db.commit()
    target = db.get(User, share_user_id)
    log_event(
        db, WORKFLOW_SHARE, target_type=SHARE_TARGET, target_id=workflow_id, user_id=user.id,
        detail={"email": target.email if target else str(share_user_id), "permission": body.permission},
    )
    return ok({"user_id": share_user_id, "email": target.email if target else "?", "permission": body.permission})


@router.delete("/{workflow_id}/shares/{share_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unshare_workflow(
    workflow_id: str,
    share_user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not is_owner(db, workflow_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    share = db.scalar(
        select(WorkflowShare).where(
            WorkflowShare.workflow_id == workflow_id,
            WorkflowShare.user_id == share_user_id,
        )
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share not found.")
    db.delete(share)
    db.commit()


@router.get("/{workflow_id}/versions")
def list_versions(
    workflow_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """List all workflow versions with metadata."""
    if not is_owner(db, workflow_id, user) and get_permission(db, workflow_id, user) != "edit":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    records = db.scalars(
        select(WorkflowVersionRecord).where(WorkflowVersionRecord.workflow_id == workflow_id)
        .order_by(WorkflowVersionRecord.version.desc())
    ).all()
    user_ids = {rec.user_id for rec in records if rec.user_id}
    users_map = {}
    if user_ids:
        users = db.scalars(select(User).where(User.id.in_(user_ids))).all()
        users_map = {u.id: u.email for u in users}

    return ok([
        {
            "id": rec.id,
            "version": rec.version,
            "name": rec.data.get("name", rec.workflow_id) if isinstance(rec.data, dict) else rec.workflow_id,
            "updated_at": rec.created_at,
            "changed_by": rec.user_id,
            "author_email": users_map.get(rec.user_id, f"User #{rec.user_id}"),
            "author_name": users_map.get(rec.user_id, f"User #{rec.user_id}").split("@")[0],
            "is_active": rec.is_active,
            "node_count": len(rec.data.get("nodes", [])) if isinstance(rec.data, dict) else 0,
        }
        for rec in records
    ])


@router.get("/{workflow_id}/versions/{version_num}")
def get_version(
    workflow_id: str,
    version_num: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Fetch full snapshot data for a specific workflow version."""
    if not is_owner(db, workflow_id, user) and get_permission(db, workflow_id, user) != "edit":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    ver = db.scalar(
        select(WorkflowVersionRecord).where(
            WorkflowVersionRecord.workflow_id == workflow_id,
            WorkflowVersionRecord.version == version_num,
        )
    )
    if ver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Workflow version {version_num} not found.")

    author = db.scalar(select(User).where(User.id == ver.user_id)) if ver.user_id else None
    author_email = author.email if author else f"User #{ver.user_id}"
    return ok({
        "id": ver.id,
        "workflow_id": ver.workflow_id,
        "version": ver.version,
        "name": ver.data.get("name", ver.workflow_id) if isinstance(ver.data, dict) else ver.workflow_id,
        "updated_at": ver.created_at,
        "changed_by": ver.user_id,
        "author_email": author_email,
        "author_name": author_email.split("@")[0],
        "is_active": ver.is_active,
        "data": ver.data,
    })


@router.get("/{workflow_id}/activation-history")
def get_activation_history(
    workflow_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Retrieve activation and deactivation timeline events for this workflow."""
    rec = get_workflow(db, workflow_id, user)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")

    events = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.target_id == workflow_id,
            AuditEvent.action.in_([WORKFLOW_ACTIVATE, WORKFLOW_DEACTIVATE]),
        )
        .order_by(AuditEvent.created_at.desc())
    ).all()

    user_ids = {e.user_id for e in events if e.user_id}
    users_map = {}
    if user_ids:
        users = db.scalars(select(User).where(User.id.in_(user_ids))).all()
        users_map = {u.id: u.email for u in users}

    versions = db.scalars(
        select(WorkflowVersionRecord)
        .where(WorkflowVersionRecord.workflow_id == workflow_id)
        .order_by(WorkflowVersionRecord.version.desc())
    ).all()

    timeline = []
    for ev in events:
        is_activate = ev.action == WORKFLOW_ACTIVATE
        matched_ver = None
        for v in versions:
            if v.created_at <= ev.created_at:
                matched_ver = v.version
                break
        if matched_ver is None and versions:
            matched_ver = versions[-1].version

        author_email = users_map.get(ev.user_id, f"User #{ev.user_id}") if ev.user_id is not None else "System"
        timeline.append({
            "id": str(ev.id),
            "action": "activated" if is_activate else "deactivated",
            "is_active": is_activate,
            "version": matched_ver or rec.version,
            "created_at": ev.created_at,
            "user_id": ev.user_id,
            "user_email": author_email,
            "user_name": author_email.split("@")[0],
        })

    if not timeline:
        author = db.scalar(select(User).where(User.id == rec.user_id)) if rec.user_id else None
        author_email = author.email if author else f"User #{rec.user_id}"
        timeline.append({
            "id": f"curr_{rec.id}",
            "action": "activated" if rec.active else "deactivated",
            "is_active": rec.active,
            "version": rec.version,
            "created_at": rec.updated_at or rec.created_at,
            "user_id": rec.user_id,
            "user_email": author_email,
            "user_name": author_email.split("@")[0],
        })

    return ok(timeline)


@router.post("/{workflow_id}/rollback")
def rollback_workflow(
    workflow_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Rollback workflow to a previous version."""
    target_version = body.get("version")
    if target_version is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Field 'version' is required.",
        )
    # Get the target version's record
    ver = db.scalar(
        select(WorkflowVersionRecord).where(
            WorkflowVersionRecord.workflow_id == workflow_id,
            WorkflowVersionRecord.version == target_version,
        )
    )
    if ver is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Workflow version {target_version} not found.",
        )
    # Permission-scoped (owner/edit; deleted workflows are invisible):
    # this also keeps rollback from resurrecting a deleted workflow.
    rec = get_workflow(db, workflow_id, user, require_edit=True)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    new_version = rec.version + 1
    # Immutable snapshot of the rolled-back version
    ver_id = f"ver_{uuid.uuid4().hex[:12]}"
    db.add(WorkflowVersionRecord(
        id=ver_id,
        workflow_id=workflow_id,
        version=new_version,
        data=ver.data,
        user_id=user.id,
        is_active=True,
    ))
    db.query(WorkflowVersionRecord).filter(
        WorkflowVersionRecord.workflow_id == workflow_id,
        WorkflowVersionRecord.version != new_version,
    ).update({"is_active": False})
    # Update the mutable latest record in place (workflows.id is the PK)
    rec.name = ver.data.get("name", "")
    rec.description = ver.data.get("settings", {}).get("description", "")
    rec.version = new_version
    rec.data = ver.data
    db.commit()
    db.refresh(rec)
    log_event(db, WORKFLOW_UPDATE, target_type=SHARE_TARGET, target_id=rec.id, user_id=user.id)
    _sync_triggers(db)
    return ok(_to_dict(rec, get_permission(db, workflow_id, user) or "edit"), meta={"version_id": ver_id, "version": new_version})


@router.get("/{workflow_id}/auth-state")
def get_workflow_auth_state(
    workflow_id: str,
    provider: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Get live stored authentication credentials/status for a workflow."""
    rec = get_workflow(db, workflow_id, user, require_edit=False)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")

    from app.auth_state.service import get_state
    from app.auth_state.adapter import canonical_provider, is_expired, normalize_expires_at

    c_provider = canonical_provider(provider) if provider else ""

    if c_provider:
        state = get_state(db, workflow_id, c_provider)
        if state:
            epoch = normalize_expires_at(state.get("expires_at"))
            valid = not is_expired(epoch)
            raw_token = state.get("access_token") or ""
            raw_type = state.get("token_type") or "Bearer"
            masked = f"{raw_token[:8]}...••••••••" if len(raw_token) > 8 else "••••••••••••" if raw_token else None
            return ok({
                "workflow_id": workflow_id,
                "provider": c_provider,
                "is_valid": valid,
                "status": "VALID" if valid else "EXPIRED",
                "access_token_masked": masked,
                "has_refresh_token": bool(state.get("refresh_token")),
                "expires_at": datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None,
                "token_type": raw_type,
            })
        return ok({
            "workflow_id": workflow_id,
            "provider": c_provider,
            "is_valid": False,
            "status": "MISSING",
            "access_token_masked": None,
            "has_refresh_token": False,
            "expires_at": None,
        })

    # If no provider given, look up all active auth states for this workflow
    from app.models.workflow_auth import WorkflowAuthState
    rows = db.query(WorkflowAuthState).filter(WorkflowAuthState.workflow_id == workflow_id).all()
    results = []
    for r in rows:
        st = get_state(db, workflow_id, r.provider)
        if st:
            ep = normalize_expires_at(st.get("expires_at"))
            v = not is_expired(ep)
            tok = st.get("access_token") or ""
            results.append({
                "provider": r.provider,
                "is_valid": v,
                "status": "VALID" if v else "EXPIRED",
                "access_token_masked": f"{tok[:8]}...••••••••" if len(tok) > 8 else "••••••••••••",
                "has_refresh_token": bool(st.get("refresh_token")),
                "expires_at": datetime.fromtimestamp(ep, UTC).isoformat() if ep else None,
            })
    return ok({"workflow_id": workflow_id, "states": results})


@router.post("/{workflow_id}/auth-state/refresh")
async def refresh_workflow_auth_state(
    workflow_id: str,
    provider: str = "",
    force: bool = True,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Manually trigger token refresh for a workflow provider using stored refresh token."""
    rec = get_workflow(db, workflow_id, user, require_edit=True)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")

    from app.auth_state.service import get_state, locked_refresh
    from app.auth_state.adapter import canonical_provider, refresh_bundle, is_expired, normalize_expires_at
    from app.engine.errors import NodeExecutionError

    c_provider = canonical_provider(provider) if provider else ""
    if not c_provider:
        from app.models.workflow_auth import WorkflowAuthState
        first_state = db.query(WorkflowAuthState).filter(WorkflowAuthState.workflow_id == workflow_id).first()
        if first_state:
            c_provider = first_state.provider
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provider is required for token refresh.")

    state = get_state(db, workflow_id, c_provider)
    if not state:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No stored credentials found for provider '{c_provider}' in this workflow. Please run Login API first.",
        )

    if not state.get("refresh_token"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"No refresh token available for provider '{c_provider}'. Initial login or re-authentication required.",
        )

    async def _do_refresh(bundle: dict[str, Any]) -> dict[str, Any]:
        return await refresh_bundle(c_provider, bundle)

    try:
        fresh = await locked_refresh(db, workflow_id, c_provider, _do_refresh, force=force)
    except NodeExecutionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Token refresh failed: {exc.message}") from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Token refresh failed: {str(exc)}") from exc

    if not fresh:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not refresh credentials.")

    epoch = normalize_expires_at(fresh.get("expires_at"))
    valid = not is_expired(epoch)
    raw_token = fresh.get("access_token") or ""
    raw_type = fresh.get("token_type") or "Bearer"
    masked = f"{raw_token[:8]}...••••••••" if len(raw_token) > 8 else "••••••••••••" if raw_token else None

    return ok({
        "workflow_id": workflow_id,
        "provider": c_provider,
        "is_valid": valid,
        "status": "REFRESHED" if valid else "EXPIRED",
        "access_token_masked": masked,
        "has_refresh_token": bool(fresh.get("refresh_token")),
        "expires_at": datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None,
        "token_type": raw_type,
        "message": "Token refreshed successfully.",
    })

