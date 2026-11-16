"""Durable approval request service and API tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.approvals import service as approvals
from app.db import get_session
from app.models import Execution, OutboxEvent, User, WorkflowRecord

from tests.test_api.conftest import auth_headers, make_workflow, register


def _user(db, email: str) -> User:
    user = User(email=email, password_hash="x", role="member", active=True)
    db.add(user)
    db.flush()
    return user


def _run(db, user: User, suffix: str) -> tuple[str, str]:
    wf_id = f"wf_appr_{suffix}"
    ex_id = f"exec_appr_{suffix}"
    db.add(WorkflowRecord(id=wf_id, user_id=user.id, name="Approval", data={}, version=1))
    db.add(
        Execution(
            id=ex_id,
            workflow_id=wf_id,
            user_id=user.id,
            workflow_version=1,
            workflow_data={"id": wf_id, "nodes": [], "connections": []},
            trigger="manual",
            status="waiting_approval",
        )
    )
    db.commit()
    return wf_id, ex_id


def test_create_list_and_approve():
    with get_session() as db:
        user = _user(db, "approval_owner@example.com")
        wf_id, run_id = _run(db, user, "one")
        request = approvals.create_request(
            db,
            run_id=run_id,
            node_id="agent_1",
            tool_name="http_request",
            risk_tier=2,
            reason="External side effect",
            arguments={"url": "https://example.com", "token": "secret-value"},
            requested_by=user.id,
            approvers=[user.id],
            quorum=1,
            separation_of_duties=False,
            workflow_id=wf_id,
        )
        assert request.status == "pending"
        assert request.arguments["token"] == "***REDACTED***" or request.arguments["token"] != "secret-value"
        assert [row.id for row in approvals.list_requests(db)] == [request.id]
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1

        decided = approvals.decide(
            db, request.id, user_id=user.id, approved=True, nonce="nonce-12345678"
        )
        assert decided.status == "approved"
        assert decided.decided_by == user.id
        assert decided.decision["decisions"][0]["approved"] is True
        events = list(db.scalars(select(OutboxEvent).order_by(OutboxEvent.created_at)).all())
        assert [event.event_type for event in events] == [
            "approval.requested",
            "approval.decided",
        ]
        assert events[1].payload["status"] == "approved"

        # A retried decision with the same nonce is idempotent.
        replay = approvals.decide(
            db, request.id, user_id=user.id, approved=True, nonce="nonce-12345678"
        )
        assert replay.status == "approved"


def test_separation_of_duties_and_expiry():
    with get_session() as db:
        user = _user(db, "approval_sod@example.com")
        _, run_id = _run(db, user, "two")
        request = approvals.create_request(
            db,
            run_id=run_id,
            node_id="agent_1",
            reason="Sensitive write",
            requested_by=user.id,
            approvers=[user.id],
            separation_of_duties=True,
        )
        with pytest.raises(approvals.ApprovalForbidden):
            approvals.decide(
                db, request.id, user_id=user.id, approved=True, nonce="nonce-sod-123"
            )

        request.separation_of_duties = False
        request.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(approvals.ApprovalConflict) as exc_info:
            approvals.decide(
                db, request.id, user_id=user.id, approved=True, nonce="nonce-exp-123"
            )
        assert exc_info.value.code == "APPROVAL_EXPIRED"


def test_quorum_requires_two_approvers():
    with get_session() as db:
        first = _user(db, "approval_first@example.com")
        second = _user(db, "approval_second@example.com")
        _, run_id = _run(db, first, "three")
        request = approvals.create_request(
            db,
            run_id=run_id,
            node_id="agent_1",
            reason="High-value action",
            approvers=[first.id, second.id],
            quorum=2,
            separation_of_duties=False,
        )
        once = approvals.decide(
            db, request.id, user_id=first.id, approved=True, nonce="nonce-first-123"
        )
        assert once.status == "pending"
        twice = approvals.decide(
            db, request.id, user_id=second.id, approved=True, nonce="nonce-second-123"
        )
        assert twice.status == "approved"
        assert len(twice.decision["decisions"]) == 2


def test_expire_stale_marks_pending_requests():
    with get_session() as db:
        user = _user(db, "approval_expire@example.com")
        _, run_id = _run(db, user, "expire")
        request = approvals.create_request(
            db,
            run_id=run_id,
            node_id="agent_1",
            reason="Expiry test",
            requested_by=user.id,
        )
        request.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        assert approvals.expire_stale(db) == 1
        db.refresh(request)
        assert request.status == "expired"


def test_approval_api_inbox_and_decision(client):
    registered = register(client, email="approval_api@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]

    workflow = make_workflow("wf_api_approval")
    created = client.post("/api/workflows", json=workflow, headers=headers)
    assert created.status_code == 201, created.text
    wf_id = created.json()["data"]["id"]

    with get_session() as db:
        db.add(
            Execution(
                id="exec_api_approval",
                workflow_id=wf_id,
                user_id=user_id,
                workflow_version=1,
                workflow_data=workflow,
                trigger="manual",
                status="waiting_approval",
            )
        )
        db.commit()
        request = approvals.create_request(
            db,
            run_id="exec_api_approval",
            node_id="agent_1",
            tool_name="http_request",
            risk_tier=2,
            reason="External side effect",
            requested_by=user_id,
            approvers=[user_id],
            separation_of_duties=False,
            workflow_id=wf_id,
        )
        request_id = request.id

    inbox = client.get("/api/approvals", headers=headers)
    assert inbox.status_code == 200, inbox.text
    assert any(item["id"] == request_id for item in inbox.json()["data"])

    detail = client.get(f"/api/approvals/{request_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "pending"

    decided = client.post(
        f"/api/approvals/{request_id}/decide",
        json={"approved": True, "nonce": "nonce-api-12345", "comment": "looks good"},
        headers=headers,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["data"]["status"] == "approved"


def test_approval_api_requires_auth(client):
    assert client.get("/api/approvals").status_code == 401

def test_view_only_share_cannot_decide_approval(client):
    owner = register(client, email="approval_owner@example.com")
    viewer = register(client, email="approval_viewer@example.com")
    owner_headers = auth_headers(owner["token"])
    viewer_headers = auth_headers(viewer["token"])

    workflow = make_workflow("wf_viewer_approval")
    created = client.post("/api/workflows", json=workflow, headers=owner_headers)
    assert created.status_code == 201, created.text
    wf_id = created.json()["data"]["id"]
    shared = client.post(
        f"/api/workflows/{wf_id}/shares",
        json={"email": viewer["user"]["email"], "permission": "view"},
        headers=owner_headers,
    )
    assert shared.status_code in (200, 201), shared.text

    with get_session() as db:
        db.add(
            Execution(
                id="exec_viewer_approval",
                workflow_id=wf_id,
                user_id=owner["user"]["id"],
                workflow_version=1,
                workflow_data=workflow,
                trigger="manual",
                status="waiting_approval",
            )
        )
        db.commit()
        request = approvals.create_request(
            db,
            run_id="exec_viewer_approval",
            node_id="agent_1",
            tool_name="http_request",
            risk_tier=2,
            reason="External side effect",
            requested_by=owner["user"]["id"],
            approvers=[],
            separation_of_duties=False,
            workflow_id=wf_id,
        )
        request_id = request.id

    assert client.get(
        f"/api/approvals/{request_id}", headers=viewer_headers
    ).status_code == 200
    denied = client.post(
        f"/api/approvals/{request_id}/decide",
        json={"approved": True, "nonce": "viewer-nonce-123"},
        headers=viewer_headers,
    )
    assert denied.status_code == 403, denied.text


def _seed_execution(
    db,
    *,
    execution_id: str,
    workflow_id: str,
    user_id: int,
    workflow_data: dict,
) -> Execution:
    execution = Execution(
        id=execution_id,
        workflow_id=workflow_id,
        user_id=user_id,
        workflow_version=1,
        workflow_data=workflow_data,
        trigger="manual",
        status="waiting_approval",
    )
    db.add(execution)
    db.flush()
    return execution


def test_approval_api_hides_missing_and_unauthorized_requests(client):
    owner = register(client, email="approval_hidden_owner@example.com")
    outsider = register(client, email="approval_hidden_outsider@example.com")
    owner_headers = auth_headers(owner["token"])
    outsider_headers = auth_headers(outsider["token"])

    # The outsider has their own workflow, so a workflow-scoped inbox is
    # non-empty; the target request must still be hidden.
    outsider_wf = make_workflow("wf_hidden_outsider")
    assert (
        client.post(
            "/api/workflows", json=outsider_wf, headers=outsider_headers
        ).status_code
        == 201
    )
    owner_wf = make_workflow("wf_hidden_owner")
    assert (
        client.post("/api/workflows", json=owner_wf, headers=owner_headers).status_code
        == 201
    )

    with get_session() as db:
        _seed_execution(
            db,
            execution_id="exec_hidden_approval",
            workflow_id="wf_hidden_owner",
            user_id=owner["user"]["id"],
            workflow_data=owner_wf,
        )
        request = approvals.create_request(
            db,
            run_id="exec_hidden_approval",
            node_id="gate",
            reason="Hidden from outsiders",
            requested_by=owner["user"]["id"],
            approvers=[],
            separation_of_duties=False,
            workflow_id="wf_hidden_owner",
        )
        request_id = request.id

    assert (
        client.get(f"/api/approvals/{request_id}", headers=outsider_headers).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/approvals/{request_id}/decide",
            json={"approved": True, "nonce": "outsider-nonce-1"},
            headers=outsider_headers,
        ).status_code
        == 404
    )
    assert (
        client.get("/api/approvals/does-not-exist", headers=owner_headers).status_code
        == 404
    )


def test_list_approvals_merges_base_and_approver_fallback(client):
    owner = register(client, email="approval_base_owner@example.com")
    approver = register(client, email="approval_base_approver@example.com")
    outsider = register(client, email="approval_base_outsider@example.com")
    owner_headers = auth_headers(owner["token"])
    approver_headers = auth_headers(approver["token"])
    outsider_headers = auth_headers(outsider["token"])

    # The approver and outsider can see their own workflows but were never
    # granted access to the owner's workflow.
    approver_wf = make_workflow("wf_base_approver")
    assert (
        client.post(
            "/api/workflows", json=approver_wf, headers=approver_headers
        ).status_code
        == 201
    )
    outsider_wf = make_workflow("wf_base_outsider")
    assert (
        client.post(
            "/api/workflows", json=outsider_wf, headers=outsider_headers
        ).status_code
        == 201
    )
    owner_wf = make_workflow("wf_base_owner")
    assert (
        client.post("/api/workflows", json=owner_wf, headers=owner_headers).status_code
        == 201
    )

    now = datetime.now(UTC)
    with get_session() as db:
        _seed_execution(
            db,
            execution_id="exec_base_approver",
            workflow_id="wf_base_approver",
            user_id=approver["user"]["id"],
            workflow_data=approver_wf,
        )
        _seed_execution(
            db,
            execution_id="exec_base_owner",
            workflow_id="wf_base_owner",
            user_id=owner["user"]["id"],
            workflow_data=owner_wf,
        )
        base = approvals.create_request(
            db,
            run_id="exec_base_approver",
            node_id="gate",
            reason="Base inbox row",
            requested_by=approver["user"]["id"],
            approvers=[],
            separation_of_duties=False,
            workflow_id="wf_base_approver",
        )
        unrelated = approvals.create_request(
            db,
            run_id="exec_base_owner",
            node_id="other_gate",
            reason="Not assigned to the approver",
            requested_by=owner["user"]["id"],
            approvers=[outsider["user"]["id"]],
            separation_of_duties=False,
            workflow_id="wf_base_owner",
        )
        fallback = approvals.create_request(
            db,
            run_id="exec_base_owner",
            node_id="gate",
            reason="Fallback approver row",
            requested_by=owner["user"]["id"],
            approvers=[approver["user"]["id"]],
            separation_of_duties=False,
            workflow_id="wf_base_owner",
        )
        base.created_at = now - timedelta(minutes=3)
        unrelated.created_at = now - timedelta(minutes=2)
        fallback.created_at = now - timedelta(minutes=1)
        db.commit()

    inbox = client.get("/api/approvals", headers=approver_headers)
    assert inbox.status_code == 200, inbox.text
    inbox_ids = [row["id"] for row in inbox.json()["data"]]
    assert inbox_ids == [fallback.id, base.id]
    assert unrelated.id not in inbox_ids

    limited = client.get("/api/approvals?limit=1", headers=approver_headers)
    assert limited.status_code == 200, limited.text
    assert [row["id"] for row in limited.json()["data"]] == [fallback.id]

    # The fallback row is visible in detail even without workflow access.
    detail = client.get(f"/api/approvals/{fallback.id}", headers=approver_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["id"] == fallback.id
    assert (
        client.get(
            f"/api/approvals/{fallback.id}", headers=outsider_headers
        ).status_code
        == 404
    )

    # An explicitly listed approver may decide without workflow access.
    decided = client.post(
        f"/api/approvals/{fallback.id}/decide",
        json={"approved": True, "nonce": "fallback-nonce-1"},
        headers=approver_headers,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["data"]["status"] == "approved"

    approved = client.get(
        "/api/approvals?status=approved", headers=approver_headers
    )
    assert approved.status_code == 200, approved.text
    assert [row["id"] for row in approved.json()["data"]] == [fallback.id]
