"""Retry-delay hardening tests (untrusted Retry-After values)."""

from __future__ import annotations

import math

import pytest

from app.engine.executor import MAX_RETRY_BACKOFF_S, _retry_delay


def test_exponential_backoff_is_used_without_retry_after():
    assert _retry_delay(2.0, 1) == 2.0
    assert _retry_delay(2.0, 2) == 4.0
    assert _retry_delay(2.0, 3) == 8.0


def test_retry_after_is_honoured_and_bounded():
    assert _retry_delay(2.0, 1, 7.5) == 7.5
    assert _retry_delay(2.0, 1, 10_000) == MAX_RETRY_BACKOFF_S
    assert _retry_delay(2.0, 1, 0) == 0.0


@pytest.mark.parametrize("retry_after", [-5, float("nan"), float("inf"), "not-a-number", None])
def test_invalid_retry_after_falls_back_to_exponential(retry_after):
    assert _retry_delay(2.0, 2, retry_after) == 4.0


def test_backoff_is_always_finite():
    assert math.isfinite(_retry_delay(float("nan"), 2))
    assert 0.0 <= _retry_delay(-10.0, 2) <= MAX_RETRY_BACKOFF_S
