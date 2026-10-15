"""Centralized Recovery State Machine and Single-Flight Coordination.

Enforces legal state transitions, single-flight locking across worker nodes,
audit event recording, and policy verification.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection_auth_policy import ConnectionAuthPolicy, CredentialAuditEvent
from app.models.recovery_state import (
    ConnectionState,
    RecoveryMode,
    can_transition,
)
from app.security.redis_client import get_shared_redis

logger = logging.getLogger("auth.state_machine")


class RecoveryStateMachine:
    """Manages connection states with strict validation and distributed locks."""

    @classmethod
    def get_or_create_policy(
        cls,
        db: Session,
        credential_id: str,
        user_id: int,
        provider: str = "",
        auth_type: str = "oauth2",
    ) -> ConnectionAuthPolicy:
        """Fetch existing policy or initialize default policy for a credential."""
        policy = db.scalar(
            select(ConnectionAuthPolicy).where(ConnectionAuthPolicy.credential_id == credential_id)
        )
        if policy is None:
            now = datetime.now(UTC)
            policy = ConnectionAuthPolicy(
                id=str(uuid.uuid4()),
                credential_id=credential_id,
                user_id=user_id,
                mode=RecoveryMode.AUTOMATIC.value,
                state=ConnectionState.CONNECTED.value,
                provider=provider or "",
                auth_type=auth_type or "oauth2",
                notify_in_app=True,
                notify_email=True,
                notify_on_recovery_failure=True,
                notify_on_upcoming_expiry=True,
                last_authenticated_at=now,
                consecutive_failures=0,
                created_at=now,
                updated_at=now,
            )
            db.add(policy)
            db.commit()
            db.refresh(policy)
            cls.record_audit_event(
                db=db,
                credential_id=credential_id,
                user_id=user_id,
                event_type="policy_created",
                previous_state=None,
                new_state=ConnectionState.CONNECTED.value,
                actor="system",
                details={"mode": policy.mode, "provider": provider},
            )
        return policy

    @classmethod
    def transition(
        cls,
        db: Session,
        credential_id: str,
        target_state: ConnectionState | str,
        actor: str = "system",
        error_code: str | None = None,
        error_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ConnectionAuthPolicy:
        """Atomically transition connection state if legal."""
        target_enum = ConnectionState(target_state) if isinstance(target_state, str) else target_state

        policy = db.scalar(
            select(ConnectionAuthPolicy)
            .where(ConnectionAuthPolicy.credential_id == credential_id)
            .with_for_update()
        )
        if policy is None:
            raise ValueError(f"No auth policy found for credential {credential_id}")

        current_enum = ConnectionState(policy.state)
        if not can_transition(current_enum, target_enum):
            logger.warning(
                "Illegal state transition rejected: credential %s cannot transition from %s to %s",
                credential_id,
                current_enum.value,
                target_enum.value,
            )
            raise ValueError(f"Illegal state transition from {current_enum.value} to {target_enum.value}")

        previous_state = policy.state
        policy.state = target_enum.value
        policy.updated_at = datetime.now(UTC)

        if error_code:
            policy.last_error_code = error_code
        if error_message:
            policy.last_error_message = error_message[:500]

        if target_enum == ConnectionState.CONNECTED:
            policy.consecutive_failures = 0
            policy.last_authenticated_at = datetime.now(UTC)
            policy.last_error_code = None
            policy.last_error_message = None
        elif target_enum in (
            ConnectionState.AUTHENTICATION_FAILED,
            ConnectionState.PROVIDER_UNAVAILABLE,
            ConnectionState.REAUTHORIZATION_REQUIRED,
        ):
            policy.consecutive_failures += 1

        db.commit()
        db.refresh(policy)

        # Record audit event
        cls.record_audit_event(
            db=db,
            credential_id=credential_id,
            user_id=policy.user_id,
            organization_id=policy.organization_id,
            event_type="state_transition",
            previous_state=previous_state,
            new_state=target_enum.value,
            actor=actor,
            details=details or {"error_code": error_code, "error_message": error_message},
        )
        logger.info(
            "Connection %s transitioned: %s -> %s (actor: %s)",
            credential_id,
            previous_state,
            target_enum.value,
            actor,
        )
        return policy

    @classmethod
    def record_audit_event(
        cls,
        db: Session,
        credential_id: str,
        user_id: int,
        event_type: str,
        previous_state: str | None,
        new_state: str | None,
        actor: str = "system",
        organization_id: str | None = None,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> CredentialAuditEvent:
        """Persist a sanitized audit log row."""
        sanitized_details = {}
        if details:
            for k, v in details.items():
                k_lower = k.lower()
                if any(sec in k_lower for sec in ("token", "secret", "password", "key", "auth")):
                    sanitized_details[k] = "[REDACTED]"
                else:
                    sanitized_details[k] = v

        event = CredentialAuditEvent(
            id=str(uuid.uuid4()),
            credential_id=credential_id,
            user_id=user_id,
            organization_id=organization_id,
            event_type=event_type,
            previous_state=previous_state,
            new_state=new_state,
            actor=actor,
            details=sanitized_details,
            correlation_id=correlation_id or str(uuid.uuid4()),
            created_at=datetime.now(UTC),
        )
        db.add(event)
        db.commit()
        return event

    @classmethod
    def acquire_recovery_lock(cls, credential_id: str, ttl_seconds: int = 45) -> str | None:
        """Acquire a single-flight distributed lock for credential refresh."""
        lock_token = str(uuid.uuid4())
        r = get_shared_redis()
        if r is not None:
            try:
                acquired = r.set(f"cred_rec_lock:{credential_id}", lock_token, nx=True, ex=ttl_seconds)
                if acquired:
                    return lock_token
                return None
            except Exception:
                pass
        # If Redis is unavailable, fallback to process-level token
        return lock_token

    @classmethod
    def release_recovery_lock(cls, credential_id: str, lock_token: str | None = None) -> None:
        """Release the single-flight distributed lock if token matches (or force-release if None)."""
        r = get_shared_redis()
        if r is not None:
            try:
                if lock_token is None:
                    r.delete(f"cred_rec_lock:{credential_id}")
                else:
                    val = r.get(f"cred_rec_lock:{credential_id}")
                    if val and (val == lock_token or val.decode("utf-8", "ignore") == lock_token):
                        r.delete(f"cred_rec_lock:{credential_id}")
            except Exception:
                pass
