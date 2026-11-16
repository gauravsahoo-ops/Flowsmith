"""Shared execution runtime (Phase 15, spec 13/34/58).

Runs one claimed queue job end-to-end: marks the execution ``running``,
executes the workflow snapshot with credential resolution, persists the
outcome, links webhook deliveries, updates metrics. Used identically by
the embedded consumer (inside the API process) and by external worker
processes (`python -m app.queue.worker`) — workers are stateless, so
any worker can run any job (spec 34).

The lifecycle itself lives in ``app.orchestration.run_coordinator``; this
module keeps the process-facing surface the queue worker and the API rely
on: session ownership, control-plane injection (env resolution, error
handlers, HTTP client) and the backward-compatible helper names.

Cancellation is cooperative and durable (spec 36): the cancel endpoint
marks the execution ``cancelling`` in the database; a monitor task polls
that flag and flips an in-process event the engine checks between nodes.
This works across processes (external workers) and survives restarts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.engine.executor import execute_workflow
from app.orchestration import cancellation
from app.orchestration.checkpoint import ancestor_ids
from app.orchestration.finalizer import (
    mark_deliveries,
    node_statuses,
)
from app.orchestration.run_coordinator import (
    RunCoordinator,
    finish_test_run,
    node_error_codes,
)
from app.queue import QueueJob

logger = logging.getLogger("runtime")

EventSink = Callable[[dict[str, Any]], None]


def signal_cancel(execution_id: str) -> bool:
    """Instantly flip the cancel event if this execution is running in the current process."""
    return cancellation.signal(execution_id)


async def _commit(db: Session) -> None:
    """Run the sync-driver commit off the event loop (it blocks otherwise)."""
    await asyncio.to_thread(db.commit)


def _node_error_codes(trace: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Back-compat alias for the coordinator's trace-error helper."""
    return node_error_codes(trace)


def _finish_test_run(
    rec: Any,
    job: QueueJob,
    test_spec: dict[str, Any],
    result: Any,
) -> Any:
    """Back-compat alias for the coordinator's test-run finalizer."""
    return finish_test_run(rec, job, test_spec, result)


def _ancestor_ids(connections: list[dict], target_id: str) -> set[str]:
    """Back-compat alias for the pure checkpoint seed planner."""
    return ancestor_ids(connections, target_id)


def _mark_deliveries(db: Session, execution_id: str, status_value: str) -> None:
    """Back-compat wrapper for the finalizer's delivery link helper."""
    mark_deliveries(db, execution_id, status_value)


def _node_statuses(
    events: list[dict[str, Any]], *, execution_id: str | None = None
) -> dict[str, str]:
    """Back-compat wrapper for the finalizer's node-status collapse."""
    return node_statuses(events, execution_id=execution_id)


async def run_job(job: QueueJob, event_sink: EventSink) -> str:
    """Execute the job; returns the terminal execution status.

    The status drives the queue's ``complete()`` call so the job row
    mirrors the execution's final state (spec 25.3: the executions
    table stays authoritative).
    """
    db = get_session()
    try:
        coordinator = RunCoordinator(
            db,
            job,
            event_sink,
            # Resolve the control-plane callables at call time so tests that
            # patch ``app.execution_runtime.*`` keep controlling the run.
            execute_workflow=execute_workflow,
            resolve_env_vars=_resolve_env_vars,
            start_error_workflow=_maybe_run_error_workflow,
            http_client=_http_client,
        )
        return await coordinator.run()
    finally:
        db.close()


def _maybe_run_error_workflow(
    db: Session, job: QueueJob, execution_id: str, error: dict[str, Any] | None,
) -> None:
    """Multi-level error workflow (Phase 14): on a failed run, start the handler
    workflow named by:
    1. Workflow-level settings: ``settings.on_error_workflow_id``
    2. Workspace-level: workspace env variable ``DEFAULT_ERROR_WORKFLOW_ID``
    3. Workspace error handler: any active workflow in the workspace containing an ``error_trigger`` node

    Strictly best-effort and single-level: handler runs use trigger
    ``error_handler`` and never cascade; test-mode runs never fire handlers;
    everything is swallowed so the original failed record is always preserved.
    """
    try:
        if job.trigger == "error_handler":
            return
        if (job.payload or {}).get("_test_run") is not None:
            return
        settings = ((job.workflow_data or {}).get("settings") or {})
        handler_id = str(settings.get("on_error_workflow_id") or "").strip()

        from app.api.executions import workflow_workspace
        ws_id = job.workspace_id or workflow_workspace(db, job.workflow_id)

        # Level 2 & 3: Workspace-level fallback if not specified on the workflow itself
        if not handler_id or handler_id == job.workflow_id:
            handler_id = ""
            if ws_id:
                from app.models import Environment
                env_row = db.execute(
                    select(Environment).where(
                        Environment.workspace_id == ws_id,
                        Environment.key == "DEFAULT_ERROR_WORKFLOW_ID",
                    )
                ).scalar_one_or_none()
                if env_row and env_row.value:
                    from app.environments import decrypt_env_value
                    handler_id = decrypt_env_value(env_row.value).strip()

            if not handler_id and ws_id:
                from app.models import WorkflowRecord
                candidate_wfs = db.execute(
                    select(WorkflowRecord).where(
                        WorkflowRecord.workspace_id == ws_id,
                        WorkflowRecord.active.is_(True),
                        WorkflowRecord.deleted_at.is_(None),
                        WorkflowRecord.id != job.workflow_id,
                    )
                ).scalars().all()
                for cw in candidate_wfs:
                    nodes = (cw.data or {}).get("nodes", [])
                    if any(n.get("type") == "error_trigger" for n in nodes):
                        handler_id = cw.id
                        break

        if not handler_id or handler_id == job.workflow_id:
            return

        from app.models import WorkflowRecord

        handler = db.get(WorkflowRecord, handler_id)
        if handler is None or not handler.active:
            return
        from app.api.executions import start_execution

        start_execution(
            db,
            workflow_id=handler.id,
            user_id=handler.user_id,
            version=handler.version,
            workflow_data=handler.data,
            trigger="error_handler",
            trigger_items=[{
                "error": error or {},
                "failed_execution_id": execution_id,
                "failed_workflow_id": job.workflow_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }],
            workspace_id=workflow_workspace(db, handler.id),
        )
        logger.info("error workflow %s started for failed execution %s", handler_id, execution_id)
    except Exception:
        logger.exception("error workflow hook failed for %s", execution_id)


def _http_client(*, mocked: bool = False) -> Any:
    """Shared httpx client (built once; SSL context load is expensive).

    Test-mode runs get a mock-aware wrapper: matched outbound calls
    answer locally, unmatched ones are blocked (Phase 14). Connectors
    are covered separately via SafeHTTPClient's ContextVar check.
    """
    from app.runner import runner

    client = runner.get_http_client()
    if mocked:
        from app.security.http_mocks import MockedHttpClient

        return MockedHttpClient(client)
    return client


def _resolve_env_vars(db: Session, job: QueueJob) -> dict[str, str]:
    """Workspace env vars for this job (Phase 31).

    Prefers the workspace captured at enqueue time; falls back to a
    workflow lookup for jobs queued before the upgrade.
    """
    from app.api.executions import workflow_workspace
    from app.environments import resolve_env_vars

    workspace_id = job.workspace_id or workflow_workspace(db, job.workflow_id)
    if not workspace_id and job.user_id:
        workspace_id = f"ws_personal_{job.user_id}"
    if workspace_id and job.user_id:
        from app.api.access import workspace_can_view

        # A workflow can be shared to a user who is not a member of the
        # workspace that scopes its environment. Never hand that user the
        # workspace's secrets merely because they can execute the workflow.
        if not workspace_can_view(db, workspace_id, job.user_id):
            logger.warning(
                "env resolution denied for %s: user %s cannot access workspace %s",
                job.execution_id,
                job.user_id,
                workspace_id,
            )
            return {}
    try:
        return resolve_env_vars(db, workspace_id)
    except Exception:
        logger.exception("env resolution failed for %s", job.execution_id)
        return {}
