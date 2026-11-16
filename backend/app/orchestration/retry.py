"""Retry delay and budget policy.

Pure helpers so the engine, orchestration tooling, and tests can share one
retry contract without importing SQLAlchemy, FastAPI, or ``app.api``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

MAX_RETRY_BACKOFF_S = 60.0


@dataclass(frozen=True)
class RetryBudget:
    """Resolved retry policy for a single node run."""

    max_attempts: int
    backoff_s: float


def retry_delay(
    backoff: float,
    retries: int,
    retry_after: Any = None,
    *,
    max_delay: float = MAX_RETRY_BACKOFF_S,
) -> float:
    """Return a bounded, safe retry delay.

    Provider ``Retry-After`` values are untrusted and can be negative,
    non-finite, or absurdly large. They must never reach ``asyncio.sleep``
    raw. The fallback is exponential backoff capped at ``max_delay``.
    """
    if retry_after is not None:
        try:
            candidate = float(retry_after)
        except (TypeError, ValueError, OverflowError):
            candidate = None
        if candidate is not None and math.isfinite(candidate) and candidate >= 0:
            return min(candidate, max_delay)
    try:
        computed = float(backoff) * (2 ** max(retries - 1, 0))
    except (TypeError, ValueError, OverflowError):
        computed = 0.0
    if not math.isfinite(computed):
        computed = 0.0
    return max(0.0, min(computed, max_delay))


def retry_budget(settings: Mapping[str, Any] | None) -> RetryBudget:
    """Resolve a node's retry settings into a typed budget.

    ``retry_max_attempts`` counts retries, so attempts are one higher. An
    invalid ``retry_backoff_seconds`` falls back to the historical 2s default.
    """
    values = settings or {}
    max_attempts = max(1, int(values.get("retry_max_attempts", 0) or 0) + 1)
    try:
        backoff_s = max(0.0, float(values.get("retry_backoff_seconds", 2) or 2))
    except (TypeError, ValueError):
        backoff_s = 2.0
    return RetryBudget(max_attempts=max_attempts, backoff_s=backoff_s)
