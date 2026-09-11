"""First-class workflow testing API (Phase 14).

A WorkflowTest is a saved, repeatable test case for one workflow:
test data (trigger items), HTTP mock rules, assertions and an
expected-outputs regression snapshot. Running a test enqueues an
ordinary execution with ``trigger="test"`` and a ``_test_run`` payload;
the runtime installs the mocks (unmatched outbound calls are BLOCKED —
a test can never mutate production data) and evaluates the spec into a
PASS/FAIL/DIFF report persisted under ``results["tests"]``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.access import get_workflow
from app.api.auth import get_current_user
from app.api.common import ok
from app.audit import WORKFLOW_TEST_CREATE, WORKFLOW_TEST_RUN, log_event
from app.db import get_db
from app.models import User
from app.models.workflow_test import WorkflowTest

router = APIRouter(prefix="/api/workflows/{workflow_id}/tests", tags=["workflow-tests"])

VALID_SPEC_KEYS = ("test_data", "mocks", "assertions", "expected_outputs")


class WorkflowTestCreate(BaseModel):
    name: str = "Untitled test"
    test_data: Any = None
    mocks: list[dict[str, Any]] | None = None
    assertions: list[dict[str, Any]] | None = None
    expected_outputs: dict[str, Any] | None = None


class WorkflowTestUpdate(BaseModel):
    name: str | None = None
    test_data: Any = None
    mocks: list[dict[str, Any]] | None = None
    assertions: list[dict[str, Any]] | None = None
    expected_outputs: dict[str, Any] | None = None


def _to_dict(t: WorkflowTest) -> dict[str, Any]:
    return {
        "id": t.id,
        "workflow_id": t.workflow_id,
        "name": t.name,
        "test_data": t.test_data,
        "mocks": t.mocks or [],
        "assertions": t.assertions or [],
        "expected_outputs": t.expected_outputs,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _validate_assertions(assertions: list[dict[str, Any]] | None) -> None:
    """Light edge validation: unknown assertion types are allowed through
    (they surface as FAIL in the report) but non-object entries are not."""
    from app.testing.service import ASSERTION_TYPES

    for a in assertions or []:
        if not isinstance(a, dict):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Each assertion must be an object with a 'type'.",
            )
        kind = str(a.get("type") or "")
        if kind and kind not in ASSERTION_TYPES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Unknown assertion type '{kind}'. Known: {', '.join(ASSERTION_TYPES)}.",
            )


@router.get("")
def list_tests(
    workflow_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_workflow(db, workflow_id, user)
    rows = db.scalars(
        select(WorkflowTest)
        .where(WorkflowTest.workflow_id == workflow_id)
        .order_by(WorkflowTest.created_at.asc(), WorkflowTest.id.asc())
    ).all()
    return ok([_to_dict(t) for t in rows])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_test(
    workflow_id: str,
    body: WorkflowTestCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_workflow(db, workflow_id, user, require_edit=True)
    _validate_assertions(body.assertions)
    rec = WorkflowTest(
        id=f"wft_{uuid.uuid4().hex[:12]}",
        workflow_id=workflow_id,
        user_id=user.id,
        name=(body.name or "").strip() or "Untitled test",
        test_data=body.test_data,
        mocks=body.mocks,
        assertions=body.assertions,
        expected_outputs=body.expected_outputs,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    log_event(db, WORKFLOW_TEST_CREATE, target_type="workflow_test", target_id=rec.id, user_id=user.id,
              detail={"workflow_id": workflow_id})
    return ok(_to_dict(rec))


def _get_test(db: Session, workflow_id: str, test_id: str) -> WorkflowTest:
    rec = db.get(WorkflowTest, test_id)
    if rec is None or rec.workflow_id != workflow_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test not found.")
    return rec


@router.get("/{test_id}")
def get_test(
    workflow_id: str,
    test_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_workflow(db, workflow_id, user)
    return ok(_to_dict(_get_test(db, workflow_id, test_id)))


@router.patch("/{test_id}")
def update_test(
    workflow_id: str,
    test_id: str,
    body: WorkflowTestUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_workflow(db, workflow_id, user, require_edit=True)
    rec = _get_test(db, workflow_id, test_id)
    _validate_assertions(body.assertions)
    if body.name is not None:
        rec.name = body.name.strip() or rec.name
    rec.test_data = body.test_data
    rec.mocks = body.mocks
    rec.assertions = body.assertions
    rec.expected_outputs = body.expected_outputs
    db.commit()
    db.refresh(rec)
    return ok(_to_dict(rec))


@router.delete("/{test_id}")
def delete_test(
    workflow_id: str,
    test_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_workflow(db, workflow_id, user, require_edit=True)
    rec = _get_test(db, workflow_id, test_id)
    db.delete(rec)
    db.commit()
    return ok({"id": test_id, "deleted": True})


@router.post("/{test_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_test(
    workflow_id: str,
    test_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Execute the workflow against this test's spec.

    Mock mode is enforced by the runtime: matched outbound calls answer
    locally, unmatched ones are blocked — production systems are never
    contacted during a test run.
    """
    from app.api.executions import start_execution

    wf_rec = get_workflow(db, workflow_id, user, require_edit=True)
    rec = _get_test(db, workflow_id, test_id)
    # Plan quota (Phase 34): test runs consume executions like any run.
    from app.billing.service import enforce_plan_limit

    enforce_plan_limit(db, wf_rec.workspace_id, "executions")

    from app.testing.service import normalize_test_data

    execution_id = start_execution(
        db,
        workflow_id=workflow_id,
        user_id=user.id,
        version=wf_rec.version,
        workflow_data=wf_rec.data,
        trigger="test",
        trigger_items=normalize_test_data(rec.test_data),
        workspace_id=wf_rec.workspace_id,
        extra_payload={
            "_test_run": {
                "test_id": rec.id,
                "name": rec.name,
                "mocks": rec.mocks or [],
                "assertions": rec.assertions or [],
                "expected_outputs": rec.expected_outputs,
            },
        },
    )
    log_event(db, WORKFLOW_TEST_RUN, target_type="workflow_test", target_id=rec.id,
              user_id=user.id, detail={"execution_id": execution_id})
    return ok({
        "execution_id": execution_id,
        "test_id": rec.id,
        "status_url": f"/api/executions/{execution_id}",
        "queued_at": datetime.now(UTC).isoformat(),
    })
