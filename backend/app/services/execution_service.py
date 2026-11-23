"""Application service for execution writes.

The service owns the execution write path: creation/queueing, cancellation,
the approval/authentication resume transaction and retries. It deliberately
has no FastAPI dependency: workers and other callers can reuse the same
transitions, and route handlers translate :class:`ExecutionServiceError`
into their own error envelope. The durable state machine — compare-and-set
transitions, approval decisions, approval-request cleanup, child-checkpoint
cascade, queue compensation, live bus events and the audit records — lives
here rather than in the HTTP layer.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals import service as approvals_service
from app.audit import (
    EXECUTION_CANCEL,
    EXECUTION_RESUME,
    EXECUTION_RETRY,
    log_event,
)
from app.credentials.validator import validate_workflow_credentials
from app.engine.errors import WorkflowValidationError
from app.eventbus import bus
from app.metrics import execution_started
from app.models import (
    ApprovalRequest,
    Execution,
    ExecutionRetryHistory,
    WorkflowRecord,
)
from app.orchestration import cancellation
from app.queue import QueueBackend, get_queue

logger = logging.getLogger("services.execution")

CancelSignal = Callable[[str], bool]
BusPublisher = Callable[[str, dict[str, Any]], None]
AuditLogger = Callable[..., None]
ConsumerStarter = Callable[[], None]

#: Statuses from which a user-initiated cancel is meaningful. ``cancelling``
#: is included because a second cancel force-terminates the run immediately.
CANCELLABLE_STATUSES = frozenset(
    {"queued", "running", "cancelling", "waiting_approval", "waiting_auth"}
)

#: A node may only be retried once the parent run has stopped making progress.
_RETRY_BLOCKED_STATUSES = frozenset({"queued", "running", "cancelling"})


class ExecutionServiceError(Exception):
    """Typed service failure that the HTTP layer maps to a status + payload."""

    def __init__(self, code: str, message: str, *, http_status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class RetryOutcome:
    """Result of a retry request; an idempotent replay creates no new run."""

    execution_id: str
    attempt_number: int
    idempotent_replay: bool = False


class ExecutionService:
    """Execution write operations with injectable eventing for tests."""

    def __init__(
        self,
        db: Session,
        *,
        signal_cancel: CancelSignal | None = None,
        bus_publish: BusPublisher | None = None,
        audit: AuditLogger | None = None,
        queue: QueueBackend | None = None,
        ensure_consumer: ConsumerStarter | None = None,
    ) -> None:
        self._db = db
        self._signal_cancel = signal_cancel or cancellation.signal
        self._bus_publish = bus_publish or bus.publish
        self._audit = audit or log_event
        self._queue = queue
        self._ensure_consumer_callback = ensure_consumer

    def start_execution(
        self,
        *,
        workflow_id: str,
        user_id: int,
        version: int,
        workflow_data: dict,
        trigger: str,
        trigger_items: list[dict[str, Any]],
        workspace_id: str | None = None,
        extra_payload: dict[str, Any] | None = None,
        parent_execution_id: str | None = None,
        retry_count: int = 0,
        correlation_id: str | None = None,
        organization_id: str | None = None,
    ) -> str:
        """Create the execution row (queued) and enqueue the job (spec 25/13).

        Shared by manual runs, webhooks, retries and the scheduler; returns
        the new execution id. A worker claims the job, flips it to
        ``running`` and executes the exact workflow snapshot (spec 24.3).
        ``extra_payload`` carries debugger directives (e.g.
        ``_retry_from_node``, Phase 13).

        Validation (spec 12.7): credential references are verified BEFORE
        queueing — workflows with unimplemented or invalid providers never
        enter the queue.
        """
        from app.services.telemetry_service import extract_execution_flow_metadata

        db = self._db
        wf_name = None
        wf_rec = db.get(WorkflowRecord, workflow_id)
        if wf_rec:
            wf_name = wf_rec.name

        flow_meta = extract_execution_flow_metadata(
            workflow_data,
            trigger=trigger,
            workflow_name=wf_name,
        )

        # Validate credential references before queue — fail fast with clear error
        try:
            validate_workflow_credentials(workflow_data, db, user_id)
        except WorkflowValidationError as ve:
            # Create a failed execution record for audit, then raise for API to
            # return 422.
            execution_id = f"exec_{uuid.uuid4().hex[:12]}"
            db.add(Execution(
                id=execution_id,
                workflow_id=workflow_id,
                user_id=user_id,
                workflow_version=version,
                workflow_data=workflow_data,
                trigger=trigger,
                trigger_data=trigger_items,
                status="failed",
                error=ve.to_dict(),
                source_connector=flow_meta["source_connector"],
                destination_connector=flow_meta["destination_connector"],
                source_object=flow_meta["source_object"],
                destination_object=flow_meta["destination_object"],
                http_method=flow_meta["http_method"],
                api_endpoint=flow_meta["api_endpoint"],
                http_status_code=400,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                workspace_id=workspace_id,
                parent_execution_id=parent_execution_id,
                retry_count=retry_count,
                correlation_id=correlation_id,
                organization_id=organization_id,
            ))
            db.commit()
            raise ve
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        db.add(Execution(
            id=execution_id,
            workflow_id=workflow_id,
            user_id=user_id,
            workflow_version=version,
            workflow_data=workflow_data,
            trigger=trigger,
            trigger_data=trigger_items,
            status="queued",
            source_connector=flow_meta["source_connector"],
            destination_connector=flow_meta["destination_connector"],
            source_object=flow_meta["source_object"],
            destination_object=flow_meta["destination_object"],
            http_method=flow_meta["http_method"],
            api_endpoint=flow_meta["api_endpoint"],
            started_at=datetime.now(UTC),
            workspace_id=workspace_id,
            parent_execution_id=parent_execution_id,
            retry_count=retry_count,
            correlation_id=correlation_id,
            organization_id=organization_id,
        ))
        db.commit()
        payload = {
            "workflow_data": workflow_data,
            "trigger_items": trigger_items,
            "trigger": trigger,
            "user_id": user_id,
            "workflow_id": workflow_id,
            "version": version,
            "workspace_id": workspace_id,
            **(extra_payload or {}),
        }
        from app.telemetry.tracer import inject_trace_context

        inject_trace_context(payload)
        queue = self._queue or get_queue()
        if not queue.enqueue(job_id, execution_id, payload):
            # Duplicate delivery guard: another execution for this id already
            # queued (should not happen with fresh ids; keep the row accurate).
            rec = db.get(Execution, execution_id)
            if rec is not None:
                rec.status = "failed"
                rec.error = {
                    "code": "DUPLICATE_QUEUE",
                    "message": "Execution was already queued.",
                }
                db.commit()
        execution_started(execution_id, trigger)
        self._ensure_consumer()
        return execution_id

    def retry_execution(
        self,
        rec: Execution,
        *,
        user_id: int,
        workspace_id: str | None = None,
        node_id: str | None = None,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> RetryOutcome:
        """Re-run *rec* from its snapshot, with idempotency and retry history.

        The HTTP layer keeps the authorization check and response envelope;
        everything else (idempotent replay lookup, node-retry validation,
        the new execution via :meth:`start_execution`, the durable
        retry-history row and the audit record) is ordered exactly as the
        historical endpoint did.
        """
        db = self._db
        execution_id = rec.id

        # Idempotency check: prevent duplicate submissions
        if idempotency_key:
            recent_retry = db.scalar(
                select(ExecutionRetryHistory).where(
                    ExecutionRetryHistory.original_execution_id == execution_id,
                    ExecutionRetryHistory.retry_policy == idempotency_key,
                )
            )
            if recent_retry:
                return RetryOutcome(
                    execution_id=recent_retry.retry_execution_id,
                    attempt_number=recent_retry.attempt_number,
                    idempotent_replay=True,
                )

        extra_payload: dict[str, Any] | None = None
        if node_id:
            workflow_nodes = {
                n.get("id") for n in (rec.workflow_data or {}).get("nodes", [])
            }
            if node_id not in workflow_nodes:
                raise ExecutionServiceError(
                    "UNKNOWN_NODE",
                    f"Unknown node '{node_id}'.",
                    http_status=404,
                )
            statuses = rec.node_statuses or {}
            node_status = statuses.get(node_id)
            if (
                rec.status in _RETRY_BLOCKED_STATUSES
                or rec.status == "waiting_approval"
            ):
                raise ExecutionServiceError(
                    "EXECUTION_IN_PROGRESS",
                    "Cannot retry a node while the execution is still running.",
                )
            if node_status not in ("error", "failed"):
                raise ExecutionServiceError(
                    "NODE_NOT_RETRYABLE",
                    f"Node '{node_id}' did not fail (status: "
                    f"{node_status or 'unknown'}); only failed nodes can be "
                    "retried safely.",
                )
            extra_payload = {
                "_retry_from_node": node_id,
                "_retry_source": execution_id,
            }

        next_attempt = (rec.retry_count or 0) + 1
        new_id = self.start_execution(
            workflow_id=rec.workflow_id,
            user_id=user_id,
            version=rec.workflow_version,
            workflow_data=rec.workflow_data,
            trigger="node_retry" if node_id else "retry",
            trigger_items=rec.trigger_data or [{}],
            workspace_id=workspace_id,
            extra_payload=extra_payload,
            parent_execution_id=execution_id,
            retry_count=next_attempt,
            correlation_id=rec.correlation_id or execution_id,
            organization_id=rec.organization_id,
        )

        retry_row = ExecutionRetryHistory(
            id=f"retry_{uuid.uuid4().hex[:12]}",
            original_execution_id=execution_id,
            retry_execution_id=new_id,
            attempt_number=next_attempt,
            retry_reason=reason
            if reason
            else ("node_retry" if node_id else "manual_retry"),
            failed_step_id=node_id,
            retry_trigger="manual",
            initiated_by_user_id=user_id,
            retry_policy=idempotency_key,
            status="pending",
            created_at=datetime.now(UTC),
        )
        db.add(retry_row)
        db.commit()

        self._audit(
            db,
            EXECUTION_RETRY,
            target_type="execution",
            target_id=execution_id,
            user_id=user_id,
            detail={
                "new_execution_id": new_id,
                "attempt_number": next_attempt,
                **({"node_id": node_id} if node_id else {}),
            },
        )
        return RetryOutcome(execution_id=new_id, attempt_number=next_attempt)

    def cancel(self, rec: Execution, *, user_id: int) -> str:
        """Cancel *rec* and return the execution's resulting status.

        The four branches mirror the historical endpoint exactly:

        1. ``waiting_approval``/``waiting_auth`` — terminal immediately,
           close pending approvals and cascade child checkpoints.
        2. ``queued`` — terminal before a worker claims it.
        3. ``cancelling`` — second cancel force-terminates.
        4. ``running`` — durable ``cancelling`` flag for cooperative stop.

        Every transition is a compare-and-set on the observed status, so a
        concurrent worker/cancel that wins the race produces a typed 409
        instead of an unconditional overwrite.
        """
        if rec.status not in CANCELLABLE_STATUSES:
            raise ExecutionServiceError(
                "EXECUTION_NOT_RUNNING", "Execution is not running."
            )

        if rec.status in ("waiting_approval", "waiting_auth"):
            return self._cancel_waiting(rec, user_id=user_id)
        if rec.status == "queued":
            return self._cancel_queued(rec, user_id=user_id)
        if rec.status == "cancelling":
            return self._cancel_cancelling(rec, user_id=user_id)
        return self._cancel_running(rec, user_id=user_id)

    def resume(
        self,
        rec: Execution,
        *,
        user_id: int,
        approved: bool,
        workspace_id: str | None,
    ) -> str:
        """Requeue a paused execution and return ``"queued"``.

        The durable approval request, when present, is authoritative: a
        decision already taken through the approvals API overrides the
        resume payload, an expired request refuses the resume, and a
        pending request is decided (quorum included) before the execution
        is claimed. The compare-and-set then ensures only one caller can
        requeue the run; a lost queue race compensates the row back to the
        status it was resumed from.
        """
        if rec.status not in ("waiting_approval", "waiting_auth"):
            raise ExecutionServiceError(
                "EXECUTION_NOT_WAITING",
                "Execution is not waiting for approval or authentication.",
            )

        execution_id = rec.id
        pause = rec.pause_state or {}
        is_auth_pause = rec.status == "waiting_auth"

        if not is_auth_pause:
            allowed = pause.get("approvers") or []
            if allowed and user_id not in allowed:
                raise ExecutionServiceError(
                    "NOT_AN_APPROVER",
                    "You are not a listed approver for this step.",
                    http_status=403,
                )

        pause_node = pause.get("node_id") or ""
        latest_request = None
        if not is_auth_pause:
            approval_id = pause.get("approval_id")
            if approval_id:
                latest_request = self._db.get(ApprovalRequest, approval_id)
            if latest_request is None:
                latest_request = self._db.scalar(
                    select(ApprovalRequest)
                    .where(
                        ApprovalRequest.run_id == execution_id,
                        ApprovalRequest.node_id == pause_node,
                    )
                    .order_by(ApprovalRequest.created_at.desc())
                    .limit(1)
                )
            if latest_request is not None:
                if latest_request.status in ("approved", "rejected"):
                    # A decision taken through the approvals API is
                    # authoritative; do not let a conflicting resume payload
                    # override it.
                    authoritative = latest_request.status == "approved"
                    if authoritative != approved:
                        logger.warning(
                            "Resume decision for execution %s differs from durable "
                            "approval %s; using the durable decision.",
                            execution_id,
                            latest_request.id,
                        )
                    approved = authoritative
                elif latest_request.status == "expired":
                    raise ExecutionServiceError(
                        "APPROVAL_EXPIRED",
                        "The approval request has expired; the run cannot be resumed.",
                    )

        queue = self._queue or get_queue()
        if is_auth_pause:
            # Re-run from the paused node seeding prior upstream results.
            paused_node = pause.get("node_id")
            payload = {
                "workflow_data": rec.workflow_data,
                "trigger_items": rec.trigger_data or [{}],
                "trigger": rec.trigger,
                "user_id": rec.user_id,
                "workflow_id": rec.workflow_id,
                "version": rec.workflow_version,
                "workspace_id": workspace_id,
                "_retry_from_node": paused_node,
                "_retry_source": execution_id,
            }
        else:
            payload = {
                "workflow_data": rec.workflow_data,
                "trigger_items": rec.trigger_data or [{}],
                "trigger": rec.trigger,
                "user_id": rec.user_id,
                "workflow_id": rec.workflow_id,
                "version": rec.workflow_version,
                "workspace_id": workspace_id,
                "_approval_data": {
                    "approved": approved,
                    "approved_by": user_id,
                    "approved_at": datetime.now(UTC).isoformat(),
                    "node_id": pause.get("node_id"),
                    # Mid-loop agent tool approval: the worker needs the pause
                    # kind and the encrypted ReAct checkpoint to resume instead
                    # of restarting the node from the beginning.
                    "pause_type": pause.get("type"),
                    "tool_name": pause.get("tool_name"),
                    "approval_id": pause.get("approval_id"),
                    "state": pause.get("state"),
                },
            }

        # Record the decision before claiming the resume. A rejected quorum
        # or an expired request must leave the execution paused, not queued.
        if (
            not is_auth_pause
            and latest_request is not None
            and latest_request.status == "pending"
        ):
            try:
                decided = approvals_service.decide(
                    self._db,
                    latest_request.id,
                    user_id=user_id,
                    approved=approved,
                    nonce=uuid.uuid4().hex,
                )
            except approvals_service.ApprovalError as exc:
                raise ExecutionServiceError(
                    exc.code, str(exc), http_status=exc.http_status
                ) from exc
            if decided.status == "pending":
                decisions = (decided.decision or {}).get("decisions") or []
                approvals_count = len(
                    [item for item in decisions if item.get("approved")]
                )
                raise ExecutionServiceError(
                    "APPROVAL_QUORUM_NOT_MET",
                    (
                        f"Approval quorum not met ({approvals_count}/{decided.quorum}); "
                        "the run remains paused."
                    ),
                )
            approved = decided.status == "approved"

        # CAS: claim the resume atomically.
        target_status = rec.status
        flipped = (
            self._db.query(Execution)
            .filter(Execution.id == execution_id, Execution.status == target_status)
            .update({"status": "queued"})
        )
        if flipped == 0:
            self._db.rollback()
            raise ExecutionServiceError(
                "EXECUTION_NOT_WAITING", "Execution is no longer waiting."
            )
        self._db.commit()

        if not queue.requeue(execution_id, payload):
            job_id = f"job_{uuid.uuid4().hex[:12]}"
            if not queue.enqueue(job_id, execution_id, payload):
                self._db.query(Execution).filter(
                    Execution.id == execution_id, Execution.status == "queued"
                ).update({"status": target_status})
                self._db.commit()
                raise ExecutionServiceError(
                    "EXECUTION_ALREADY_QUEUED", "Execution is already queued."
                )
        self._record_resume_audit(
            execution_id,
            user_id=user_id,
            resumed_from=target_status,
            approved=approved,
        )
        return "queued"

    def _ensure_consumer(self) -> None:
        if self._ensure_consumer_callback is not None:
            self._ensure_consumer_callback()
            return
        from app.queue.worker import ensure_embedded_consumer

        ensure_embedded_consumer()

    def _cancel_waiting(self, rec: Execution, *, user_id: int) -> str:
        execution_id = rec.id
        values: dict[Any, Any] = {
            "status": "cancelled",
            "finished_at": datetime.now(UTC),
            "pause_state": None,
            "error": rec.error
            or {
                "code": "CANCELLED_WHILE_WAITING",
                "message": "Cancelled while waiting for action.",
            },
        }
        flipped = (
            self._db.query(Execution)
            .filter(
                Execution.id == execution_id,
                Execution.status.in_(("waiting_approval", "waiting_auth")),
            )
            .update(values)
        )
        if flipped == 0:
            self._db.rollback()
            raise ExecutionServiceError(
                "EXECUTION_NOT_WAITING", "Execution is no longer waiting."
            )
        self._db.commit()
        # A terminal run must not leave a decidable request in the inbox.
        try:
            pending_requests = list(
                self._db.scalars(
                    select(ApprovalRequest).where(
                        ApprovalRequest.run_id == execution_id,
                        ApprovalRequest.status == "pending",
                    )
                ).all()
            )
            for request in pending_requests:
                request.status = "cancelled"
                request.decision = {
                    **(request.decision or {}),
                    "reason": "execution_cancelled",
                }
            if pending_requests:
                self._db.commit()
        except Exception:
            logger.warning(
                "Could not cancel pending approvals for execution %s",
                execution_id,
                exc_info=True,
            )
            self._db.rollback()
        # Child executions are checkpoints owned by this parent; terminate the
        # full descendant chain so none can be resumed out of band.
        try:
            active_statuses = (
                "queued",
                "running",
                "cancelling",
                "waiting_approval",
                "waiting_auth",
            )
            child_rows = self._db.execute(
                select(Execution.id, Execution.parent_execution_id).where(
                    Execution.trigger == "sub_workflow",
                    Execution.status.in_(active_statuses),
                )
            ).all()
            children_by_parent: dict[str, list[str]] = {}
            for child_id, parent_id in child_rows:
                if parent_id:
                    children_by_parent.setdefault(parent_id, []).append(child_id)
            descendants: list[str] = []
            seen: set[str] = set()
            queue = list(children_by_parent.get(execution_id, []))
            while queue:
                child_id = queue.pop()
                if child_id in seen:
                    continue
                seen.add(child_id)
                descendants.append(child_id)
                queue.extend(children_by_parent.get(child_id, []))
            if descendants:
                self._db.query(Execution).filter(
                    Execution.id.in_(descendants)
                ).update(
                    {
                        "status": "cancelled",
                        "finished_at": datetime.now(UTC),
                        "pause_state": None,
                        "error": {
                            "code": "PARENT_CANCELLED",
                            "message": "Parent execution was cancelled.",
                        },
                    },
                    synchronize_session=False,
                )
                self._db.commit()
        except Exception:
            logger.warning(
                "Could not cancel child executions for parent %s",
                execution_id,
                exc_info=True,
            )
            self._db.rollback()
        self._publish_cancelled(rec, execution_id)
        self._record_audit(execution_id, user_id=user_id)
        return "cancelled"

    def _cancel_queued(self, rec: Execution, *, user_id: int) -> str:
        execution_id = rec.id
        values: dict[Any, Any] = {
            "status": "cancelled",
            "finished_at": datetime.now(UTC),
            "error": rec.error
            or {
                "code": "CANCELLED_IN_QUEUE",
                "message": "Execution cancelled before starting.",
            },
        }
        flipped = (
            self._db.query(Execution)
            .filter(Execution.id == execution_id, Execution.status == "queued")
            .update(values)
        )
        if flipped == 0:
            self._db.rollback()
            raise ExecutionServiceError(
                "EXECUTION_NOT_QUEUED", "Execution is no longer queued."
            )
        self._db.commit()
        self._publish_cancelled(rec, execution_id)
        self._record_audit(execution_id, user_id=user_id)
        return "cancelled"

    def _cancel_cancelling(self, rec: Execution, *, user_id: int) -> str:
        execution_id = rec.id
        values: dict[Any, Any] = {
            "status": "cancelled",
            "finished_at": datetime.now(UTC),
            "error": rec.error
            or {
                "code": "FORCE_CANCELLED",
                "message": "Execution force-cancelled by user.",
            },
        }
        flipped = (
            self._db.query(Execution)
            .filter(Execution.id == execution_id, Execution.status == "cancelling")
            .update(values)
        )
        if flipped == 0:
            self._db.rollback()
            raise ExecutionServiceError(
                "EXECUTION_NOT_CANCELLING", "Execution is not cancelling."
            )
        self._db.commit()
        self._signal_cancel(execution_id)
        self._publish_cancelled(rec, execution_id)
        self._record_audit(execution_id, user_id=user_id)
        return "cancelled"

    def _cancel_running(self, rec: Execution, *, user_id: int) -> str:
        execution_id = rec.id
        flipped = (
            self._db.query(Execution)
            .filter(Execution.id == execution_id, Execution.status == "running")
            .update({"status": "cancelling"})
        )
        if flipped == 0:
            self._db.rollback()
            raise ExecutionServiceError(
                "EXECUTION_NOT_RUNNING", "Execution is not running."
            )
        self._db.commit()
        # Instantly notify in-process runner if active locally.
        self._signal_cancel(execution_id)
        self._bus_publish(
            execution_id,
            {
                "event": "execution.cancelling",
                "execution_id": execution_id,
                "workflow_id": rec.workflow_id,
                "status": "cancelling",
            },
        )
        self._record_audit(execution_id, user_id=user_id)
        return "cancelling"

    def _publish_cancelled(self, rec: Execution, execution_id: str) -> None:
        self._bus_publish(
            execution_id,
            {
                "event": "execution.cancelled",
                "execution_id": execution_id,
                "workflow_id": rec.workflow_id,
                "status": "cancelled",
            },
        )

    def _record_audit(self, execution_id: str, *, user_id: int) -> None:
        self._audit(
            self._db,
            EXECUTION_CANCEL,
            target_type="execution",
            target_id=execution_id,
            user_id=user_id,
        )

    def _record_resume_audit(
        self,
        execution_id: str,
        *,
        user_id: int,
        resumed_from: str,
        approved: bool,
    ) -> None:
        self._audit(
            self._db,
            EXECUTION_RESUME,
            target_type="execution",
            target_id=execution_id,
            user_id=user_id,
            detail={"resumed_from": resumed_from, "approved": approved},
        )
