"""Shared execution runtime (Phase 15, spec 13/34/58).

Runs one claimed queue job end-to-end: marks the execution ``running``,
executes the workflow snapshot with credential resolution, persists the
outcome, links webhook deliveries, updates metrics. Used identically by
the embedded consumer (inside the API process) and by external worker
processes (`python -m app.queue.worker`) — workers are stateless, so
any worker can run any job (spec 34).

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

from sqlalchemy.orm import Session

from app.credentials import service as credential_service
from app.credentials.type_registry import get_credential_type_registry
from app.db import get_session
from app.engine.errors import NodeExecutionError, WorkflowValidationError
from app.engine.executor import execute_workflow
from app.metrics import execution_finished
from app.models import Execution as ExecutionModel
from app.queue import QueueJob
from app.schemas.workflow import Workflow

logger = logging.getLogger("runtime")

CANCEL_POLL_S = 0.25

EventSink = Callable[[dict[str, Any]], None]


def _node_statuses(events: list[dict[str, Any]]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for ev in events:
        nid = ev.get("node_id")
        if nid:
            statuses[nid] = ev.get("status", "success")
    return statuses


def _mark_deliveries(db: Session, execution_id: str, status_value: str) -> None:
    """Spec 32: link delivery records to their execution's final outcome."""
    from sqlalchemy import select

    from app.models import WebhookDelivery

    rows = db.scalars(
        select(WebhookDelivery).where(WebhookDelivery.execution_id == execution_id)
    ).all()
    for row in rows:
        row.status = status_value
    if rows:
        db.commit()


async def _watch_cancel(execution_id: str, cancel_event: asyncio.Event) -> None:
    """Poll the DB for the durable cancel flag; flip the local event."""
    from app.models import Execution

    while not cancel_event.is_set():
        db = get_session()
        try:
            rec = db.get(Execution, execution_id)
            if rec is not None and rec.status in ("cancelling", "cancelled"):
                cancel_event.set()
        except Exception:
            logger.exception("cancel watch failed for %s", execution_id)
        finally:
            db.close()
        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=CANCEL_POLL_S)
        except asyncio.TimeoutError:
            pass


def _node_error_codes(trace: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-node error payloads from the run's trace steps (Phase 14).

    Lets `error_code` test assertions pin the typed error of a specific
    node instead of guessing from the workflow-level error.
    """
    errors: dict[str, dict[str, Any]] = {}
    for step in trace or []:
        err = step.get("error")
        if isinstance(err, dict) and step.get("node_id"):
            errors[step["node_id"]] = err
    return errors


def _finish_test_run(
    rec: ExecutionModel,
    job: QueueJob,
    test_spec: dict[str, Any],
    result: Any,
) -> Any:
    """Finalize a test-mode run (Phase 14).

    The execution row keeps the WORKFLOW's own terminal status: a red
    regression must not masquerade as a crashed execution and vice
    versa — the PASS/FAIL verdict lives exclusively in the persisted
    report under ``results["tests"]``. The report is stamped with the
    workflow/test identity so listings can group mock runs.
    """
    report = getattr(result, "test_report", None)
    if isinstance(report, dict):
        report.setdefault("workflow_id", job.workflow_id)
        report["test_mode"] = True
        result.test_report = report
    return result


def _ancestor_ids(connections: list[dict], target_id: str) -> set[str]:
    """Return all upstream ancestor node IDs of *target_id* (BFS)."""
    from collections import deque

    parent_map: dict[str, set[str]] = {}
    for conn in connections:
        src = conn.get("source", "")
        tgt = conn.get("target", "")
        parent_map.setdefault(tgt, set()).add(src)

    visited: set[str] = set()
    queue = deque(parent_map.get(target_id, set()))
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        queue.extend(parent_map.get(nid, set()) - visited)
    return visited


async def run_job(job: QueueJob, event_sink: EventSink) -> str:
    """Execute the job; returns the terminal execution status.

    The status drives the queue's ``complete()`` call so the job row
    mirrors the execution's final state (spec 25.3: the executions
    table stays authoritative).
    """
    execution_id = job.execution_id
    cancel_event = asyncio.Event()
    db = get_session()

    def resolve_credentials(refs: dict[str, str]) -> dict:
        try:
            from app.credentials.resolver import get_credential_resolver
            # Per-run credential cache: same cred fetched/decrypted once per execution
            if not hasattr(resolve_credentials, "_cache"):
                resolve_credentials._cache = {}  # type: ignore[attr-defined]
            out = {}
            for ctype, cid in refs.items():
                cache_key = f"{job.user_id}:{cid}"
                if cache_key not in resolve_credentials._cache:  # type: ignore[attr-defined]
                    resolved_map = get_credential_resolver().resolve_map(db, job.user_id, {ctype: cid})
                    if ctype in resolved_map and isinstance(resolved_map[ctype], dict):
                        resolved_map[ctype]["_credential_id"] = cid
                    resolve_credentials._cache[cache_key] = resolved_map  # type: ignore[attr-defined]
                out[ctype] = resolve_credentials._cache[cache_key][ctype]  # type: ignore[attr-defined]
            return out
        except (credential_service.CredentialError, ValueError) as exc:
            code = getattr(exc, "code", None) or ("CREDENTIAL_PROVIDER_NOT_IMPLEMENTED" if "not implemented" in str(exc).lower() else "CREDENTIALS_REQUIRED")
            raise NodeExecutionError(str(exc), code=code, node_id="") from exc

    try:
        rec = db.get(ExecutionModel, execution_id)
        if rec is None:
            return "failed"
        if rec.status == "cancelling":
            # Cancelled before a worker picked it up (spec 36). Publish
            # the terminal event so live streams and the durable events
            # table reflect the outcome (spec 37).
            rec.status = "cancelled"
            rec.finished_at = datetime.now(UTC)
            db.commit()
            event_sink({
                "event": "execution.cancelled",
                "execution_id": execution_id,
                "workflow_id": job.workflow_data.get("id"),
                "node_id": None,
                "status": "cancelled",
            })
            return "cancelled"
        rec.status = "running"
        db.commit()

        monitor = asyncio.create_task(_watch_cancel(execution_id, cancel_event))
        try:
            workflow = Workflow.model_validate(job.workflow_data)
            env_vars = _resolve_env_vars(db, job)
            # Durable approval resume (Phase 32) + safe node retry
            # (Phase 13): replay persisted node outputs so upstream side
            # effects never re-run.
            decision = (job.payload or {}).get("_approval_data")
            retry_from_node = (job.payload or {}).get("_retry_from_node")
            run_node = (job.payload or {}).get("_run_node")
            run_to_node = (job.payload or {}).get("_run_to_node")
            # Phase 14: first-class workflow tests — mocks installed for
            # the whole execution; unmatched outbound calls are BLOCKED so
            # a test can never touch production systems.
            test_spec = (job.payload or {}).get("_test_run")
            # Safe node retry runs in a NEW execution row: the persisted
            # outputs to seed from live on the SOURCE execution.
            retry_source_id = (job.payload or {}).get("_retry_source") or execution_id
            retry_source_rec = (
                db.get(ExecutionModel, retry_source_id)
                if retry_from_node and retry_source_id != execution_id
                else rec
            )
            initial_results: dict[str, dict[str, list[dict[str, Any]]]] | None = None
            storage_seed: dict[str, Any] | None = None
            if decision is not None:
                outputs = (rec.results or {}).get("outputs")
                if isinstance(outputs, dict):
                    # Replay everything EXCEPT the paused node itself:
                    # it must run again to consume the recorded decision.
                    paused_node = (decision or {}).get("node_id")
                    initial_results = {
                        nid: by_handle
                        for nid, by_handle in outputs.items()
                        if nid != paused_node
                    }
                storage_seed = {"_approval_data": decision}
                db.expire(rec)
                rec.status = "running"
                rec.error = None
                db.commit()
            elif retry_from_node:
                # Safe node retry: seed every upstream output EXCEPT the
                # failed node and its descendants — they re-run on fresh
                # data. The engine skips seeded nodes entirely, so no
                # upstream side effect is ever repeated.
                from app.engine.graph import descendant_ids

                doomed = descendant_ids(
                    (job.workflow_data or {}).get("connections", []), retry_from_node,
                )
                doomed.add(retry_from_node)
                outputs = ((retry_source_rec.results if retry_source_rec else None) or {}).get("outputs")
                if isinstance(outputs, dict):
                    initial_results = {
                        nid: by_handle
                        for nid, by_handle in outputs.items()
                        if nid not in doomed
                    }
                db.expire(rec)
                rec.status = "running"
                rec.error = None
                db.commit()
            elif run_node:
                # Single-node execution: seed ALL other nodes as empty
                # so only the target node runs.  Upstream parents get a
                # single empty item so the target receives input; other
                # nodes get empty arrays so they produce no downstream flow.
                from app.engine.graph import descendant_ids

                all_nodes = {n.get("id") for n in (job.workflow_data or {}).get("nodes", [])}
                connections = (job.workflow_data or {}).get("connections", [])
                # Find all upstream ancestors of the target (parents, grandparents, etc.)
                upstream = _ancestor_ids(connections, run_node)
                initial_results = {}
                for nid in all_nodes:
                    if nid == run_node:
                        continue
                    if nid in upstream:
                        # Upstream parents: provide a single empty item
                        # so the target node has at least one input.
                        initial_results[nid] = {"main": [{}]}
                    else:
                        # Non-upstream, non-target: empty output (skipped flow)
                        initial_results[nid] = {"main": []}
                db.expire(rec)
                rec.status = "running"
                rec.error = None
                db.commit()
            elif run_to_node:
                # Run-to-node: execute the chain up to (and including)
                # the target; seed all downstream nodes as skipped.
                from app.engine.graph import descendant_ids

                downstream = descendant_ids(
                    (job.workflow_data or {}).get("connections", []), run_to_node,
                )
                # Remove the target itself — it should run, not be seeded.
                downstream.discard(run_to_node)
                initial_results = {
                    nid: {"main": []}
                    for nid in downstream
                }
                db.expire(rec)
                rec.status = "running"
                rec.error = None
                db.commit()
            else:
                db.expire(rec)
                rec.status = "running"
                db.commit()
            # Pre-execution credential validation: catch unimplemented
            # providers BEFORE the workflow runs so users get clear errors
            # at queue time rather than opaque runtime failures.
            for wf_node in (job.workflow_data or {}).get("nodes", []):
                creds = wf_node.get("credentials") or {}
                for cred_type, cred_id in creds.items():
                    if not cred_id:
                        continue
                    type_reg = get_credential_type_registry()
                    entry = type_reg.get(cred_type)
                    if entry and not entry.get("implemented"):
                        raise WorkflowValidationError([{
                            "code": "CREDENTIAL_PROVIDER_NOT_IMPLEMENTED",
                            "node_id": wf_node.get("id", "unknown"),
                            "field": f"credentials.{cred_type}",
                            "message": f"Authentication provider '{entry.get('provider')}' for credential type '{cred_type}' is not implemented yet.",
                        }])
                # Also check generic auth_type for http_request nodes
                if wf_node.get("type") == "http_request":
                    params = wf_node.get("parameters") or {}
                    if params.get("authentication") == "generic":
                        at = params.get("auth_type", "none")
                        if at not in ("none", ""):
                            from app.credentials.registry import CREDENTIAL_IMPLEMENTED
                            m = {"bearer":"bearer_auth","basic":"basic_auth","header":"header_auth","query":"query_auth","digest":"digest_auth","custom":"custom_auth","oauth2":"oauth2","oauth1":"oauth1","api_key":"header_auth"}
                            ct = m.get(at, at)
                            if ct in CREDENTIAL_IMPLEMENTED and not CREDENTIAL_IMPLEMENTED.get(ct):
                                raise WorkflowValidationError([{
                                    "code": "CREDENTIAL_PROVIDER_NOT_IMPLEMENTED",
                                    "node_id": wf_node.get("id", "unknown"),
                                    "field": "parameters.auth_type",
                                    "message": f"Authentication provider '{at}' for credential type '{ct}' is not implemented yet.",
                                }])
            mock_token = None
            if test_spec is not None:
                from app.security import http_mocks

                mock_token = http_mocks.install(
                    http_mocks.compile_rules(test_spec.get("mocks"))
                )
            try:
                result = await execute_workflow(
                    workflow,
                    job.trigger_items,
                    execution_id=execution_id,
                    cancel_event=cancel_event,
                    http_client=_http_client(mocked=test_spec is not None),
                    event_sink=event_sink,
                    credential_resolver=resolve_credentials,
                    env_vars=env_vars,
                    initial_results=initial_results,
                    storage_seed=storage_seed,
                    workspace_id=job.workspace_id,
                    user_id=job.user_id,
                )
            finally:
                if mock_token is not None:
                    from app.security import http_mocks

                    http_mocks.reset(mock_token)
            if test_spec is not None:
                # Phase 14: PASS/FAIL/DIFF report from the test spec.
                from app.testing.service import evaluate_test

                result.test_report = evaluate_test(test_spec, {
                    "status": result.status,
                    "error": result.error.to_dict() if result.error else None,
                    "node_statuses": _node_statuses(result.events),
                    "node_errors": _node_error_codes(result.trace),
                    "results": {"outputs": result.results},
                })
            if test_spec is not None:
                result = _finish_test_run(rec, job, test_spec, result)
            db.expire(rec)
            rec = db.get(ExecutionModel, execution_id)
            if rec is not None and rec.status == "waiting_approval":
                # The run paused at an approval node: keep the execution
                # open (spec 25.2). Persist progress, but no terminal
                # status or finished_at — resume continues this row.
                merged = dict(rec.node_statuses or {})
                for nid, st in _node_statuses(result.events).items():
                    if merged.get(nid) != "waiting_approval":
                        merged[nid] = st
                rec.node_statuses = merged
                rec.trace = result.trace
                if not rec.results:
                    rec.results = {"outputs": result.results}
                db.commit()
                _mark_deliveries(db, execution_id, "waiting_approval")
                return "waiting_approval"
            if rec is not None:
                rec.status = result.status
                rec.finished_at = datetime.now(UTC)
                stored: dict[str, Any] = {"outputs": result.results}
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
                rec.results = stored
                rec.node_statuses = _node_statuses(result.events)
                rec.trace = result.trace
                rec.error = result.error.to_dict() if result.error else None
                rec.pause_state = None
                db.commit()
            _mark_deliveries(db, execution_id, result.status)
            execution_finished(execution_id, result.status, job.trigger)
            if result.status == "failed" and result.error is not None:
                _maybe_run_error_workflow(db, job, execution_id, result.error.to_dict())
            return result.status
        finally:
            monitor.cancel()
    except asyncio.CancelledError:
        raise
    except WorkflowValidationError as exc:
        # The workflow snapshot is invalid (bad params, unknown nodes,
        # cycles...). Not a crash: surface the issues so the user can
        # fix the workflow instead of seeing an opaque EXECUTION_CRASHED.
        logger.warning("execution %s rejected at validation: %s", execution_id, exc.message)
        execution_finished(execution_id, "failed", job.trigger)
        rec = db.get(ExecutionModel, execution_id)
        if rec is not None:
            rec.status = "failed"
            rec.finished_at = datetime.now(UTC)
            rec.error = exc.to_dict()
            db.commit()
        _mark_deliveries(db, execution_id, "failed")
        return "failed"
    except Exception as exc:  # never lose the record (spec 34.1)
        logger.exception("execution %s crashed", execution_id)
        execution_finished(execution_id, "failed", job.trigger)
        rec = db.get(ExecutionModel, execution_id)
        crash_error = {"code": "EXECUTION_CRASHED", "message": str(exc)}
        if rec is not None:
            rec.status = "failed"
            rec.finished_at = datetime.now(UTC)
            rec.error = crash_error
            db.commit()
        _mark_deliveries(db, execution_id, "failed")
        _maybe_run_error_workflow(db, job, execution_id, crash_error)
        return "failed"
    finally:
        db.close()


def _maybe_run_error_workflow(
    db: Session, job: QueueJob, execution_id: str, error: dict[str, Any] | None,
) -> None:
    """Global error workflow (Batch D): on a failed run, start the handler
    workflow named by ``settings.on_error_workflow_id`` with the failure
    context. Strictly best-effort and single-level: handler runs use
    trigger ``error_handler`` and never cascade; test-mode runs never
    fire handlers; everything is swallowed so the original failed record
    is always preserved.
    """
    try:
        if job.trigger == "error_handler":
            return
        if (job.payload or {}).get("_test_run") is not None:
            return
        settings = ((job.workflow_data or {}).get("settings") or {})
        handler_id = str(settings.get("on_error_workflow_id") or "").strip()
        if not handler_id or handler_id == job.workflow_id:
            return
        from app.models import WorkflowRecord

        handler = db.get(WorkflowRecord, handler_id)
        if handler is None or not handler.active:
            return
        from app.api.executions import start_execution, workflow_workspace

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
    try:
        return resolve_env_vars(db, workspace_id)
    except Exception:
        logger.exception("env resolution failed for %s", job.execution_id)
        return {}
