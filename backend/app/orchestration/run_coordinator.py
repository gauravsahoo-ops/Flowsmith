"""Run coordinator: one claimed queue job, executed end-to-end.

This module composes the already-extracted boundaries — seed planning
(``checkpoint``), process-local + durable cancellation (``cancellation``),
and the pause/auth/terminal decisions (``finalizer``) — with the engine's
``execute_workflow`` and the control-plane callables injected by
``app.execution_runtime``.

The coordinator owns the execution row lifecycle and every side effect
(commits, deliveries, telemetry, metrics, error monitoring, error
handlers, events), but never the database session: ``run_job`` creates and
closes the session and passes it in. That keeps the queue/worker contract
(``run_job`` returns the execution status) unchanged.

No ``app.api`` imports: the control plane is injected, so the
architecture boundary stays intact.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.credentials import service as credential_service
from app.credentials.type_registry import get_credential_type_registry
from app.engine.errors import NodeExecutionError, WorkflowValidationError
from app.metrics import execution_finished
from app.models import Execution as ExecutionModel
from app.orchestration.cancellation import register, unregister, watch_durable_cancel
from app.orchestration.checkpoint import plan_seed
from app.orchestration.finalizer import (
    CANCELLED_ERROR,
    build_auth_pause_plan,
    build_pause_plan,
    build_terminal_plan,
    classify_auth_failure,
    is_pause,
    mark_deliveries as _mark_deliveries,
    node_statuses as _node_statuses,
)


def _queue_wait_ms(started_at: datetime, now_utc: datetime) -> float:
    """Milliseconds between queue start and execution start.

    SQLite (used by the live acceptance harness) returns naive datetimes,
    while Postgres returns timezone-aware ones. Normalize before subtracting
    so both backends produce a duration instead of raising TypeError.
    """
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return round(max(0.0, (now_utc - started_at).total_seconds() * 1000.0), 2)
from app.queue import QueueJob
from app.schemas.workflow import Workflow

logger = logging.getLogger("runtime")

EventSink = Callable[[dict[str, Any]], None]
ExecuteWorkflow = Callable[..., Awaitable[Any]]
ResolveEnvVars = Callable[[Session, QueueJob], dict[str, str]]
StartErrorWorkflow = Callable[
    [Session, QueueJob, str, dict[str, Any] | None], None
]
HttpClientFactory = Callable[..., Any]
TestRunEvaluator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


async def _commit(db: Session) -> None:
    """Run the sync-driver commit off the event loop (it blocks otherwise)."""
    await asyncio.to_thread(db.commit)


def node_error_codes(trace: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
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


def finish_test_run(
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


class RunCoordinator:
    """Executes a claimed job and persists its whole lifecycle.

    ``db`` is owned by the caller (``run_job``): the coordinator must not
    close it, and the caller keeps the session open for the entire run.
    """

    def __init__(
        self,
        db: Session,
        job: QueueJob,
        event_sink: EventSink,
        *,
        execute_workflow: ExecuteWorkflow,
        resolve_env_vars: ResolveEnvVars,
        start_error_workflow: StartErrorWorkflow,
        http_client: HttpClientFactory,
        test_run_evaluator: TestRunEvaluator | None = None,
    ) -> None:
        self.db = db
        self.job = job
        self.event_sink = event_sink
        self.execute_workflow = execute_workflow
        self.resolve_env_vars = resolve_env_vars
        self.start_error_workflow = start_error_workflow
        self.http_client = http_client
        self.test_run_evaluator = test_run_evaluator

    def _evaluate_test(
        self, test_spec: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        evaluator = self.test_run_evaluator
        if evaluator is None:
            from app.testing.service import evaluate_test

            evaluator = evaluate_test
        return evaluator(test_spec, payload)

    def _validate_credentials(self, workflow_data: dict[str, Any]) -> None:
        """Pre-execution credential validation.

        Catch unimplemented providers BEFORE the workflow runs so users
        get clear errors at queue time rather than opaque runtime
        failures.
        """
        for wf_node in (workflow_data or {}).get("nodes", []):
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

    async def run(self) -> str:
        """Execute the job; returns the terminal execution status.

        The status drives the queue's ``complete()`` call so the job row
        mirrors the execution's final state (spec 25.3: the executions
        table stays authoritative). Paused runs are terminal for the
        worker: ``waiting_approval`` and ``waiting_auth`` are DONE.
        """
        db = self.db
        job = self.job
        event_sink = self.event_sink
        execution_id = job.execution_id

        # Execution-scoped cache: created fresh for this run, so a
        # rotated/deleted credential is re-resolved on the next execution. Do
        # not move this to a function/module attribute (audit H-5 correction).
        credential_cache: dict[str, dict] = {}

        def resolve_credentials(refs: dict[str, str]) -> dict:
            try:
                from app.credentials.resolver import get_credential_resolver
                out = {}
                for ctype, cid in refs.items():
                    cache_key = f"{job.user_id}:{cid}"
                    if cache_key not in credential_cache:
                        resolved_map = get_credential_resolver().resolve_map(db, job.user_id, {ctype: cid})
                        if ctype in resolved_map and isinstance(resolved_map[ctype], dict):
                            resolved_map[ctype]["_credential_id"] = cid
                        credential_cache[cache_key] = resolved_map
                    out[ctype] = credential_cache[cache_key][ctype]
                return out
            except (credential_service.CredentialError, ValueError) as exc:
                code = getattr(exc, "code", None) or ("CREDENTIAL_PROVIDER_NOT_IMPLEMENTED" if "not implemented" in str(exc).lower() else "CREDENTIALS_REQUIRED")
                raise NodeExecutionError(str(exc), code=code, node_id="") from exc

        try:
            rec = db.get(ExecutionModel, execution_id)
            if rec is None:
                # A consumer connected to a different database can claim a job
                # from the shared queue and then never find the execution row.
                # Without this log the job silently fails and the real
                # execution sits "queued" until the orphan sweep repeats it.
                logger.error(
                    "job %s references execution %s, which does not exist in this "
                    "worker's database; check DATABASE_URL and queue isolation",
                    job.id,
                    execution_id,
                )
                return "failed"
            if rec.status in ("cancelling", "cancelled"):
                # Cancelled before a worker picked it up (spec 36). Publish
                # the terminal event so live streams and the durable events
                # table reflect the outcome (spec 37).
                rec.status = "cancelled"
                rec.finished_at = rec.finished_at or datetime.now(UTC)
                await _commit(db)
                event_sink({
                    "event": "execution.cancelled",
                    "execution_id": execution_id,
                    "workflow_id": job.workflow_data.get("id"),
                    "node_id": None,
                    "status": "cancelled",
                })
                return "cancelled"
            # CAS into "running": a cancel landing between the check above and
            # this write must win instead of being clobbered by an
            # unconditional read-modify-write (same guard class as the API-side
            now_utc = datetime.now(UTC)
            q_wait_ms = None
            if rec.started_at:
                q_wait_ms = _queue_wait_ms(rec.started_at, now_utc)

            flipped = (
                db.query(ExecutionModel)
                .filter(
                    ExecutionModel.id == execution_id,
                    ExecutionModel.status.in_(("queued", "running")),
                )
                .update(
                    {
                        "status": "running",
                        "queue_wait_ms": q_wait_ms,
                    },
                    synchronize_session=False,
                )
            )
            if flipped == 0:
                db.rollback()
                db.expire(rec)
                if rec.status in ("cancelling", "cancelled"):
                    rec.status = "cancelled"
                    rec.finished_at = rec.finished_at or datetime.now(UTC)
                    await _commit(db)
                    event_sink({
                        "event": "execution.cancelled",
                        "execution_id": execution_id,
                        "workflow_id": job.workflow_data.get("id"),
                        "node_id": None,
                        "status": "cancelled",
                    })
                    return "cancelled"
                # Row moved to a terminal state between claim and start — there
                # is nothing left to run; report its current status.
                return rec.status
            await _commit(db)

            cancel_event = register(execution_id)
            monitor = asyncio.create_task(
                watch_durable_cancel(execution_id, cancel_event)
            )
            try:
                workflow = Workflow.model_validate(job.workflow_data)
                env_vars = await asyncio.to_thread(self.resolve_env_vars, db, job)
                # Resume/retry/debugger seeds: the pure planner decides which
                # persisted outputs replay; this runtime loads the source rows.
                payload = job.payload or {}
                retry_from_node = payload.get("_retry_from_node")
                run_node = payload.get("_run_node")
                run_to_node = payload.get("_run_to_node")
                test_spec = payload.get("_test_run")  # Phase 14 test mocks
                # Safe node retry runs in a NEW execution row.
                retry_source_id = payload.get("_retry_source") or execution_id
                retry_source_rec = (
                    db.get(ExecutionModel, retry_source_id)
                    if retry_from_node and retry_source_id != execution_id
                    else rec
                )
                run_source_id = payload.get("_source_execution")
                run_source_rec = (
                    db.get(ExecutionModel, run_source_id)
                    if run_node and run_source_id and run_source_id != execution_id
                    else None
                )
                retry_results = (retry_source_rec.results if retry_source_rec else None) or {}
                run_results = (run_source_rec.results if run_source_rec else None) or {}
                seed = plan_seed(
                    payload,
                    workflow_data=job.workflow_data,
                    outputs=(rec.results or {}).get("outputs"),
                    retry_outputs=retry_results.get("outputs"),
                    run_outputs=run_results.get("outputs") or {},
                )
                decision, upstream, doomed = seed.decision, seed.upstream, seed.doomed
                initial_results, storage_seed = seed.initial_results, seed.storage_seed
                if seed.mode != "fresh":
                    db.expire(rec)
                    rec.status = "running"
                    rec.error = None
                    await _commit(db)
                # The normal path was already CAS-flipped to "running" above;
                # avoid a redundant second commit here.
                self._validate_credentials(job.workflow_data or {})
                mock_token = None
                if test_spec is not None:
                    from app.security import http_mocks

                    mock_token = http_mocks.install(
                        http_mocks.compile_rules(test_spec.get("mocks"))
                    )
                from app.telemetry.tracer import extract_trace_context, start_trace_span

                parent_trace_context = extract_trace_context(job.payload or {})
                wf_title = (job.workflow_data or {}).get("name") or job.workflow_id
                with start_trace_span(
                    f"workflow.execute {wf_title}",
                    attributes={
                        "workflow.id": job.workflow_id,
                        "execution.id": execution_id,
                        "user.id": str(job.user_id),
                        "trigger": job.trigger,
                    },
                    parent_context=parent_trace_context,
                ) as exec_span:
                    try:
                        result = await self.execute_workflow(
                            workflow,
                            job.trigger_items,
                            execution_id=execution_id,
                            cancel_event=cancel_event,
                            http_client=self.http_client(mocked=test_spec is not None),
                            event_sink=event_sink,
                            credential_resolver=resolve_credentials,
                            env_vars=env_vars,
                            initial_results=initial_results,
                            storage_seed=storage_seed,
                            workspace_id=job.workspace_id,
                            user_id=job.user_id,
                        )
                        exec_span.set_attribute("execution.status", result.status)
                    finally:
                        if mock_token is not None:
                            from app.security import http_mocks

                            http_mocks.reset(mock_token)
                if test_spec is not None:
                    # Phase 14: PASS/FAIL/DIFF report from the test spec.
                    result.test_report = self._evaluate_test(test_spec, {
                        "status": result.status,
                        "error": result.error.to_dict() if result.error else None,
                        "node_statuses": _node_statuses(
                            result.events, execution_id=execution_id
                        ),
                        "node_errors": node_error_codes(result.trace),
                        "results": {"outputs": result.results},
                    })
                if test_spec is not None:
                    result = finish_test_run(rec, job, test_spec, result)
                db.expire(rec)
                rec = db.get(ExecutionModel, execution_id)
                if rec is not None and rec.status in ("cancelling", "cancelled"):
                    # Cancellation won the race with the pause write. Never
                    # resurrect a terminal run as waiting_approval.
                    rec.status = "cancelled"
                    rec.finished_at = rec.finished_at or datetime.now(UTC)
                    rec.pause_state = None
                    if rec.error is None:
                        rec.error = dict(CANCELLED_ERROR)
                    await _commit(db)
                    await asyncio.to_thread(_mark_deliveries, db, execution_id, "cancelled")
                    return "cancelled"
                if rec is not None and rec.status in ("success", "failed", "timeout"):
                    # The row was finalized elsewhere (maintenance timeout, a
                    # duplicate delivery, or an operator action). Do not let a
                    # late pause/finish overwrite a terminal outcome.
                    await asyncio.to_thread(_mark_deliveries, db, execution_id, rec.status)
                    return rec.status
                if rec is not None and is_pause(rec.status, result):
                    # The run paused at an approval node or inside an agent tool
                    # loop: keep the execution open (spec 25.2). Persist progress,
                    # but no terminal status or finished_at — resume continues this
                    # row. ``result.paused`` is the engine's authoritative signal;
                    # the row write is normally already done by the node.
                    already_waiting = rec.status == "waiting_approval"
                    plan = build_pause_plan(
                        result, rec.node_statuses or {}, execution_id=execution_id
                    )
                    if not already_waiting:
                        rec.status = plan.status
                        rec.finished_at = None
                        if plan.pause_state is not None:
                            rec.pause_state = plan.pause_state
                    rec.node_statuses = plan.node_statuses
                    rec.trace = plan.trace
                    rec.results = plan.results
                    rec.error = None
                    await _commit(db)
                    await asyncio.to_thread(_mark_deliveries, db, execution_id, "waiting_approval")
                    return "waiting_approval"
                if rec is not None and result.status == "failed":
                    failure = classify_auth_failure(result, job.workflow_data)
                    if failure is not None and failure.credential_id:
                        from app.models.connection_auth_policy import ConnectionAuthPolicy
                        from app.services.recovery_notifications import RecoveryNotificationService

                        policy = db.scalar(select(ConnectionAuthPolicy).where(ConnectionAuthPolicy.credential_id == failure.credential_id))
                        plan = build_auth_pause_plan(
                            result,
                            failure,
                            rec.node_statuses or {},
                            now=datetime.now(UTC),
                            execution_id=execution_id,
                        )
                        logger.info("Pausing execution %s in waiting_auth for credential %s (node: %s)", execution_id, plan.credential_id, plan.node_id)
                        rec.status = plan.status
                        rec.pause_state = plan.pause_state
                        rec.node_statuses = plan.node_statuses
                        rec.trace = plan.trace
                        rec.results = plan.results
                        await _commit(db)
                        await asyncio.to_thread(_mark_deliveries, db, execution_id, "waiting_auth")

                        event_sink({
                            "event": "execution.waiting_auth",
                            "execution_id": execution_id,
                            "workflow_id": job.workflow_data.get("id"),
                            "node_id": plan.node_id,
                            "status": "waiting_auth",
                            "credential_id": plan.credential_id,
                        })

                        if policy and (policy.notify_in_app or policy.notify_email):
                            RecoveryNotificationService.notify_manual_action_required(
                                db=db, policy=policy, credential_name=plan.node_name
                            )
                        return "waiting_auth"

                if rec is not None:
                    source_rec_for_merge = run_source_rec if run_node else (retry_source_rec if retry_from_node else None)
                    merge_source = (
                        source_rec_for_merge
                        if source_rec_for_merge is not None and source_rec_for_merge.id != rec.id
                        else None
                    )
                    source_results = (
                        {
                            "outputs": (merge_source.results or {}).get("outputs", {}),
                            "inputs": (merge_source.results or {}).get("inputs", {}),
                            "trace": merge_source.trace or [],
                        }
                        if merge_source is not None
                        else None
                    )
                    # A retry inherits statuses for every node it did not
                    # re-run; a run-node inherits only its ancestors.
                    merge_upstream = upstream if run_node else {
                        n.get("id")
                        for n in (job.workflow_data or {}).get("nodes", [])
                        if n.get("id")
                    }
                    plan = build_terminal_plan(
                        result,
                        decision=decision,
                        mode=seed.mode,
                        rec_status=rec.status,
                        cancel_requested=cancel_event.is_set(),
                        existing_node_statuses=merge_source.node_statuses if merge_source is not None else None,
                        source_results=source_results,
                        prior_inputs=(
                            (run_source_rec.results or {}).get("inputs", {})
                            if run_node and run_source_rec
                            else {}
                        ),
                        upstream=merge_upstream,
                        doomed=doomed,
                        execution_id=execution_id,
                    )
                    rec.status = plan.status
                    rec.finished_at = datetime.now(UTC)
                    rec.node_statuses = plan.node_statuses
                    rec.trace = plan.trace
                    rec.results = plan.results
                    rec.error = plan.error
                    rec.pause_state = None
                    # Commit the delivery outcome in the same transaction as the
                    # terminal execution state so a client that observes
                    # "success" cannot still see a stale "queued" delivery.
                    await asyncio.to_thread(_mark_deliveries, db, execution_id, result.status)
                    await _commit(db)

                    try:
                        from app.services.telemetry_service import finalize_execution_telemetry
                        await asyncio.to_thread(finalize_execution_telemetry, db, rec, result, job)
                    except Exception:
                        logger.exception("Failed to finalize telemetry for execution %s", execution_id)
                final_status = "cancelled" if (rec and rec.status == "cancelled") else result.status
                await asyncio.to_thread(_mark_deliveries, db, execution_id, final_status)
                execution_finished(execution_id, final_status, job.trigger)
                if final_status in ("failed", "timeout"):
                    err_dict = result.error.to_dict() if result.error else {"code": "EXECUTION_FAILED", "message": "Workflow execution failed."}
                    try:
                        from app.services.error_monitoring import ErrorMonitoringService
                        await asyncio.to_thread(ErrorMonitoringService.capture_execution_error, None, execution_id, job, err_dict, rec)
                    except Exception:
                        logger.exception("Failed to capture error for execution %s", execution_id)
                    if result.error is not None:
                        # Error-handler invocation is best-effort. During worker
                        # shutdown the default executor can already be closed;
                        # that must not overwrite the already-recorded failure
                        # with an EXECUTION_CRASHED status.
                        try:
                            await asyncio.to_thread(
                                self.start_error_workflow,
                                db,
                                job,
                                execution_id,
                                result.error.to_dict(),
                            )
                        except Exception:
                            logger.exception(
                                "Failed to start error workflow for execution %s",
                                execution_id,
                            )
                return final_status
            finally:
                unregister(execution_id)
                monitor.cancel()
        except asyncio.CancelledError:
            unregister(execution_id)
            # Worker-level cancellation (shutdown/stop) must still reach a
            # terminal row — re-raising alone left executions "running" forever
            # (spec 34.1: executions are authoritative).
            logger.warning("execution %s cancelled at worker level", execution_id)
            try:
                execution_finished(execution_id, "cancelled", job.trigger)
                rec = db.get(ExecutionModel, execution_id)
                if rec is not None and rec.status not in ("success", "failed", "cancelled", "timeout"):
                    rec.status = "cancelled"
                    rec.finished_at = datetime.now(UTC)
                    rec.error = {"code": "WORKER_STOPPED", "message": "Worker stopped mid-execution."}
                    await _commit(db)
                await asyncio.to_thread(_mark_deliveries, db, execution_id, "cancelled")
            except Exception:
                logger.exception("failed to record worker-level cancellation of %s", execution_id)
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
                await _commit(db)
            await asyncio.to_thread(_mark_deliveries, db, execution_id, "failed")
            try:
                from app.services.error_monitoring import ErrorMonitoringService
                await asyncio.to_thread(ErrorMonitoringService.capture_execution_error, None, execution_id, job, exc.to_dict(), rec)
            except Exception:
                logger.exception("Failed to capture validation error for execution %s", execution_id)
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
                await _commit(db)
            await asyncio.to_thread(_mark_deliveries, db, execution_id, "failed")
            try:
                from app.services.error_monitoring import ErrorMonitoringService
                await asyncio.to_thread(ErrorMonitoringService.capture_execution_error, None, execution_id, job, crash_error, rec)
            except Exception:
                logger.exception("Failed to capture crash error for execution %s", execution_id)
            try:
                await asyncio.to_thread(self.start_error_workflow, db, job, execution_id, crash_error)
            except Exception:
                logger.exception("Failed to start error workflow for crashed execution %s", execution_id)
            return "failed"
