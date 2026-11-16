"""Preflight for MCP stdio sandbox deployment.

Validates the operator contract before enabling stdio MCP servers:

- production must use the Docker sandbox unless the explicit unsandboxed
  escape hatch is set;
- Docker mode requires a configured image/allowlist and a reachable Linux
  Docker daemon with the image already present;
- subprocess mode is reported as a development/escape-hatch configuration.

Run from the repository root:

    .venv\\Scripts\\python.exe scripts\\check_mcp_sandbox_deployment.py

Exit code 0 means the configured contract is internally consistent. It does
not pull images and it never prints credentials.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import get_settings
from app.tools.mcp.sandbox import (
    DockerSandboxConfig,
    docker_available,
)


def _run(argv: list[str], timeout: float = 8.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, (completed.stdout or completed.stderr or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, type(exc).__name__


def main() -> int:
    settings = get_settings()
    backend = str(settings.mcp_stdio_sandbox_backend or "subprocess").lower()
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, str] = {}

    checks["backend"] = backend
    checks["app_env"] = settings.app_env

    if settings.app_env == "production" and backend == "subprocess":
        if not settings.mcp_stdio_allow_unsandboxed:
            errors.append(
                "production stdio requires MCP_STDIO_SANDBOX_BACKEND=docker "
                "or the explicit MCP_STDIO_ALLOW_UNSANDBOXED=true escape hatch"
            )
        else:
            warnings.append(
                "production is using the unsandboxed subprocess escape hatch"
            )

    if backend == "docker":
        config = DockerSandboxConfig.from_settings(settings)
        checks["docker_executable"] = config.docker_executable
        checks["image"] = config.image or "(none)"
        checks["image_allowlist_count"] = str(len(config.allowed_images))
        checks["network"] = config.network

        if not config.image and not config.allowed_images:
            errors.append("Docker mode requires MCP_STDIO_DOCKER_IMAGE or an image allowlist")
        if not config.allowed_images:
            warnings.append(
                "MCP_STDIO_DOCKER_IMAGES is empty; only the global image is allowed"
            )
        if not config.require_digest:
            warnings.append(
                "MCP_STDIO_DOCKER_REQUIRE_DIGEST is false; production should pin @sha256 images"
            )
        if not config.allowed_networks or config.network not in config.allowed_networks:
            errors.append("configured Docker network is not in MCP_STDIO_DOCKER_NETWORKS")

        if not docker_available(config):
            errors.append(f"Docker CLI not found: {config.docker_executable}")
        else:
            code, output = _run(
                [config.docker_executable, "info", "--format", "{{.OSType}}"]
            )
            checks["docker_os"] = output if code == 0 else "unavailable"
            if code != 0:
                errors.append("Docker daemon is not reachable")
            elif output.strip().lower() != "linux":
                errors.append("MCP Docker sandbox requires a Linux container daemon")

            if config.image:
                code, _ = _run(
                    [config.docker_executable, "image", "inspect", config.image]
                )
                checks["image_present"] = "yes" if code == 0 else "no"
                if code != 0:
                    errors.append(
                        "configured MCP image is not present; pre-pull it before deployment"
                    )

        docker_host = str(getattr(settings, "docker_host", "") or "")
        if docker_host and (
            "docker.sock" in docker_host or "docker_engine" in docker_host
        ):
            warnings.append(
                "DOCKER_HOST points at the host socket; prefer a dedicated/rootless "
                "or remote sandbox daemon"
            )
    else:
        warnings.append(
            "subprocess mode is a development/escape-hatch configuration; "
            "it shares the host filesystem and network"
        )

    checks["docker_cli"] = "yes" if shutil.which(
        str(getattr(settings, "mcp_stdio_docker_executable", "docker") or "docker")
    ) else "no"

    print(
        json.dumps(
            {
                "status": "error" if errors else "ok",
                "checks": checks,
                "warnings": warnings,
                "errors": errors,
            },
            indent=2,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
