"""Redis-backed login throttle (Phase 38).

Unit tests use fakeredis so multi-instance semantics are verified
without infrastructure. The memory throttle contract (is_locked /
retry_after / record_failure / clear) must hold identically.
"""

from __future__ import annotations

import fakeredis
import pytest

from app.security.ratelimit import RedisFailureThrottle


@pytest.fixture
def throttle():
    return RedisFailureThrottle(fakeredis.FakeStrictRedis(), max_failures=3, window_s=60, lockout_s=120)


def test_not_locked_initially(throttle):
    assert throttle.is_locked("k") is False
    assert throttle.retry_after("k") == 0


def test_locks_after_max_failures(throttle):
    for _ in range(3):
        throttle.record_failure("k")
    assert throttle.is_locked("k") is True
    assert throttle.retry_after("k") > 0


def test_below_threshold_not_locked(throttle):
    for _ in range(2):
        throttle.record_failure("k")
    assert throttle.is_locked("k") is False


def test_clear_unlocks(throttle):
    for _ in range(3):
        throttle.record_failure("k")
    assert throttle.is_locked("k")
    throttle.clear("k")
    assert throttle.is_locked("k") is False
    assert throttle.retry_after("k") == 0


def test_keys_are_isolated(throttle):
    for _ in range(3):
        throttle.record_failure("user-a")
    assert throttle.is_locked("user-a") is True
    assert throttle.is_locked("user-b") is False


def test_reset_clears_everything(throttle):
    throttle.record_failure("a")
    throttle.record_failure("b")
    throttle.reset()
    assert throttle.is_locked("a") is False
    assert throttle.is_locked("b") is False


def test_factory_returns_redis_backed_when_configured(monkeypatch):
    import fakeredis

    from app.security import ratelimit as rl

    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(rl, "get_shared_redis", lambda: fake)
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: __import__("types").SimpleNamespace(
            login_max_attempts=5, login_window_seconds=300, login_lockout_seconds=300, redis_url="redis://x"
        ),
    )
    t = rl.get_login_throttle()
    assert isinstance(t, rl.RedisFailureThrottle)


def test_factory_returns_memory_without_redis(monkeypatch):
    from app.security import ratelimit as rl

    monkeypatch.setattr(rl, "get_shared_redis", lambda: None)
    t = rl.get_login_throttle()
    assert isinstance(t, rl.FailureThrottle)
