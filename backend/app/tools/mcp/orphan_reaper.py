"""Bounded, best-effort reaper for orphaned MCP Docker sandbox containers.

Containers started by :mod:`app.tools.mcp.sandbox` carry the labels
``flowsmith.mcp.sandbox=true``, ``flowsmith.mcp.server=<id>``, and
``flowsmith.mcp.created=<epoch seconds>``. ``docker run --rm`` normally
removes the container when the stdio session ends, but an API/worker crash can
leave it running (and the container keeps consuming its limits).

This module is intentionally fail-open: a missing Docker CLI, an unreachable
daemon, a timeout, or a malformed ``docker ps`` line never raises out of the
maintenance loop. Only containers that carry the sandbox label *and* an
unparseable-free creation timestamp older than the TTL are removed. Docker is
always invoked with an argv list; no shell is ever involved.
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol, cast

from app.config import get_settings

logger = logging.getLogger("tools.mcp.orphan_reaper")

DEFAULT_ORPHAN_TTL_S = 3600

# Hard bounds for one sweep: Docker commands have a per-call timeout and one
# sweep never removes more than this many containers. The label filter keeps
# the candidate set small in practice; the cap protects the maintenance thread
# from a pathological daemon response.
DEFAULT_COMMAND_TIMEOUT_S = 10.0
MAX_CONTAINERS_PER_SWEEP = 200

SANDBOX_LABEL = "flowsmith.mcp.sandbox=true"
CREATED_LABEL = "flowsmith.mcp.created"
_PS_FORMAT = '{{.ID}}|{{.Label "' + CREATED_LABEL + '"}}'
_CONTAINER_ID_RE = re.compile(r"^[0-9a-fA-F]{12,64}$")


class DockerRunner(Protocol):
    """Adapts Docker invocation for tests (an object with ``run``)."""

    def run(self, argv: list[str]) -> tuple[int, str]: ...


Launcher = Callable[[list[str]], tuple[int, str]] | DockerRunner


def _docker_executable(settings: Any) -> str:
    raw = str(getattr(settings, "mcp_stdio_docker_executable", "docker") or "docker")
    return raw.strip()


def _executable_available(executable: str) -> bool:
    """Return True when the configured Docker CLI appears to exist."""
    if not executable or executable.startswith("-"):
        return False
    if os.path.dirname(executable):
        return Path(executable).is_file()
    return shutil.which(executable) is not None


def _run_docker(argv: list[str]) -> tuple[int, str]:
    """Default launcher: a bounded subprocess with an explicit argv list."""
    completed = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=DEFAULT_COMMAND_TIMEOUT_S,
        check=False,
        # Explicit even though it is the default: argv must never be handed
        # to a shell for interpretation.
        shell=False,
    )
    return int(completed.returncode), completed.stdout or ""


def _invoke(launcher: Launcher, argv: list[str]) -> tuple[int, str]:
    if callable(launcher):
        result = cast(Callable[[list[str]], tuple[int, str]], launcher)(argv)
    else:
        result = cast(DockerRunner, launcher).run(argv)
    returncode, stdout = result
    return int(returncode), str(stdout or "")


def _parse_ttl(value: Any, default: int) -> int:
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, ttl)


def _ttl_from_settings(settings: Any, ttl_s: int | float | None) -> int:
    if ttl_s is not None:
        return _parse_ttl(ttl_s, DEFAULT_ORPHAN_TTL_S)
    return _parse_ttl(
        getattr(settings, "mcp_stdio_docker_orphan_ttl_s", DEFAULT_ORPHAN_TTL_S),
        DEFAULT_ORPHAN_TTL_S,
    )


def _iter_containers(output: str) -> Iterator[tuple[str, float]]:
    """Yield ``(container_id, created_epoch_s)`` from ``docker ps`` output.

    Malformed IDs, missing/non-numeric creation labels, and non-finite or
    non-positive timestamps are skipped rather than guessed at.
    """
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or "|" not in line:
            continue
        container_id, raw_created = line.split("|", 1)
        container_id = container_id.strip()
        raw_created = raw_created.strip()
        if not _CONTAINER_ID_RE.fullmatch(container_id) or not raw_created:
            continue
        try:
            created = float(raw_created)
        except ValueError:
            continue
        if not math.isfinite(created) or created <= 0:
            continue
        yield container_id, created


def _short_id(container_id: str) -> str:
    return container_id[:12]


def reap_orphaned_containers(
    *,
    settings: Any | None = None,
    launcher: Launcher | None = None,
    now: float | None = None,
    ttl_s: int | float | None = None,
) -> int:
    """Remove stale labeled MCP sandbox containers and return the count.

    A sweep is a no-op (returning 0) unless the Docker stdio backend is
    configured and available. ``launcher`` is an injectable I/O seam for
    tests: a callable accepting an argv list or an object exposing
    ``run(argv) -> (returncode, stdout)``. The default launcher uses
    :mod:`subprocess` with an argv list, never a shell.

    Failures are logged by type/count only (never full argv, env, or token
    material) and never propagate to the caller.
    """
    effective_settings = settings if settings is not None else get_settings()
    backend = str(
        getattr(effective_settings, "mcp_stdio_sandbox_backend", "subprocess")
        or "subprocess"
    ).strip().lower()
    if backend != "docker":
        logger.debug("MCP orphan sweep skipped: Docker backend is not configured")
        return 0

    executable = _docker_executable(effective_settings)
    if launcher is None and not _executable_available(executable):
        logger.debug("MCP orphan sweep skipped: Docker CLI is unavailable")
        return 0

    runner: Launcher = launcher if launcher is not None else _run_docker
    ttl = _ttl_from_settings(effective_settings, ttl_s)
    try:
        current = time.time() if now is None else float(now)
    except (TypeError, ValueError):
        current = time.time()

    ps_argv = [
        executable,
        "ps",
        "-a",
        "--filter",
        f"label={SANDBOX_LABEL}",
        "--format",
        _PS_FORMAT,
    ]
    try:
        returncode, output = _invoke(runner, ps_argv)
    except (OSError, subprocess.SubprocessError, TimeoutError, ValueError) as exc:
        logger.warning(
            "MCP orphan sweep skipped: Docker unavailable (%s)",
            type(exc).__name__,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - fail-open by design
        logger.warning(
            "MCP orphan sweep skipped: launcher error (%s)",
            type(exc).__name__,
        )
        return 0
    if returncode != 0:
        logger.warning(
            "MCP orphan sweep skipped: docker ps exited %s", returncode
        )
        return 0

    removed = 0
    candidates = 0
    for container_id, created in _iter_containers(output):
        if current - created <= ttl:
            continue
        if candidates >= MAX_CONTAINERS_PER_SWEEP:
            logger.warning(
                "MCP orphan sweep reached the per-sweep limit (%d)",
                MAX_CONTAINERS_PER_SWEEP,
            )
            break
        candidates += 1
        rm_argv = [executable, "rm", "-f", container_id]
        try:
            rm_code, _ = _invoke(runner, rm_argv)
        except (OSError, subprocess.SubprocessError, TimeoutError, ValueError) as exc:
            logger.warning(
                "MCP orphan removal failed for %s (%s)",
                _short_id(container_id),
                type(exc).__name__,
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one failure must not abort
            logger.warning(
                "MCP orphan removal failed for %s (%s)",
                _short_id(container_id),
                type(exc).__name__,
            )
            continue
        if rm_code == 0:
            removed += 1
        else:
            logger.warning(
                "MCP orphan removal failed for %s (docker rm exited %s)",
                _short_id(container_id),
                rm_code,
            )

    if removed:
        logger.info(
            "MCP orphan sweep removed %d stale container(s)", removed
        )
    return removed


def reap_mcp_orphans() -> int:
    """Convenience entry point for the maintenance loop."""
    try:
        return reap_orphaned_containers(settings=get_settings())
    except Exception as exc:  # noqa: BLE001 - never break maintenance
        logger.warning(
            "MCP orphan sweep failed (%s)", type(exc).__name__
        )
        return 0
