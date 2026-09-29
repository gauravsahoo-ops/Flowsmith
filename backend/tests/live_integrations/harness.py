"""Opt-In Real API Live Verification Harness (Phase 41).

Rules:
1. Never store credentials in source code.
2. Only execute when FLOWSMITH_LIVE_TESTS=true and required environment variables exist.
3. If credentials are missing, mark LIVE_TEST_UNAVAILABLE (never LIVE_TEST_PASSED).
4. Track all live verification outcomes in a structured audit ledger.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

logger = logging.getLogger("flowsmith.live_tests")

LIVE_AUDIT_LOG_PATH = Path(r"c:\Flowsmith\docs\integration-platform\LIVE_API_AUDIT_RESULTS.json")


@dataclass
class LiveTestOutcome:
    connector_key: str
    operation: str
    status: str  # "LIVE_SUCCESS", "LIVE_FAILED", "LIVE_TEST_UNAVAILABLE"
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    endpoint_called: Optional[str] = None
    status_code: Optional[int] = None
    error_message: Optional[str] = None


class LiveTestRegistry:
    """Thread-safe ledger tracking all live API test executions."""

    def __init__(self) -> None:
        self.outcomes: List[LiveTestOutcome] = []

    def record(
        self,
        connector_key: str,
        operation: str,
        status: str,
        duration_ms: float = 0.0,
        endpoint_called: Optional[str] = None,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> LiveTestOutcome:
        outcome = LiveTestOutcome(
            connector_key=connector_key,
            operation=operation,
            status=status,
            duration_ms=duration_ms,
            endpoint_called=endpoint_called,
            status_code=status_code,
            error_message=error_message,
        )
        self.outcomes.append(outcome)
        logger.info(
            "LiveTest [%s:%s] -> %s (%0.1fms)",
            connector_key,
            operation,
            status,
            duration_ms,
        )
        return outcome

    def save_audit_file(self, target_path: Optional[Path] = None) -> None:
        path = target_path or LIVE_AUDIT_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "total_tests_recorded": len(self.outcomes),
            "live_success_count": sum(1 for o in self.outcomes if o.status == "LIVE_SUCCESS"),
            "live_failed_count": sum(1 for o in self.outcomes if o.status == "LIVE_FAILED"),
            "live_unavailable_count": sum(1 for o in self.outcomes if o.status == "LIVE_TEST_UNAVAILABLE"),
            "outcomes": [asdict(o) for o in self.outcomes],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)


# Global singleton instance
live_registry = LiveTestRegistry()


def is_live_testing_enabled() -> bool:
    """Returns True only when FLOWSMITH_LIVE_TESTS environment variable is set to true."""
    val = os.getenv("FLOWSMITH_LIVE_TESTS", "").strip().lower()
    return val in ("true", "1", "yes")


def require_live_credentials(app_name: str, required_vars: List[str]) -> Dict[str, str]:
    """Ensures opt-in live test prerequisites are met.

    Skips test with 'LIVE_TEST_UNAVAILABLE' if live testing is disabled or any credential is missing.
    NEVER marks a test as passed when credentials are unavailable.
    """
    if not is_live_testing_enabled():
        live_registry.record(
            connector_key=app_name,
            operation="live_auth",
            status="LIVE_TEST_UNAVAILABLE",
            error_message="FLOWSMITH_LIVE_TESTS is not set to true",
        )
        pytest.skip(f"LIVE_TEST_UNAVAILABLE: FLOWSMITH_LIVE_TESTS is disabled for {app_name}")

    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        live_registry.record(
            connector_key=app_name,
            operation="live_auth",
            status="LIVE_TEST_UNAVAILABLE",
            error_message=f"Missing required environment credentials: {', '.join(missing)}",
        )
        pytest.skip(
            f"LIVE_TEST_UNAVAILABLE: Missing required environment credentials for {app_name}: {', '.join(missing)}"
        )

    return {var: os.getenv(var, "") for var in required_vars}
