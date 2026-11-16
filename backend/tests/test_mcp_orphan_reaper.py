"""Docker-free tests for the MCP orphan-container reaper.

Every test injects a fake launcher, so the default pass never needs a Docker
daemon or CLI. The maintenance-loop tests use fakes as well.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

import pytest

from app.config import Settings
from app.maintenance import MaintenanceDaemon
from app.tools.mcp import orphan_reaper
from app.tools.mcp.orphan_reaper import (
    DEFAULT_ORPHAN_TTL_S,
    reap_mcp_orphans,
    reap_orphaned_containers,
)

NOW = 1_800_000_000.0
OLD_ID = "a" * 12
FRESH_ID = "b" * 12
EDGE_ID = "c" * 12


def _settings(**overrides) -> Settings:
    values = {
        "mcp_stdio_sandbox_backend": "docker",
        "mcp_stdio_docker_executable": "docker",
        "mcp_stdio_docker_orphan_ttl_s": DEFAULT_ORPHAN_TTL_S,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class RecordingLauncher:
    """Callable launcher recording every argv list it receives."""

    def __init__(
        self,
        *,
        ps_output: str = "",
        ps_code: int = 0,
        ps_error: BaseException | None = None,
        rm_codes: list[int] | None = None,
    ) -> None:
        self.ps_output = ps_output
        self.ps_code = ps_code
        self.ps_error = ps_error
        self.rm_codes = list(rm_codes or [])
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        if argv[1] == "ps":
            if self.ps_error is not None:
                raise self.ps_error
            return self.ps_code, self.ps_output
        assert argv[1] == "rm"
        return (self.rm_codes.pop(0) if self.rm_codes else 0), ""


def _rm_calls(launcher: RecordingLauncher) -> list[list[str]]:
    return [call for call in launcher.calls if call[1] == "rm"]


def test_removes_only_containers_older_than_ttl() -> None:
    older = "d" * 12
    launcher = RecordingLauncher(
        ps_output="\n".join(
            [
                f"{OLD_ID}|{int(NOW - 7200)}",
                f"{FRESH_ID}|{int(NOW - 60)}",
                # Exactly at the TTL boundary is not "older than TTL".
                f"{EDGE_ID}|{int(NOW - 3600)}",
                f"{older}|{int(NOW - 3601)}",
            ]
        )
    )

    removed = reap_orphaned_containers(
        settings=_settings(), launcher=launcher, now=NOW
    )

    assert removed == 2
    assert [call[-1] for call in _rm_calls(launcher)] == [OLD_ID, older]
    # Every Docker invocation is an argv list (never a shell string).
    assert all(isinstance(call, list) for call in launcher.calls)
    assert all(call[0] == "docker" for call in launcher.calls)


def test_ttl_override_changes_the_cutoff() -> None:
    launcher = RecordingLauncher(
        ps_output=f"{OLD_ID}|{int(NOW - 120)}"
    )

    removed = reap_orphaned_containers(
        settings=_settings(), launcher=launcher, now=NOW, ttl_s=60
    )

    assert removed == 1
    assert _rm_calls(launcher)[0][-1] == OLD_ID


def test_skips_malformed_and_missing_created_labels() -> None:
    malformed_id = "z" * 12
    good_id = "e" * 12
    launcher = RecordingLauncher(
        ps_output="\n".join(
            [
                f"{OLD_ID}|not-a-number",
                f"{FRESH_ID}|",  # missing label
                f"{malformed_id}",  # no separator at all
                f"not-an-id|{int(NOW - 7200)}",
                f"{EDGE_ID}|nan",
                f"{'f' * 12}|-5",
                "",
                f"{good_id}|{int(NOW - 9000)}",
            ]
        )
    )

    removed = reap_orphaned_containers(
        settings=_settings(), launcher=launcher, now=NOW
    )

    assert removed == 1
    assert [call[-1] for call in _rm_calls(launcher)] == [good_id]


def test_noop_when_backend_is_not_configured() -> None:
    calls: list[list[str]] = []

    def launcher(argv: list[str]) -> tuple[int, str]:
        calls.append(argv)
        return 0, f"{OLD_ID}|{int(NOW - 7200)}"

    removed = reap_orphaned_containers(
        settings=Settings(_env_file=None), launcher=launcher, now=NOW
    )

    assert removed == 0
    assert calls == []


def test_noop_when_docker_cli_is_missing() -> None:
    launcher = RecordingLauncher(ps_error=FileNotFoundError("docker"))

    assert (
        reap_orphaned_containers(
            settings=_settings(), launcher=launcher, now=NOW
        )
        == 0
    )
    assert [call[1] for call in launcher.calls] == ["ps"]


def test_noop_on_docker_timeout() -> None:
    launcher = RecordingLauncher(
        ps_error=subprocess.TimeoutExpired(["docker", "ps"], 10)
    )

    assert (
        reap_orphaned_containers(
            settings=_settings(), launcher=launcher, now=NOW
        )
        == 0
    )
    assert _rm_calls(launcher) == []


def test_noop_on_nonzero_docker_ps() -> None:
    launcher = RecordingLauncher(
        ps_code=1, ps_output=f"{OLD_ID}|{int(NOW - 7200)}"
    )

    assert (
        reap_orphaned_containers(
            settings=_settings(), launcher=launcher, now=NOW
        )
        == 0
    )
    assert _rm_calls(launcher) == []


def test_rm_failure_does_not_abort_the_sweep() -> None:
    ids = ["1" * 12, "2" * 12, "3" * 12]
    launcher = RecordingLauncher(
        ps_output="\n".join(f"{container_id}|{int(NOW - 7200)}" for container_id in ids),
        rm_codes=[1, 0, 1],
    )

    removed = reap_orphaned_containers(
        settings=_settings(), launcher=launcher, now=NOW
    )

    # Only the successful rm counts, but the failed ones do not stop the sweep.
    assert removed == 1
    assert [call[-1] for call in _rm_calls(launcher)] == ids


def test_launcher_object_with_run_method_is_supported() -> None:
    class RunLauncher:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, argv: list[str]) -> tuple[int, str]:
            self.calls.append(list(argv))
            if argv[1] == "ps":
                return 0, f"{OLD_ID}|{int(NOW - 7200)}"
            return 0, ""

    launcher = RunLauncher()

    removed = reap_orphaned_containers(
        settings=_settings(), launcher=launcher, now=NOW
    )

    assert removed == 1
    assert [call[1] for call in launcher.calls] == ["ps", "rm"]


def test_default_launcher_never_uses_a_shell(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs

        class Result:
            returncode = 0
            stdout = ""

        return Result()

    monkeypatch.setattr(orphan_reaper.subprocess, "run", fake_run)

    removed = reap_orphaned_containers(
        settings=_settings(mcp_stdio_docker_executable=sys.executable),
        now=NOW,
    )

    assert removed == 0
    argv = captured["argv"]
    kwargs = captured["kwargs"]
    assert isinstance(argv, list)
    assert argv[:2] == [sys.executable, "ps"]
    assert "label=flowsmith.mcp.sandbox=true" in argv
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == orphan_reaper.DEFAULT_COMMAND_TIMEOUT_S


def test_reap_mcp_orphans_is_fail_open(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(orphan_reaper, "reap_orphaned_containers", boom)

    assert reap_mcp_orphans() == 0


def test_config_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.mcp_stdio_docker_orphan_ttl_s == 3600
    assert settings.mcp_stdio_docker_orphan_ttl_s == DEFAULT_ORPHAN_TTL_S
    assert settings.mcp_stdio_docker_orphan_sweep_interval_s == 300


async def test_maintenance_loop_reaps_after_renewal(monkeypatch, caplog) -> None:
    daemon = MaintenanceDaemon()
    events: list[str] = []

    async def fake_renew() -> dict[str, int]:
        events.append("renew")
        return {"checked": 1, "refreshed": 0, "skipped": 1, "failed": 0}

    async def fake_to_thread(func):
        events.append("reap")
        assert func is reap_mcp_orphans
        return 1

    async def fake_sleep(_: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(daemon, "renew_credentials", fake_renew)
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with caplog.at_level(logging.INFO, logger="maintenance"):
        with pytest.raises(asyncio.CancelledError):
            await daemon._cred_renewal_loop()

    assert events == ["renew", "reap"]
    assert "removed 1 orphaned MCP container(s)" in caplog.text


async def test_maintenance_loop_sweeps_when_renewal_fails(monkeypatch) -> None:
    daemon = MaintenanceDaemon()
    events: list[str] = []

    async def fake_renew() -> dict[str, int]:
        events.append("renew")
        raise RuntimeError("renewal down")

    async def fake_to_thread(func):
        events.append("reap")
        return 0

    async def fake_sleep(_: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(daemon, "renew_credentials", fake_renew)
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await daemon._cred_renewal_loop()

    # Renewal failure is isolated: the sweep still runs.
    assert events == ["renew", "reap"]
