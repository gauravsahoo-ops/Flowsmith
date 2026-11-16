"""Retry policy tests for ``app.orchestration.retry``.

The helpers are pure: no database, FastAPI, or ``app.api`` dependency is
needed to exercise them.
"""

from __future__ import annotations

import math

import pytest

from app.orchestration.retry import (
    MAX_RETRY_BACKOFF_S,
    RetryBudget,
    retry_budget,
    retry_delay,
)


def test_exponential_backoff_sequence() -> None:
    assert [retry_delay(2.0, retries) for retries in (1, 2, 3, 4)] == [2.0, 4.0, 8.0, 16.0]
    # The first attempt (or a nonsensical negative retry count) uses the base.
    assert retry_delay(2.0, 0) == 2.0
    assert retry_delay(0.25, -3) == 0.25


def test_retry_after_is_honoured_and_capped() -> None:
    assert retry_delay(2.0, 1, 7.5) == 7.5
    assert retry_delay(2.0, 1, "3.5") == 3.5
    assert retry_delay(2.0, 1, 10_000) == MAX_RETRY_BACKOFF_S
    assert retry_delay(2.0, 1, 0) == 0.0
    # A custom cap (the executor patches its module constant) still clamps.
    assert retry_delay(2.0, 1, 10_000, max_delay=0.03) == 0.03


@pytest.mark.parametrize(
    "retry_after",
    [-5, float("nan"), float("inf"), float("-inf"), "not-a-number", object(), None],
)
def test_invalid_retry_after_falls_back_to_exponential(retry_after: object) -> None:
    assert retry_delay(2.0, 2, retry_after) == 4.0


@pytest.mark.parametrize(
    "backoff",
    [float("nan"), float("inf"), float("-inf"), "not-a-number", None, object()],
)
def test_invalid_backoff_produces_finite_non_negative(backoff: object) -> None:
    delay = retry_delay(backoff, 2)  # type: ignore[arg-type]
    assert math.isfinite(delay)
    assert delay >= 0.0


@pytest.mark.parametrize("retries", [None, "two", float("nan"), float("inf"), -100])
def test_invalid_retries_produce_finite_non_negative(retries: object) -> None:
    delay = retry_delay(2.0, retries)  # type: ignore[arg-type]
    assert math.isfinite(delay)
    assert 0.0 <= delay <= MAX_RETRY_BACKOFF_S


def test_retry_budget_defaults_when_settings_are_unset() -> None:
    assert retry_budget(None) == RetryBudget(max_attempts=1, backoff_s=2.0)
    assert retry_budget({}) == RetryBudget(max_attempts=1, backoff_s=2.0)


def test_retry_budget_zero_and_positive_values() -> None:
    # Zero backoff keeps the historical ``or 2`` coercion to the 2s default.
    assert retry_budget({"retry_max_attempts": 0, "retry_backoff_seconds": 0}) == RetryBudget(
        max_attempts=1, backoff_s=2.0
    )
    assert retry_budget({"retry_max_attempts": 3, "retry_backoff_seconds": 0.5}) == RetryBudget(
        max_attempts=4, backoff_s=0.5
    )
    # Numeric strings follow the engine's permissive int/float parsing.
    assert retry_budget({"retry_max_attempts": "2", "retry_backoff_seconds": "1.5"}) == RetryBudget(
        max_attempts=3, backoff_s=1.5
    )


def test_retry_budget_never_drops_below_one_attempt() -> None:
    assert retry_budget({"retry_max_attempts": -4}).max_attempts == 1


def test_retry_budget_clamps_negative_backoff() -> None:
    assert retry_budget({"retry_backoff_seconds": -10}) == RetryBudget(max_attempts=1, backoff_s=0.0)


@pytest.mark.parametrize("value", ["not-a-number", None, object()])
def test_retry_budget_invalid_backoff_falls_back_to_two_seconds(value: object) -> None:
    assert retry_budget({"retry_backoff_seconds": value}).backoff_s == 2.0


def test_executor_wrapper_honours_patched_cap() -> None:
    """The engine wrapper reads its module constant at call time (tests patch it)."""
    from unittest.mock import patch

    from app.engine.executor import _retry_delay

    with patch("app.engine.executor.MAX_RETRY_BACKOFF_S", 0.03):
        assert _retry_delay(0.05, 2) == 0.03
    assert _retry_delay(0.05, 2) == 0.1
