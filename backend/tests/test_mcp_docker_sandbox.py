"""Opt-in live Docker sandbox test for MCP stdio.

Skipped by default. Enable with:

    $env:FLOWSMITH_DOCKER_TESTS='true'
    $env:FLOWSMITH_MCP_DOCKER_TEST_IMAGE='python:3.12-slim'  # optional
    pytest -m docker tests/test_mcp_docker_sandbox.py -q

The image must already be present locally; the test never pulls images.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from app.tools.mcp.sandbox import DockerSandbox, DockerSandboxConfig
from app.tools.mcp.transport_stdio import StdioMCPClient
from tests.test_mcp_stdio import STDIO_SERVER

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("FLOWSMITH_DOCKER_TESTS", "").lower()
        not in ("1", "true", "yes"),
        reason="set FLOWSMITH_DOCKER_TESTS=true to run Docker sandbox tests",
    ),
]

IMAGE = os.environ.get("FLOWSMITH_MCP_DOCKER_TEST_IMAGE", "python:3.12-slim")


def _linux_docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.OSType}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "linux"


@pytest.mark.asyncio
async def test_docker_stdio_round_trip() -> None:
    if not _linux_docker_available():
        pytest.skip("Docker Linux daemon is not available")
    image = subprocess.run(
        ["docker", "image", "inspect", IMAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    if image.returncode != 0:
        pytest.skip(f"{IMAGE} is not present locally; pre-pull it first")

    config = DockerSandboxConfig(
        image=IMAGE,
        allowed_images=(IMAGE,),
        network="none",
        networks=("none",),
        require_digest=False,
        pull="never",
        workspace_mode="none",
    )
    sandbox = DockerSandbox(config, server_id="docker-round-trip")
    client = StdioMCPClient(
        ["python", "-u", "-c", f"exec({STDIO_SERVER!r})"],
        sandbox=sandbox,
        server_id="docker-round-trip",
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        await client.initialize()
        tools = await client.list_tools()
        assert any(tool.get("name") == "echo" for tool in tools)
        result = await client.call_tool("echo", {"text": "hello-docker"})
        assert "hello-docker" in json.dumps(result)
    finally:
        await client.close()
