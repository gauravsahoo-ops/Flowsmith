"""Application Lifecycle State Machine & Observability (Phase 11 / Enterprise Stability).

Tracks formal startup stages, durations, process identity, and readiness state.
Ensures application readiness accurately reflects completion of mandatory initialization.
"""

from __future__ import annotations

import enum
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("flowsmith.lifecycle")


class StartupStage(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    CONFIG_VALIDATION = "CONFIG_VALIDATION"
    DATABASE_CONNECTIVITY = "DATABASE_CONNECTIVITY"
    SCHEMA_REVISION_VERIFICATION = "SCHEMA_REVISION_VERIFICATION"
    CONNECTOR_REGISTRY_INIT = "CONNECTOR_REGISTRY_INIT"
    REDIS_CONNECTIVITY = "REDIS_CONNECTIVITY"
    SERVICE_INITIALIZATION = "SERVICE_INITIALIZATION"
    STARTUP_COMPLETE = "STARTUP_COMPLETE"
    READINESS_ENABLED = "READINESS_ENABLED"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    FAILED = "FAILED"


class LifecycleManager:
    """Thread-safe lifecycle manager tracking startup progression and system readiness."""

    def __init__(self, service_name: str = "flowsmith-backend") -> None:
        self.service_name = service_name
        self.pid = os.getpid()
        self._stage: StartupStage = StartupStage.NOT_STARTED
        self._start_time: float = time.monotonic()
        self._stage_start_time: float = self._start_time
        self._stage_history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._failure_reason: Optional[str] = None
        self._metadata: Dict[str, Any] = {}

    @property
    def current_stage(self) -> StartupStage:
        return self._stage

    @property
    def is_ready(self) -> bool:
        return self._stage == StartupStage.READINESS_ENABLED

    @property
    def is_failed(self) -> bool:
        return self._stage == StartupStage.FAILED

    @property
    def failure_reason(self) -> Optional[str]:
        return self._failure_reason

    def set_metadata(self, key: str, value: Any) -> None:
        with self._lock:
            self._metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._metadata.get(key, default)

    def transition_to(self, stage: StartupStage, message: str = "") -> None:
        """Atomically transition to a new lifecycle stage with structured logging."""
        now = time.monotonic()
        with self._lock:
            prev_stage = self._stage
            duration_s = round(now - self._stage_start_time, 4)
            self._stage_history.append({
                "from_stage": prev_stage.value,
                "to_stage": stage.value,
                "duration_s": duration_s,
                "timestamp": time.time(),
                "message": message,
            })
            self._stage = stage
            self._stage_start_time = now

            extra_info = f" - {message}" if message else ""
            logger.info(
                "[LIFECYCLE] Service=%s PID=%d Stage=%s (previous=%s took=%.3fs)%s",
                self.service_name,
                self.pid,
                stage.value,
                prev_stage.value,
                duration_s,
                extra_info,
            )

    def mark_failed(self, error: Exception | str, stage: Optional[StartupStage] = None) -> None:
        """Mark lifecycle as failed and log diagnostic details without leaking credentials."""
        now = time.monotonic()
        err_str = str(error)
        with self._lock:
            self._failure_reason = err_str
            self._stage = StartupStage.FAILED
            duration_s = round(now - self._stage_start_time, 4)
            failed_at = stage.value if stage else "UNKNOWN"
            self._stage_history.append({
                "from_stage": failed_at,
                "to_stage": StartupStage.FAILED.value,
                "duration_s": duration_s,
                "error": err_str,
                "timestamp": time.time(),
            })
            logger.error(
                "[LIFECYCLE_FAILED] Service=%s PID=%d Stage=%s Error=%s",
                self.service_name,
                self.pid,
                failed_at,
                err_str,
            )

    def get_status_summary(self) -> Dict[str, Any]:
        """Return non-sensitive structured status summary for readiness probe."""
        with self._lock:
            total_uptime_s = round(time.monotonic() - self._start_time, 2)
            return {
                "service": self.service_name,
                "pid": self.pid,
                "stage": self._stage.value,
                "is_ready": self.is_ready,
                "failed": self.is_failed,
                "failure_reason": self._failure_reason,
                "uptime_s": total_uptime_s,
                "metadata": dict(self._metadata),
                "history": list(self._stage_history),
            }


# Process-wide singleton
_lifecycle_manager = LifecycleManager()


def get_lifecycle() -> LifecycleManager:
    return _lifecycle_manager
