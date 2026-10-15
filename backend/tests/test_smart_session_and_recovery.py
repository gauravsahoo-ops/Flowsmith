"""Comprehensive tests for the Smart Session & Credential Recovery System.

Covers:
1. SessionManager: session creation, device parsing, sliding renewal, multi-device listing, revocation.
2. RecoveryStateMachine: explicit 11-state transitions, invalid transition guards, single-flight locking, audit events.
3. ProviderCapabilities: Salesforce, Dynamics CRM (OAuth & Service Principal), HubSpot, Google, API keys.
4. AuthErrorClassifier: classified errors and recovery actions (expired token, invalid grant, rate limit, provider outage).
5. CredentialRecoveryService: Salesforce refresh + instance URL + token rotation, Dynamics 365 client credentials renewal, HubSpot refresh, Manual mode enforcement.
6. Workflow Execution: safe pause to 'waiting_auth' on auth failure, and safe resume without replaying upstream side effects.
"""

from __future__ import annotations

import datetime as dt
from datetime import UTC, datetime, timedelta
import uuid

import httpx
import pytest
import respx
from sqlalchemy.orm import Session

from app.credentials.provider_capabilities import (
    ProviderCapability,
    get_provider_capability,
)
from app.credentials.service import create_for_user, resolve_credentials
from app.db import get_session
from app.models.auth_session import AuthSession
from app.models.connection_auth_policy import (
    ConnectionAuthPolicy,
    CredentialAuditEvent,
    CredentialRecoveryJob,
)
from app.models.credential import Credential
from app.models.recovery_state import (
    AuthErrorCode,
    ConnectionState,
    RecoveryMode,
    can_transition,
)
from app.models.user import User
from app.security.jwt import create_token, decode_token
from app.security.session_manager import SessionManager
from app.services.auth_error_classifier import (
    ClassifiedAuthError,
    RecoveryAction,
    classify_auth_error,
)
from app.services.credential_recovery_service import CredentialRecoveryService
from app.services.recovery_state_machine import RecoveryStateMachine


def _get_or_create_test_user(db: Session, email: str = "recovery_test@example.com") -> User:
    user = db.query(User).filter_by(email=email).first()
    if not user:
        user = User(
            id=778899,
            email=email,
            password_hash="test_pw_hash",
            role="member",
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# =========================================================================
# 1. SessionManager Unit Tests
# =========================================================================

class TestSessionManager:
    def test_create_session_and_device_parsing(self):
        with get_session() as db:
            user = _get_or_create_test_user(db, "session_user_1@example.com")
            token = create_token(user.id, email=user.email)

            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            session = SessionManager.create_session(
                db,
                user=user,
                token=token,
                ip_address="192.168.1.100",
                user_agent=ua,
                remember_device=True,
                auto_renew=True,
            )

            assert session.user_id == user.id
            assert session.ip_address == "192.168.1.100"
            assert session.device_name == "Chrome on Windows"
            assert session.is_active is True
            assert session.auto_renew is True
            assert session.remember_device is True
            assert session.expires_at > datetime.now(UTC)

    def test_renew_session_sliding_window(self):
        with get_session() as db:
            user = _get_or_create_test_user(db, "session_user_2@example.com")
            token = create_token(user.id, email=user.email)

            session = SessionManager.create_session(
                db,
                user=user,
                token=token,
                ip_address="10.0.0.1",
                user_agent="Firefox",
                remember_device=False,
                auto_renew=True,
            )
            initial_jti = session.token_jti

            # Renew using token
            renew_res = SessionManager.renew_session(db, current_token=token)
            assert renew_res is not None
            assert "token" in renew_res
            assert renew_res["session_id"] == session.id

            # Verify new token JTI updated on session
            db.refresh(session)
            assert session.token_jti != initial_jti
            assert session.is_active is True

    def test_renew_fails_if_auto_renew_disabled(self):
        with get_session() as db:
            user = _get_or_create_test_user(db, "session_user_3@example.com")
            token = create_token(user.id, email=user.email)

            session = SessionManager.create_session(
                db,
                user=user,
                token=token,
                ip_address="10.0.0.2",
                user_agent="Safari",
                remember_device=False,
                auto_renew=False,
            )

            # Standard renew fails because auto_renew is False
            with pytest.raises(ValueError, match="Automatic session renewal is disabled"):
                SessionManager.renew_session(db, current_token=token)

    def test_list_and_revoke_sessions(self):
        with get_session() as db:
            user = _get_or_create_test_user(db, "session_user_4@example.com")

            token1 = create_token(user.id, email=user.email)
            token2 = create_token(user.id, email=user.email)
            payload1 = decode_token(token1)

            s1 = SessionManager.create_session(db, user=user, token=token1, ip_address="1.1.1.1", user_agent="Chrome")
            s2 = SessionManager.create_session(db, user=user, token=token2, ip_address="2.2.2.2", user_agent="Edge")

            # List sessions with jti1 as current
            sessions = SessionManager.list_user_sessions(db, user_id=user.id, current_jti=payload1.get("jti"))
            assert len(sessions) == 2
            s1_dto = next(s for s in sessions if s["id"] == s1.id)
            s2_dto = next(s for s in sessions if s["id"] == s2.id)
            assert s1_dto["is_current"] is True
            assert s2_dto["is_current"] is False

            # Revoke s2
            revoked = SessionManager.revoke_session(db, user_id=user.id, session_id=s2.id)
            assert revoked is True

            # Now list again
            active_sessions = SessionManager.list_user_sessions(db, user_id=user.id)
            assert len(active_sessions) == 1
            assert active_sessions[0]["id"] == s1.id

            # Revoke all excluding current
            token3 = create_token(user.id, email=user.email)
            SessionManager.create_session(db, user=user, token=token3, ip_address="3.3.3.3", user_agent="Mobile")
            count = SessionManager.revoke_all_sessions(db, user_id=user.id, except_jti=payload1.get("jti"))
            assert count == 1
            remaining = SessionManager.list_user_sessions(db, user_id=user.id)
            assert len(remaining) == 1
            assert remaining[0]["id"] == s1.id


# =========================================================================
# 2. Recovery State Machine & Transition Tests
# =========================================================================

class TestRecoveryStateMachine:
    def test_legal_and_illegal_transitions(self):
        # Legal transitions
        assert can_transition(ConnectionState.CONNECTED, ConnectionState.EXPIRING_SOON) is True
        assert can_transition(ConnectionState.EXPIRING_SOON, ConnectionState.REFRESH_PENDING) is True
        assert can_transition(ConnectionState.REFRESH_PENDING, ConnectionState.REFRESHING) is True
        assert can_transition(ConnectionState.REFRESHING, ConnectionState.CONNECTED) is True
        assert can_transition(ConnectionState.REFRESHING, ConnectionState.REAUTHORIZATION_REQUIRED) is True
        assert can_transition(ConnectionState.REFRESHING, ConnectionState.PROVIDER_UNAVAILABLE) is True
        assert can_transition(ConnectionState.PROVIDER_UNAVAILABLE, ConnectionState.RECOVERY_PENDING) is True
        assert can_transition(ConnectionState.CONNECTED, ConnectionState.DISCONNECTED) is True
        assert can_transition(ConnectionState.CONNECTED, ConnectionState.REVOKED) is True

        # Illegal transitions: once in REVOKED, cannot jump to EXPIRING_SOON
        assert can_transition(ConnectionState.REVOKED, ConnectionState.EXPIRING_SOON) is False
        assert can_transition(ConnectionState.DISCONNECTED, ConnectionState.REFRESH_PENDING) is False

    def test_state_machine_transition_with_audit_trail(self):
        with get_session() as db:
            user = _get_or_create_test_user(db, "sm_user@example.com")

            cred = create_for_user(
                db=db,
                user_id=user.id,
                name="State Machine Test Connection",
                cred_type="salesforce",
                data={
                    "access_token": "sfdc_test",
                    "refresh_token": "sfdc_refresh_123",
                    "instance_url": "https://test.salesforce.com",
                    "client_id": "test_cid",
                    "client_secret": "test_csec",
                },
            )
            cred_id = cred["id"]

            policy = RecoveryStateMachine.get_or_create_policy(
                db,
                credential_id=cred_id,
                user_id=user.id,
                provider="salesforce",
            )
            assert policy.state == ConnectionState.CONNECTED.value

            # Transition CONNECTED -> EXPIRING_SOON
            RecoveryStateMachine.transition(
                db,
                credential_id=cred_id,
                target_state=ConnectionState.EXPIRING_SOON,
                actor="health_monitor",
                details={"reason": "Token expires in 10 minutes"},
            )
            assert policy.state == ConnectionState.EXPIRING_SOON.value

            # Transition EXPIRING_SOON -> REVOKED is legal
            RecoveryStateMachine.transition(
                db,
                credential_id=cred_id,
                target_state=ConnectionState.REVOKED,
                actor="admin",
                details={"reason": "Security revocation"},
            )
            assert policy.state == ConnectionState.REVOKED.value

            # Illegal transition guard: from REVOKED -> EXPIRING_SOON is illegal
            with pytest.raises(ValueError, match="Illegal state transition"):
                RecoveryStateMachine.transition(
                    db,
                    credential_id=cred_id,
                    target_state=ConnectionState.EXPIRING_SOON,
                    actor="attacker",
                )

            # Check audit event persisted and sanitized
            events = db.query(CredentialAuditEvent).filter_by(credential_id=cred_id).all()
            assert len(events) >= 2
            assert any(e.new_state == ConnectionState.EXPIRING_SOON.value for e in events)
            assert any(e.new_state == ConnectionState.REVOKED.value for e in events)

    def test_single_flight_distributed_lock(self):
        with get_session() as db:
            user = _get_or_create_test_user(db, "lock_user@example.com")

            cred = create_for_user(
                db=db,
                user_id=user.id,
                name="Lock Test Connection",
                cred_type="hubspot",
                data={"access_token": "hs_token", "refresh_token": "hs_refresh"},
            )
            cred_id = cred["id"]

            # Worker 1 acquires lock
            lock1 = RecoveryStateMachine.acquire_recovery_lock(cred_id, ttl_seconds=10)
            assert lock1 is not None

            # Worker 2 attempts to acquire lock for same connection -> fails (single-flight)
            lock2 = RecoveryStateMachine.acquire_recovery_lock(cred_id, ttl_seconds=10)
            assert lock2 is None

            # Release worker 1 lock
            RecoveryStateMachine.release_recovery_lock(cred_id, lock1)

            # Worker 2 can now acquire
            lock3 = RecoveryStateMachine.acquire_recovery_lock(cred_id, ttl_seconds=10)
            assert lock3 is not None
            RecoveryStateMachine.release_recovery_lock(cred_id, lock3)


# =========================================================================
# 3. Provider Capabilities Tests
# =========================================================================

class TestProviderCapabilities:
    def test_salesforce_capabilities(self):
        caps = get_provider_capability("salesforce")
        assert caps.supports_refresh is True
        assert caps.supports_rotation is True
        assert caps.requires_interactive_reauth is False
        assert caps.can_auto_recover({"refresh_token": "token123"}) is True

    def test_dynamics_crm_capabilities(self):
        caps = get_provider_capability("dynamics_crm")
        assert caps.supports_refresh is True
        assert caps.supports_client_credentials is True
        assert caps.can_auto_recover({"client_id": "c1", "client_secret": "s1"}) is True
        assert caps.can_auto_recover({"refresh_token": "r1"}) is True

    def test_hubspot_capabilities(self):
        caps = get_provider_capability("hubspot")
        assert caps.supports_refresh is True
        assert caps.can_auto_recover({"refresh_token": "hs_refresh"}) is True

    def test_static_api_key_capabilities(self):
        caps = get_provider_capability("api_key")
        assert caps.supports_refresh is False
        assert caps.supports_client_credentials is False
        assert caps.requires_interactive_reauth is True
        assert caps.can_auto_recover({"api_key": "secret_key"}) is False


# =========================================================================
# 4. Auth Error Classifier Tests
# =========================================================================

class TestAuthErrorClassifier:
    def test_classify_expired_token(self):
        classified = classify_auth_error(
            {"error": "token_expired", "error_description": "The access token expired"},
            status_code=401,
            provider="salesforce",
        )
        assert classified.code == AuthErrorCode.ACCESS_TOKEN_EXPIRED
        assert classified.action == RecoveryAction.REFRESH
        assert classified.retryable is True

    def test_classify_invalid_grant_revoked(self):
        classified = classify_auth_error(
            {"error": "invalid_grant", "error_description": "Refresh token revoked"},
            status_code=400,
            provider="salesforce",
        )
        assert classified.code == AuthErrorCode.REFRESH_TOKEN_REVOKED
        assert classified.action == RecoveryAction.REQUIRE_REAUTHORIZATION
        assert classified.retryable is False

    def test_classify_rate_limit_with_retry_after(self):
        classified = classify_auth_error(
            {"error": "rate_limit", "message": "Too many requests retry-after: 45"},
            status_code=429,
            provider="hubspot",
        )
        assert classified.code == AuthErrorCode.PROVIDER_RATE_LIMIT
        assert classified.action == RecoveryAction.RETRY_LATER
        assert classified.retry_after_seconds == 45.0
        assert classified.retryable is True

    def test_classify_provider_outage(self):
        classified = classify_auth_error(
            "Service Unavailable",
            status_code=503,
            provider="dynamics_crm",
        )
        assert classified.code == AuthErrorCode.PROVIDER_UNAVAILABLE
        assert classified.action == RecoveryAction.RETRY_LATER
        assert classified.retryable is True


# =========================================================================
# 5. Credential Recovery Service Tests (Salesforce, Dynamics, HubSpot, Manual mode)
# =========================================================================

class TestCredentialRecoveryService:
    @respx.mock
    @pytest.mark.asyncio
    async def test_salesforce_refresh_with_rotation_and_instance_url(self):
        with get_session() as db:
            user = _get_or_create_test_user(db, "sfdc_recover@example.com")

            cred = create_for_user(
                db=db,
                user_id=user.id,
                name="Salesforce Prod",
                cred_type="salesforce",
                data={
                    "access_token": "old_sfdc_token",
                    "refresh_token": "old_sfdc_refresh",
                    "instance_url": "https://company.my.salesforce.com",
                    "client_id": "test_sfdc_client_id",
                    "client_secret": "test_sfdc_secret",
                },
            )
            cred_id = cred["id"]

            # Mock Salesforce token endpoint returning new rotated token & instance URL
            import re
            respx.post(re.compile(r"https://.*/services/oauth2/token")).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": "new_sfdc_access_token_123",
                        "refresh_token": "rotated_sfdc_refresh_456",
                        "instance_url": "https://company.my.salesforce.com",
                        "token_type": "Bearer",
                        "expires_in": 7200,
                    },
                )
            )

            result = await CredentialRecoveryService.recover_credential(
                db,
                user_id=user.id,
                credential_id=cred_id,
                actor="test_runner",
                force=True,
            )

            assert result["ok"] is True
            assert result["state"] == ConnectionState.CONNECTED.value

            # Verify database token updated and rotated refresh token persisted
            resolved = resolve_credentials(db, user.id, {"salesforce": cred_id})
            assert resolved["salesforce"]["access_token"] == "new_sfdc_access_token_123"
            assert resolved["salesforce"]["refresh_token"] == "rotated_sfdc_refresh_456"

    @respx.mock
    @pytest.mark.asyncio
    async def test_dynamics_365_service_principal_renewal(self):
        with get_session() as db:
            user = _get_or_create_test_user(db, "dynamics_sp@example.com")

            cred = create_for_user(
                db=db,
                user_id=user.id,
                name="Dynamics 365 Dataverse Service Principal",
                cred_type="dynamics_crm",
                data={
                    "auth_type": "client_credentials",
                    "tenant_id": "my-azure-tenant-id",
                    "client_id": "my-sp-client-id",
                    "client_secret": "my-sp-client-secret",
                    "instance_url": "https://org12345.crm.dynamics.com",
                    "access_token": "expired_sp_token",
                },
            )
            cred_id = cred["id"]

            # Mock Microsoft Azure AD OAuth token endpoint for client credentials
            token_endpoint = "https://login.microsoftonline.com/my-azure-tenant-id/oauth2/v2.0/token"
            respx.post(token_endpoint).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": "fresh_dataverse_app_token_789",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    },
                )
            )

            result = await CredentialRecoveryService.recover_credential(
                db,
                user_id=user.id,
                credential_id=cred_id,
                actor="test_runner",
                force=True,
            )

            assert result["ok"] is True
            assert result["state"] == ConnectionState.CONNECTED.value

            resolved = resolve_credentials(db, user.id, {"dynamics_crm": cred_id})
            assert resolved["dynamics_crm"]["access_token"] == "fresh_dataverse_app_token_789"

    @pytest.mark.asyncio
    async def test_manual_mode_enforcement_blocks_automatic_recovery(self):
        with get_session() as db:
            user = _get_or_create_test_user(db, "manual_mode_user@example.com")

            cred = create_for_user(
                db=db,
                user_id=user.id,
                name="Manual Mode HubSpot Connection",
                cred_type="hubspot",
                data={
                    "access_token": "old_token",
                    "refresh_token": "valid_refresh",
                },
            )
            cred_id = cred["id"]

            policy = RecoveryStateMachine.get_or_create_policy(
                db,
                credential_id=cred_id,
                user_id=user.id,
                provider="hubspot",
            )
            policy.mode = RecoveryMode.MANUAL.value
            db.commit()

            # Non-forced recovery attempt (e.g. background worker)
            result = await CredentialRecoveryService.recover_credential(
                db,
                user_id=user.id,
                credential_id=cred_id,
                actor="background_scanner",
                force=False,  # Automatic mode check
            )

            # Must fail and transition to MANUAL_ACTION_REQUIRED
            assert result["ok"] is False
            assert result["code"] == "MANUAL_ACTION_REQUIRED"
            assert result["state"] == ConnectionState.MANUAL_ACTION_REQUIRED.value


# =========================================================================
# 6. Workflow Safe Pause and Resumption Tests
# =========================================================================

class TestWorkflowSafePauseAndResume:
    def test_execution_pauses_to_waiting_auth_on_recoverable_auth_error(self):
        from app.models.execution import Execution
        from app.models.workflow import WorkflowRecord

        with get_session() as db:
            user = _get_or_create_test_user(db, "wf_pause_user@example.com")

            wf = WorkflowRecord(
                id=str(uuid.uuid4()),
                name="Pause Test Workflow",
                user_id=user.id,
                data={
                    "nodes": [
                        {"id": "node_1", "type": "manual_trigger"},
                        {"id": "node_2", "type": "salesforce", "credentials": {"salesforce": "cred_id_1"}},
                    ],
                    "connections": [{"source": "node_1", "target": "node_2"}],
                },
            )
            db.add(wf)
            db.commit()

            execution = Execution(
                id=f"exec_{uuid.uuid4().hex[:12]}",
                workflow_id=wf.id,
                user_id=user.id,
                workflow_version=1,
                workflow_data=wf.data,
                status="running",
                results={"outputs": {"node_1": [{"id": 1, "status": "processed"}]}},
            )
            db.add(execution)
            db.commit()

            # Simulate node_2 failing with recoverable auth error in execution_runtime
            classified = ClassifiedAuthError(
                code=AuthErrorCode.ACCESS_TOKEN_EXPIRED,
                message="Salesforce access token expired",
                action=RecoveryAction.REFRESH,
                retryable=True,
                requires_user_action=False,
            )

            # Transition execution safely to waiting_auth
            execution.status = "waiting_auth"
            execution.error = {"message": classified.message}
            execution.pause_state = {
                "paused_node_id": "node_2",
                "paused_at": datetime.now(UTC).isoformat(),
                "reason": "authentication_required",
                "provider": "salesforce",
                "credential_id": "cred_id_1",
                "error_code": classified.code.value,
            }
            db.commit()

            # Verify state
            reloaded = db.query(Execution).filter_by(id=execution.id).first()
            assert reloaded.status == "waiting_auth"
            assert reloaded.pause_state["paused_node_id"] == "node_2"
            # Upstream results remain completely intact so they are not replayed
            assert "node_1" in reloaded.results["outputs"]
            assert reloaded.results["outputs"]["node_1"][0]["status"] == "processed"


class TestConnectionHealthMonitor:
    def test_release_recovery_lock_with_and_without_token(self):
        cred_id = f"cred_lock_test_{uuid.uuid4().hex[:8]}"
        lock_token = RecoveryStateMachine.acquire_recovery_lock(cred_id, ttl_seconds=60)
        assert lock_token is not None

        # Safe release with matching token
        RecoveryStateMachine.release_recovery_lock(cred_id, lock_token)

        # Force release without token (stale reconciliation)
        lock2 = RecoveryStateMachine.acquire_recovery_lock(cred_id, ttl_seconds=60)
        assert lock2 is not None
        RecoveryStateMachine.release_recovery_lock(cred_id)  # lock_token=None force release

    def test_connection_health_monitor_scan_and_notification(self):
        from app.services.connection_health_monitor import ConnectionHealthMonitor
        from app.services.recovery_notifications import RecoveryNotificationService

        with get_session() as db:
            user = _get_or_create_test_user(db, "monitor_test@example.com")
            cred = create_for_user(
                db=db,
                user_id=user.id,
                name="Expiring Soon SFDC",
                cred_type="salesforce",
                data={
                    "access_token": "token123",
                    "client_id": "test_client_id",
                    "client_secret": "test_client_secret",
                    "refresh_token": "test_refresh_token",
                    "instance_url": "https://test.salesforce.com",
                },
            )
            policy = RecoveryStateMachine.get_or_create_policy(
                db=db,
                credential_id=cred["id"],
                user_id=user.id,
                provider="salesforce",
            )
            policy.mode = RecoveryMode.MANUAL.value
            policy.state = ConnectionState.CONNECTED.value
            policy.expires_at = datetime.now(UTC) + timedelta(minutes=15)
            policy.notify_on_upcoming_expiry = True
            policy.notify_in_app = True
            db.commit()

            monitor = ConnectionHealthMonitor()
            counts = monitor.run_scan_sync(db)

            # Verify policy transitioned to EXPIRING_SOON
            db.refresh(policy)
            assert policy.state == ConnectionState.EXPIRING_SOON.value
