"""Connection Health Monitor & Proactive Recovery Daemon.

Runs periodically in the background to scan expiring credentials,
execute proactive OAuth renewals, reconcile interrupted recoveries,
and clean up stale sessions and locks without requiring an open browser tab.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.connection_auth_policy import ConnectionAuthPolicy
from app.models.credential import Credential
from app.models.recovery_state import ConnectionState, RecoveryMode
from app.services.credential_recovery_service import CredentialRecoveryService
from app.services.recovery_notifications import RecoveryNotificationService
from app.services.recovery_state_machine import RecoveryStateMachine

logger = logging.getLogger("auth.health_monitor")

DEFAULT_SCAN_INTERVAL_S = 60
DEFAULT_EXPIRY_WINDOW_S = 1800  # 30 minutes
STALE_REFRESHING_TIMEOUT_S = 300  # 5 minutes


class ConnectionHealthMonitor:
    """Monitors connection health and coordinates proactive renewal."""

    def __init__(self, interval_seconds: int = DEFAULT_SCAN_INTERVAL_S) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def ensure_started(self) -> None:
        """Start the background monitoring daemon."""
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._loop())
            logger.info("ConnectionHealthMonitor started with %ds scan interval", self.interval_seconds)

    async def stop(self) -> None:
        """Gracefully stop the daemon."""
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                if self._task.get_loop() is asyncio.get_running_loop():
                    await self._task
            except (asyncio.CancelledError, RuntimeError):
                pass
        logger.info("ConnectionHealthMonitor stopped")

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.run_scan_async()
            except Exception:
                logger.exception("Error during ConnectionHealthMonitor scan")
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

    async def run_scan_async(self) -> dict[str, int]:
        """Perform one scan pass using a fresh DB session."""
        db = get_session()
        try:
            return await asyncio.to_thread(self.run_scan_sync, db)
        finally:
            db.close()

    def run_scan_sync(self, db: Session) -> dict[str, int]:
        """Synchronous scan pass for proactive refresh, retry reconciliation, and lock cleanup."""
        now = datetime.now(UTC)
        expiry_threshold = now + timedelta(seconds=DEFAULT_EXPIRY_WINDOW_S)

        proactive_count = 0
        retry_count = 0
        reconciled_stale_count = 0

        # 1. Stale REFRESHING reconciliation
        stale_limit = now - timedelta(seconds=STALE_REFRESHING_TIMEOUT_S)
        stale_refreshing = db.scalars(
            select(ConnectionAuthPolicy).where(
                ConnectionAuthPolicy.state == ConnectionState.REFRESHING.value,
                ConnectionAuthPolicy.updated_at <= stale_limit,
            )
        ).all()
        for pol in stale_refreshing:
            logger.warning(
                "Reconciling stale REFRESHING connection %s (stuck since %s)",
                pol.credential_id,
                pol.updated_at,
            )
            RecoveryStateMachine.release_recovery_lock(pol.credential_id)
            RecoveryStateMachine.transition(
                db=db,
                credential_id=pol.credential_id,
                target_state=ConnectionState.RECOVERY_PENDING,
                actor="health_monitor:reconcile",
                error_code="STALE_REFRESH_RESET",
                error_message="Recovery worker heartbeat timed out; reset for retry.",
            )
            reconciled_stale_count += 1

        # 2. Overdue retry attempts (PROVIDER_UNAVAILABLE or RECOVERY_PENDING)
        due_retries = db.scalars(
            select(ConnectionAuthPolicy).where(
                ConnectionAuthPolicy.state.in_([
                    ConnectionState.PROVIDER_UNAVAILABLE.value,
                    ConnectionState.RECOVERY_PENDING.value,
                ]),
                ConnectionAuthPolicy.next_recovery_at.is_not(None),
                ConnectionAuthPolicy.next_recovery_at <= now,
            )
        ).all()
        for pol in due_retries:
            logger.info("Executing due retry recovery for connection %s", pol.credential_id)
            try:
                # Trigger recovery
                loop = None
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass
                if loop and loop.is_running():
                    asyncio.create_task(
                        CredentialRecoveryService.recover_credential(
                            db=db,
                            user_id=pol.user_id,
                            credential_id=pol.credential_id,
                            actor="health_monitor:scheduled_retry",
                            trigger="scheduled_retry",
                        )
                    )
                else:
                    asyncio.run(
                        CredentialRecoveryService.recover_credential(
                            db=db,
                            user_id=pol.user_id,
                            credential_id=pol.credential_id,
                            actor="health_monitor:scheduled_retry",
                            trigger="scheduled_retry",
                        )
                    )
                retry_count += 1
            except Exception:
                logger.exception("Failed to schedule retry for %s", pol.credential_id)

        # 3. Proactive expiration scan
        expiring_policies = db.scalars(
            select(ConnectionAuthPolicy).where(
                ConnectionAuthPolicy.expires_at.is_not(None),
                ConnectionAuthPolicy.expires_at <= expiry_threshold,
                ConnectionAuthPolicy.state.not_in([
                    ConnectionState.DISCONNECTED.value,
                    ConnectionState.REVOKED.value,
                    ConnectionState.REFRESHING.value,
                ]),
            )
        ).all()

        for pol in expiring_policies:
            cred = db.get(Credential, pol.credential_id)
            if not cred:
                continue

            if pol.mode == RecoveryMode.MANUAL.value:
                # Manual mode: do NOT auto-refresh! Transition to MANUAL_ACTION_REQUIRED or EXPIRING_SOON
                if pol.expires_at is not None and pol.expires_at <= now and pol.state != ConnectionState.MANUAL_ACTION_REQUIRED.value:
                    RecoveryStateMachine.transition(
                        db=db,
                        credential_id=pol.credential_id,
                        target_state=ConnectionState.MANUAL_ACTION_REQUIRED,
                        actor="health_monitor:manual_expiry",
                        error_code="MANUAL_EXPIRY",
                        error_message="Credential expired in Manual mode.",
                    )
                    if pol.notify_in_app or pol.notify_email:
                        RecoveryNotificationService.notify_manual_action_required(
                            db=db, policy=pol, credential_name=cred.name
                        )
                elif pol.state == ConnectionState.CONNECTED.value:
                    RecoveryStateMachine.transition(
                        db=db,
                        credential_id=pol.credential_id,
                        target_state=ConnectionState.EXPIRING_SOON,
                        actor="health_monitor:manual_expiring_soon",
                    )
                    if pol.notify_on_upcoming_expiry and (pol.notify_in_app or pol.notify_email):
                        RecoveryNotificationService.notify_upcoming_expiry(
                            db=db, policy=pol, credential_name=cred.name
                        )
            else:
                # Automatic recovery mode: schedule proactive renewal
                logger.info("Triggering proactive renewal for expiring connection %s", pol.credential_id)
                try:
                    loop = None
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        pass
                    if loop and loop.is_running():
                        asyncio.create_task(
                            CredentialRecoveryService.recover_credential(
                                db=db,
                                user_id=pol.user_id,
                                credential_id=pol.credential_id,
                                actor="health_monitor:proactive",
                                trigger="proactive_expiry",
                            )
                        )
                    else:
                        asyncio.run(
                            CredentialRecoveryService.recover_credential(
                                db=db,
                                user_id=pol.user_id,
                                credential_id=pol.credential_id,
                                actor="health_monitor:proactive",
                                trigger="proactive_expiry",
                            )
                        )
                    proactive_count += 1
                except Exception:
                    logger.exception("Failed to run proactive renewal for %s", pol.credential_id)

        # 4. Cleanup expired sessions
        try:
            from app.models.auth_session import AuthSession
            old_cutoff = now - timedelta(days=30)
            db.query(AuthSession).filter(
                AuthSession.is_active == False,
                AuthSession.revoked_at <= old_cutoff,
            ).delete(synchronize_session=False)
            db.commit()
        except Exception:
            pass

        return {
            "proactive_renewals": proactive_count,
            "scheduled_retries": retry_count,
            "reconciled_stale": reconciled_stale_count,
        }


connection_health_monitor = ConnectionHealthMonitor()
