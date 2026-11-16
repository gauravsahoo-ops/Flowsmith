"""Pure pause/auth/terminal decisions for a finished workflow run.

``run_job`` used to inline three decision trees: keep an execution paused for
approval, pause it for credential re-authentication, or finalize it with the
merged trace/results of a replay. This module owns those decisions as pure
functions so they can be tested directly. The runtime keeps every side
effect: database commits, delivery linking, telemetry, events, error
handlers, and the queue contract.

No ``app.api`` imports: this package is a domain layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.engine.executor import ExecutionResult

AUTH_ERROR_CODES = frozenset(
    {
        "AUTH_FAILED",
        "CONNECTOR_AUTH_FAILED",
        "REAUTHORIZATION_REQUIRED",
        "MANUAL_ACTION_REQUIRED",
        "CREDENTIALS_REQUIRED",
        "EXPIRED_TOKEN",
    }
)
AUTH_MESSAGE_HINTS = (
    "token expired",
    "authentication",
    "unauthorized",
    "invalid_grant",
    "credentials required",
)
CANCELLED_ERROR = {
    "code": "CANCELLED",
    "message": "Execution cancelled by user.",
}


@dataclass(frozen=True)
class AuthFailure:
    """The credential-bearing node that needs the user to reconnect."""

    node_id: str | None
    credential_id: str | None
    credential_name: str


@dataclass(frozen=True)
class PausePlan:
    """Persisted snapshot for a run paused on approval."""

    status: str
    node_statuses: dict[str, str]
    trace: list[dict[str, Any]]
    results: dict[str, Any]
    pause_state: dict[str, Any] | None


@dataclass(frozen=True)
class AuthPausePlan:
    """Persisted snapshot for a run paused on credential re-authentication."""

    status: str
    node_statuses: dict[str, str]
    trace: list[dict[str, Any]]
    results: dict[str, Any]
    pause_state: dict[str, Any]
    credential_id: str | None
    node_id: str | None
    node_name: str


@dataclass(frozen=True)
class TerminalPlan:
    """Terminal execution fields produced from the engine's run result."""

    status: str
    node_statuses: dict[str, str]
    trace: list[dict[str, Any]]
    results: dict[str, Any]
    error: dict[str, Any] | None


def node_statuses(
    events: list[dict[str, Any]], *, execution_id: str | None = None
) -> dict[str, str]:
    """Collapse node events into the persisted status map.

    Sub-workflow child events are forwarded through the parent's sink with
    the child's ``execution_id``. When *execution_id* is given, only events
    for that run are considered so a child cannot overwrite the parent's
    per-node statuses.
    """
    statuses: dict[str, str] = {}
    for ev in events:
        if execution_id is not None and ev.get("execution_id") != execution_id:
            continue
        nid = ev.get("node_id")
        if nid:
            statuses[nid] = ev.get("status", "success")
    return statuses


def is_pause(rec_status: str | None, result: ExecutionResult) -> bool:
    """A run stays open when the row already paused or the engine says so."""
    return rec_status == "waiting_approval" or bool(result.paused)


def build_pause_plan(
    result: ExecutionResult,
    existing_node_statuses: Mapping[str, str] | None,
    *,
    execution_id: str | None = None,
) -> PausePlan:
    """Merge pause progress without finalizing the execution row.

    A node that is already ``waiting_approval`` keeps that status: a resumed
    run may emit events for nodes that are still waiting for a human.
    """
    merged = dict(existing_node_statuses or {})
    for nid, st in node_statuses(result.events, execution_id=execution_id).items():
        if merged.get(nid) != "waiting_approval":
            merged[nid] = st
    if result.paused_node_id:
        merged[result.paused_node_id] = "waiting_approval"

    pause_state: dict[str, Any] | None = None
    if result.pause_info:
        pause_state = result.pause_info.get("pause_state") or result.pause_info

    return PausePlan(
        status="waiting_approval",
        node_statuses=merged,
        trace=result.trace,
        results={
            "outputs": dict(result.results or {}),
            "inputs": dict(result.inputs or {}),
        },
        pause_state=pause_state,
    )


def classify_auth_failure(
    result: ExecutionResult,
    workflow_data: Mapping[str, Any] | None,
) -> AuthFailure | None:
    """Return the auth failure behind a failed run, if there is one.

    The credential id is looked up on the failed workflow node. When the
    node cannot be matched (or carries no credentials) the id stays ``None``
    and the name falls back to ``"Integration"``; callers decide whether
    that is resumable.
    """
    if result.status != "failed" or result.error is None:
        return None

    code = getattr(result.error, "code", None)
    message = str(getattr(result.error, "message", "") or "")
    if code not in AUTH_ERROR_CODES and not any(
        hint in message.lower() for hint in AUTH_MESSAGE_HINTS
    ):
        return None

    failed_node_id = getattr(result.error, "node_id", None)
    if not failed_node_id and result.trace:
        last_step = result.trace[-1]
        if last_step.get("status") == "error":
            failed_node_id = last_step.get("node_id")

    failed_cred_id = None
    failed_cred_name = "Integration"
    if failed_node_id and workflow_data:
        for node_def in workflow_data.get("nodes") or []:
            if node_def.get("id") == failed_node_id:
                creds = node_def.get("credentials") or {}
                if creds:
                    failed_cred_id = next((cid for cid in creds.values() if cid), None)
                failed_cred_name = (
                    node_def.get("name")
                    or node_def.get("label")
                    or failed_node_id
                )
                break

    return AuthFailure(
        node_id=failed_node_id,
        credential_id=failed_cred_id,
        credential_name=failed_cred_name,
    )


def build_auth_pause_plan(
    result: ExecutionResult,
    failure: AuthFailure,
    existing_node_statuses: Mapping[str, str] | None,
    *,
    now: datetime,
    execution_id: str | None = None,
) -> AuthPausePlan:
    """Pause the run in ``waiting_auth``; only outputs are persisted."""
    merged = dict(existing_node_statuses or {})
    for nid, st in node_statuses(result.events, execution_id=execution_id).items():
        merged[nid] = "waiting_auth" if nid == failure.node_id else st

    pause_state = {
        "type": "auth_required",
        "credential_id": failure.credential_id,
        "node_id": failure.node_id,
        "node_name": failure.credential_name,
        "message": (
            "Execution paused: authentication required for connection "
            f"'{failure.credential_name}'. Reconnect integration to resume."
        ),
        "paused_at": now.isoformat(),
    }

    return AuthPausePlan(
        status="waiting_auth",
        node_statuses=merged,
        trace=result.trace,
        results={"outputs": result.results},
        pause_state=pause_state,
        credential_id=failure.credential_id,
        node_id=failure.node_id,
        node_name=failure.credential_name,
    )


def terminal_status(
    result: ExecutionResult,
    *,
    rec_status: str | None,
    cancel_requested: bool,
) -> str:
    """Resolve the durable status, with timeout winning every race."""
    if result.status == "timeout":
        return "timeout"
    if (
        rec_status in ("cancelling", "cancelled")
        or result.status == "cancelled"
        or cancel_requested
    ):
        return "cancelled"
    return result.status


def build_terminal_plan(
    result: ExecutionResult,
    *,
    decision: Mapping[str, Any] | None,
    mode: str,
    rec_status: str | None,
    cancel_requested: bool,
    existing_node_statuses: Mapping[str, str] | None,
    source_results: Mapping[str, Any] | None,
    prior_inputs: Mapping[str, Any] | None,
    upstream: Iterable[str] | None,
    doomed: Iterable[str] | None,
    execution_id: str | None = None,
) -> TerminalPlan:
    """Shape the terminal row fields, including replay merges.

    ``source_results`` is the persisted outcome of the execution a run
    continues (``outputs``/``inputs``/``trace`` keys); ``None`` means the
    run has no source to merge. ``existing_node_statuses`` are that
    source's persisted node statuses. ``prior_inputs`` are the source's
    inputs used to prune upstream entries the source never produced.
    """
    stored: dict[str, Any] = {
        "outputs": dict(result.results or {}),
        "inputs": dict(result.inputs or {}),
    }
    # Surface the human decision with the run record (Phase 36).
    if decision is not None:
        stored["approval"] = {
            "node_id": decision.get("node_id"),
            "approved": bool(decision.get("approved")),
            "approved_by": decision.get("approved_by"),
            "approved_at": decision.get("approved_at"),
        }
    # Phase 14: PASS/FAIL/DIFF test report.
    if getattr(result, "test_report", None) is not None:
        stored["tests"] = result.test_report

    upstream_ids = set(upstream or ())
    target_upstream = (
        upstream_ids - set(doomed or ()) if mode == "node_retry" else upstream_ids
    )

    if source_results is not None:
        # Merge prior outputs & inputs.
        merged_outputs = dict(source_results.get("outputs", {}))
        merged_outputs.update(result.results or {})
        stored["outputs"] = merged_outputs

        merged_inputs = dict(source_results.get("inputs", {}))
        merged_inputs.update(result.inputs or {})
        stored["inputs"] = merged_inputs

        # Only a run-node replay merges traces; a retry trace reflects just
        # the steps executed in this run.
        if mode == "run_node":
            prior_trace = [
                step
                for step in (source_results.get("trace") or [])
                if step.get("node_id") in target_upstream
            ]
            new_node_ids = {step.get("node_id") for step in result.trace}
            merged_trace = [
                step
                for step in prior_trace
                if step.get("node_id") not in new_node_ids
            ] + list(result.trace)
            merged_trace.sort(key=lambda step: step.get("started_at") or "")
            trace = merged_trace
        else:
            trace = result.trace

        # Prior statuses survive only for replayable upstream nodes.
        prior_statuses = {
            nid: st
            for nid, st in dict(existing_node_statuses or {}).items()
            if nid in target_upstream
        }
        merged_statuses = dict(prior_statuses)
        merged_statuses.update(
            node_statuses(result.events, execution_id=execution_id)
        )
        statuses = merged_statuses
    else:
        trace = result.trace
        statuses = node_statuses(result.events, execution_id=execution_id)

    if mode == "run_node":
        # Drop upstream entries this run fabricated as seeds: they must not
        # look like real outputs of the source execution.
        prior_output_ids = (
            source_results.get("outputs", {}) if source_results is not None else {}
        )
        preserved_inputs = dict(prior_inputs or {})
        outputs = stored.get("outputs", {})
        inputs = stored.get("inputs", {})
        for uid in upstream_ids:
            if uid not in prior_output_ids and uid in outputs:
                del outputs[uid]
            if uid not in preserved_inputs and uid in inputs:
                del inputs[uid]

    return TerminalPlan(
        status=terminal_status(
            result,
            rec_status=rec_status,
            cancel_requested=cancel_requested,
        ),
        node_statuses=statuses,
        trace=trace,
        results=stored,
        error=result.error.to_dict() if result.error else None,
    )


def mark_deliveries(db: Session, execution_id: str, status_value: str) -> None:
    """Spec 32: link delivery records to their execution's final outcome."""
    from app.models import WebhookDelivery

    rows = db.scalars(
        select(WebhookDelivery).where(WebhookDelivery.execution_id == execution_id)
    ).all()
    for row in rows:
        row.status = status_value
    if rows:
        db.commit()
