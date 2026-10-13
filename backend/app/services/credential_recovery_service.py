"""Centralized Credential Recovery Service.

Orchestrates automatic vs. manual recovery, refresh-token rotation,
provider-specific adapters (Salesforce, Dynamics 365, HubSpot), distributed locking,
and notifications.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.credentials.credential_store import get_credential_store
from app.credentials.provider_capabilities import get_provider_capability
from app.models.credential import Credential
from app.models.recovery_state import (
    AuthErrorCode,
    ConnectionState,
    RecoveryMode,
)
from app.security.crypto import encrypt_text
from app.services.auth_error_classifier import (
    RecoveryAction,
    classify_auth_error,
)
from app.services.recovery_notifications import RecoveryNotificationService
from app.services.recovery_state_machine import RecoveryStateMachine

logger = logging.getLogger("auth.credential_recovery")


class CredentialRecoveryService:
    """Coordinates credential renewal, state machine, and provider handlers."""

    @classmethod
    async def recover_credential(
        cls,
        db: Session,
        user_id: int,
        credential_id: str,
        force: bool = False,
        actor: str = "system",
        trigger: str = "execution_failure",
    ) -> dict[str, Any]:
        """Attempt to recover/renew an integration credential according to policy."""
        rec = db.get(Credential, credential_id)
        if rec is None or rec.user_id != user_id:
            return {"ok": False, "code": "NOT_FOUND", "message": "Credential not found"}

        # Resolve or create policy
        policy = RecoveryStateMachine.get_or_create_policy(
            db=db,
            credential_id=credential_id,
            user_id=user_id,
            provider=rec.type,
        )

        # 1. Enforce MANUAL mode: do NOT silently refresh if user selected Manual mode!
        if policy.mode == RecoveryMode.MANUAL.value and not force:
            logger.info("Credential %s is configured for MANUAL authentication; skipping auto-refresh", credential_id)
            if policy.state != ConnectionState.MANUAL_ACTION_REQUIRED.value:
                RecoveryStateMachine.transition(
                    db=db,
                    credential_id=credential_id,
                    target_state=ConnectionState.MANUAL_ACTION_REQUIRED,
                    actor=actor,
                    error_code=AuthErrorCode.MANUAL_MODE_LOCKED.value,
                    error_message="Manual authentication mode enabled. User action required.",
                )
                if policy.notify_in_app or policy.notify_email:
                    RecoveryNotificationService.notify_manual_action_required(
                        db=db, policy=policy, credential_name=rec.name
                    )
            return {
                "ok": False,
                "code": "MANUAL_ACTION_REQUIRED",
                "state": ConnectionState.MANUAL_ACTION_REQUIRED.value,
                "message": "Credential requires manual reconnection (Manual mode configured).",
            }

        # Check capability
        capability = get_provider_capability(rec.type)
        cred_store = get_credential_store()
        try:
            cred_data = cred_store.decrypt(rec)
        except Exception as exc:
            return {"ok": False, "code": "DECRYPTION_FAILED", "message": str(exc)}

        if not capability.can_auto_recover(cred_data) and not force:
            RecoveryStateMachine.transition(
                db=db,
                credential_id=credential_id,
                target_state=ConnectionState.REAUTHORIZATION_REQUIRED,
                actor=actor,
                error_code=AuthErrorCode.REFRESH_TOKEN_EXPIRED.value,
                error_message="Credential lacks refresh material for background recovery.",
            )
            RecoveryNotificationService.notify_reauthorization_required(
                db=db, policy=policy, credential_name=rec.name, reason="Missing refresh material"
            )
            return {
                "ok": False,
                "code": "REAUTHORIZATION_REQUIRED",
                "state": ConnectionState.REAUTHORIZATION_REQUIRED.value,
                "message": "Credential cannot be renewed automatically. Reauthorization required.",
            }

        # 2. Acquire single-flight distributed lock
        lock_token = RecoveryStateMachine.acquire_recovery_lock(credential_id)
        if not lock_token:
            logger.info("Credential %s renewal is already in-flight by another worker", credential_id)
            return {
                "ok": True,
                "code": "REFRESH_IN_PROGRESS",
                "state": ConnectionState.REFRESHING.value,
                "message": "Recovery attempt already in progress.",
            }

        try:
            # Transition to REFRESHING
            RecoveryStateMachine.transition(
                db=db,
                credential_id=credential_id,
                target_state=ConnectionState.REFRESHING,
                actor=actor,
            )

            # 3. Execute Provider-specific renewal
            new_data = await cls._execute_provider_renewal(
                provider=rec.type,
                cred_data=cred_data,
                credential_id=credential_id,
            )

            # 4. Atomic encrypted persistence
            rec.data = encrypt_text(json.dumps(new_data, ensure_ascii=False))
            policy.last_authenticated_at = datetime.now(UTC)
            policy.expires_at = datetime.fromtimestamp(new_data["expires_at"], tz=UTC) if new_data.get("expires_at") else None
            policy.next_recovery_at = None
            db.commit()

            # Transition to CONNECTED
            RecoveryStateMachine.transition(
                db=db,
                credential_id=credential_id,
                target_state=ConnectionState.CONNECTED,
                actor=actor,
                details={"provider": rec.type, "expires_at": new_data.get("expires_at")},
            )

            # Notify on success if configured
            if policy.mode == RecoveryMode.AUTOMATIC_WITH_NOTIFICATIONS.value and policy.notify_in_app:
                RecoveryNotificationService.notify_recovery_succeeded(
                    db=db, policy=policy, credential_name=rec.name
                )

            logger.info("Successfully recovered credential %s (%s)", credential_id, rec.name)
            return {
                "ok": True,
                "code": "RECOVERED",
                "state": ConnectionState.CONNECTED.value,
                "message": "Credential successfully renewed.",
            }

        except Exception as exc:
            logger.exception("Failed to recover credential %s: %s", credential_id, exc)
            classification = classify_auth_error(exc, provider=rec.type)

            if classification.action == RecoveryAction.REQUIRE_REAUTHORIZATION:
                RecoveryStateMachine.transition(
                    db=db,
                    credential_id=credential_id,
                    target_state=ConnectionState.REAUTHORIZATION_REQUIRED,
                    actor=actor,
                    error_code=classification.code.value,
                    error_message=str(exc),
                )
                RecoveryNotificationService.notify_reauthorization_required(
                    db=db, policy=policy, credential_name=rec.name, reason=classification.message
                )
            elif classification.action == RecoveryAction.RETRY_LATER:
                # Schedule retry with backoff
                retry_sec = classification.retry_after_seconds or min(300, 30 * (2 ** policy.consecutive_failures))
                policy.next_recovery_at = datetime.now(UTC) + timedelta(seconds=retry_sec)
                RecoveryStateMachine.transition(
                    db=db,
                    credential_id=credential_id,
                    target_state=ConnectionState.PROVIDER_UNAVAILABLE,
                    actor=actor,
                    error_code=classification.code.value,
                    error_message=str(exc),
                )
            else:
                RecoveryStateMachine.transition(
                    db=db,
                    credential_id=credential_id,
                    target_state=ConnectionState.AUTHENTICATION_FAILED,
                    actor=actor,
                    error_code=classification.code.value,
                    error_message=str(exc),
                )
                if policy.notify_on_recovery_failure:
                    RecoveryNotificationService.notify_recovery_failed(
                        db=db, policy=policy, credential_name=rec.name, error_message=str(exc)
                    )

            return {
                "ok": False,
                "code": classification.code.value,
                "state": policy.state,
                "message": f"Recovery failed: {exc}",
            }
        finally:
            RecoveryStateMachine.release_recovery_lock(credential_id, lock_token)

    @classmethod
    async def _execute_provider_renewal(
        cls,
        provider: str,
        cred_data: dict[str, Any],
        credential_id: str,
    ) -> dict[str, Any]:
        """Dispatch renewal to provider client."""
        canon = provider.lower()
        updated = dict(cred_data)
        updated["_credential_id"] = credential_id

        # A. Salesforce
        if "salesforce" in canon:
            from app.providers.salesforce import SalesforceProviderClient

            client = SalesforceProviderClient()
            token = await client.authenticate(updated, force=True)
            updated["access_token"] = token
            if client._instance_url:
                updated["instance_url"] = client._instance_url
            if getattr(client, "_refresh_token", None):
                updated["refresh_token"] = client._refresh_token
            return updated

        # B. Microsoft Dynamics 365 / Dataverse
        elif "dynamics" in canon:
            from app.providers.dynamics_crm import DynamicsCrmProviderClient

            client = DynamicsCrmProviderClient()
            instance_url = client._validate_creds(updated)
            auth_type = str(updated.get("auth_type") or "oauth2").lower()
            tenant_id = str(updated.get("tenant_id") or "common").strip()
            client_id = str(updated.get("client_id") or "").strip()
            client_secret = str(updated.get("client_secret") or "").strip()
            refresh_token = str(updated.get("refresh_token") or "").strip()

            if auth_type == "client_credentials" or (not refresh_token and client_id and client_secret):
                # Service Principal token renewal
                token, exp = await client._get_client_credentials_token(
                    tenant_id, client_id, client_secret, instance_url
                )
                updated["access_token"] = token
                updated["expires_at"] = time.time() + 3500.0
                return updated
            else:
                # Interactive OAuth refresh
                token, exp = await client._refresh_oauth_token(
                    tenant_id, refresh_token, client_id, client_secret
                )
                updated["access_token"] = token
                updated["expires_at"] = time.time() + 3500.0
                return updated

        # C. HubSpot
        elif "hubspot" in canon:
            from app.providers.hubspot import HubSpotProviderClient

            client = HubSpotProviderClient()
            refresh_token = str(updated.get("refresh_token") or "").strip()
            if not refresh_token:
                raise ValueError("HubSpot OAuth requires a valid refresh token.")
            token, exp_epoch = await client._refresh_access_token(refresh_token)
            updated["access_token"] = token
            updated["expires_at"] = exp_epoch
            return updated

        # D. Generic OAuth2
        else:
            from app.credentials.oauth_manager import get_oauth_manager

            oauth_mgr = get_oauth_manager()
            return await oauth_mgr.refresh(updated)
