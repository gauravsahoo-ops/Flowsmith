"""Docker-free tests for the MCP stdio sandbox seam.

These tests cover policy validation, Docker argv construction, production
gating, and the unchanged host-subprocess fallback. No test requires a Docker
daemon, so the default pass stays hermetic.
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.tools.mcp import sandbox as mcp_sandbox
from app.tools.mcp.client_factory import build_stdio_client
from app.tools.mcp.sandbox import (
    DockerSandboxConfig,
    SandboxError,
    SandboxPolicyError,
    SandboxSpec,
    SandboxUnavailable,
    SandboxValidationError,
    SubprocessSandbox,
    assert_stdio_sandbox_allowed,
    build_container_env,
    build_docker_run_argv,
    build_sandbox,
    build_subprocess_env,
    parse_container_command,
    remove_env_file,
    validate_container_user,
    validate_image,
    validate_network,
    validate_stdio_command,
    validate_workspace_path,
    write_env_file,
)
from app.tools.mcp.transport_stdio import (
    MCPTransportError,
    StdioMCPClient,
)

IMAGE = "ghcr.io/flowsmith/mcp-runtime@sha256:" + "a" * 64

STDIO_SERVER = r"""
import json
import sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    if request_id is None:
        continue
    if method == "initialize":
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "sandbox-test", "version": "1.0.0"},
            },
        }
    elif method == "ping":
        response = {"jsonrpc": "2.0", "id": request_id, "result": {}}
    elif method == "tools/list":
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                    }
                ]
            },
        }
    elif method == "tools/call":
        params = request.get("params") or {}
        text = (params.get("arguments") or {}).get("text", "")
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": str(text)}],
                "isError": False,
            },
        }
    else:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "method not found"},
        }
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
"""


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _docker_config(**overrides) -> DockerSandboxConfig:
    values = {
        "image": IMAGE,
        "images": (IMAGE,),
        "network": "none",
        "networks": ("none",),
        "user": "65534:65534",
        "cpus": 0.5,
        "tmpfs_mb": 16,
        "run_tmpfs_mb": 16,
        "shm_mb": 64,
        "workspace_tmpfs_mb": 32,
        "pull": "never",
        "startup_timeout_s": 5.0,
        "close_timeout_s": 5.0,
    }
    values.update(overrides)
    return DockerSandboxConfig(**values)


def _spec(**overrides) -> SandboxSpec:
    values = {
        "argv": ("python", "-m", "mcp_server"),
        "env": {"MCP_AUTH_TOKEN": "super-secret-token"},
        "server_id": "srv-1",
        "workspace_mode": "none",
    }
    values.update(overrides)
    return SandboxSpec(**values)


def _argv_with(spec: SandboxSpec, config: DockerSandboxConfig) -> list[str]:
    return build_docker_run_argv(
        spec,
        config,
        container_name="mcp-test",
        env_file="/tmp/mcp-test.env",
    )


def test_default_backend_is_subprocess_and_never_probes_docker(monkeypatch):
    settings = _settings()
    assert settings.mcp_stdio_sandbox_backend == "subprocess"
    monkeypatch.setattr(
        mcp_sandbox.shutil,
        "which",
        lambda *_args, **_kwargs: pytest.fail("docker must not be probed"),
    )
    sandbox = build_sandbox(settings)
    assert isinstance(sandbox, SubprocessSandbox)


def test_minimal_subprocess_env_excludes_worker_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:db-secret@db/app")
    monkeypatch.setenv("JWT_SECRET", "jwt-secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    child = build_subprocess_env({"MCP_AUTH_TOKEN": "resolved-token"})

    assert child["MCP_AUTH_TOKEN"] == "resolved-token"
    assert child["PATH"] == "/usr/bin"
    assert "DATABASE_URL" not in child
    assert "JWT_SECRET" not in child


def test_dangerous_environment_keys_are_rejected():
    for key in ("PYTHONPATH", "HTTP_PROXY", "LD_PRELOAD", "NODE_OPTIONS"):
        with pytest.raises(SandboxValidationError):
            build_subprocess_env({key: "value"})
        with pytest.raises(SandboxValidationError):
            build_container_env({key: "value"})

    with pytest.raises(SandboxValidationError):
        build_subprocess_env({"BAD KEY": "value"})
    with pytest.raises(SandboxValidationError):
        build_subprocess_env({"MCP_AUTH_TOKEN": "line\nbreak"})


def test_container_env_never_inherits_host_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:db-secret@db/app")
    child = build_container_env({"MCP_AUTH_TOKEN": "resolved-token"})
    assert child == {
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "MCP_AUTH_TOKEN": "resolved-token",
    }


def test_posix_command_parsing_works_on_windows():
    assert parse_container_command('python -m "my server" --flag') == [
        "python",
        "-m",
        "my server",
        "--flag",
    ]
    assert parse_container_command("python -c 'print(1)'") == [
        "python",
        "-c",
        "print(1)",
    ]
    assert parse_container_command(["python", "-m", "my server"]) == [
        "python",
        "-m",
        "my server",
    ]


@pytest.mark.parametrize(
    "command",
    [
        [],
        "",
        "   ",
        ["", "arg"],
        ["python", "bad\x00arg"],
        ["python", "bad\rarg"],
        ["python", "bad\narg"],
        ["-c", "python"],
    ],
)
def test_command_validation_rejects_invalid_commands(command):
    with pytest.raises(SandboxValidationError):
        validate_stdio_command(command)


def test_command_validation_rejects_too_many_and_too_long():
    with pytest.raises(SandboxValidationError):
        validate_stdio_command(["python"] + ["x"] * 64, max_args=2)
    with pytest.raises(SandboxValidationError):
        validate_stdio_command(["python", "x" * 20], max_arg_length=10)
    assert validate_stdio_command(["python", "-m", "server"]) == [
        "python",
        "-m",
        "server",
    ]


def test_image_allowlist_and_syntax():
    assert (
        validate_image(IMAGE, allowed_images=(IMAGE,), require_digest=True)
        == IMAGE
    )
    for bad in ("-image", " image", "image ", "image\nname", "img\tname", ""):
        with pytest.raises(SandboxValidationError):
            validate_image(bad)
    with pytest.raises(SandboxPolicyError):
        validate_image("ghcr.io/other/image:latest", allowed_images=(IMAGE,))
    with pytest.raises(SandboxPolicyError):
        validate_image("ghcr.io/flowsmith/mcp-runtime:latest", require_digest=True)


def test_network_defaults_to_none_and_rejects_host_modes():
    assert validate_network("") == "none"
    assert validate_network("none") == "none"
    for bad in ("host", "bridge", "default", "backend", "docker0", "container:abc"):
        with pytest.raises(SandboxPolicyError):
            validate_network(bad)
    with pytest.raises(SandboxPolicyError):
        validate_network("custom", allowed_networks=("none",))
    with pytest.raises(SandboxPolicyError):
        validate_network("host", allowed_networks=("host",))
    assert (
        validate_network("mcp-net", allowed_networks=("mcp-net",)) == "mcp-net"
    )


def test_config_accepts_alias_allowlists_and_config_network():
    config = DockerSandboxConfig(
        image=IMAGE,
        allowed_images=(IMAGE,),
        network="mcp-net",
        allowed_networks=("mcp-net",),
    )
    assert config.allowed_images == (IMAGE,)
    assert config.allowed_networks == ("mcp-net",)
    argv = _argv_with(_spec(network="none"), config)
    assert argv[argv.index("--network") + 1] == "mcp-net"


def test_non_root_user_enforcement():
    assert validate_container_user("65534:65534") == "65534:65534"
    assert validate_container_user("1000") == "1000"
    for bad in ("0", "0:0", "1000:0", "root", "65534:root", "-1", " 1000"):
        with pytest.raises(SandboxPolicyError):
            validate_container_user(bad)
    assert validate_container_user("0:0", allow_root=True) == "0:0"


def test_docker_argv_enforces_isolation_and_limits():
    argv = _argv_with(_spec(), _docker_config())

    assert argv[:2] == ["docker", "run"]
    for flag in ("--rm", "--init", "-i", "--read-only"):
        assert flag in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges:true"
    assert argv[argv.index("--user") + 1] == "65534:65534"
    assert argv[argv.index("--pids-limit") + 1] == "64"
    assert argv[argv.index("--memory") + 1] == "256m"
    assert argv[argv.index("--memory-swap") + 1] == "256m"
    assert argv[argv.index("--cpus") + 1] == "0.5"
    assert "--ulimit" in argv
    assert "cpu=60" in argv
    assert "nofile=256" in argv
    assert "core=0" in argv
    assert any(item.startswith("/tmp:") for item in argv)
    assert any(item.startswith("/run:") for item in argv)
    assert argv[argv.index("--pull") + 1] == "never"
    assert argv[argv.index("--shm-size") + 1] == "64m"
    assert argv[argv.index("--stop-timeout") + 1] == "2"
    assert argv[argv.index("--log-driver") + 1] == "none"
    assert argv[argv.index("--env-file") + 1] == "/tmp/mcp-test.env"
    assert argv[argv.index("--workdir") + 1] == "/tmp"
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[-3:] == ["python", "-m", "mcp_server"]
    assert argv[-4] == IMAGE
    assert "HOME=/tmp" in argv
    assert "TMPDIR=/tmp" in argv

    assert "--privileged" not in argv
    assert not any("docker.sock" in part for part in argv)
    assert "super-secret-token" not in " ".join(argv)
    assert all("super-secret-token" not in part for part in argv)


def test_configured_container_name_and_labels():
    argv = _argv_with(_spec(server_id="server-abc"), _docker_config())
    assert argv[argv.index("--name") + 1] == "mcp-test"
    assert "flowsmith.mcp.server=server-abc" in argv
    assert "flowsmith.mcp.server_id=server-abc" in argv
    assert "flowsmith.mcp.sandbox=true" in argv
    assert any(part.startswith("flowsmith.mcp.created=") for part in argv)
    with pytest.raises(SandboxValidationError):
        build_docker_run_argv(
            _spec(),
            _docker_config(),
            container_name="-bad",
            env_file="/tmp/x.env",
        )


def test_env_file_is_private_and_contains_no_extra_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:db-secret@db/app")
    path = write_env_file(
        build_container_env({"MCP_AUTH_TOKEN": "super-secret-token"})
    )
    try:
        content = Path(path).read_text(encoding="utf-8")
        assert "MCP_AUTH_TOKEN=super-secret-token" in content
        assert "DATABASE_URL" not in content
        assert "db-secret" not in content
        if os.name != "nt":
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    finally:
        remove_env_file(path)
    assert not Path(path).exists()


def test_repr_redacts_env_cwd_argv_and_workspace():
    spec = SandboxSpec(
        argv=("python", "--token", "super-secret-token"),
        env={"MCP_AUTH_TOKEN": "super-secret-token"},
        cwd="/home/user/super-secret-token",
        workspace="/home/user/super-secret-token/workspace",
    )
    rendered = repr(spec)
    assert "super-secret-token" not in rendered
    assert "MCP_AUTH_TOKEN" not in rendered
    assert "argv=<3 args>" in rendered
    assert "env=<1 vars>" in rendered
    assert "cwd=<redacted>" in rendered
    assert "workspace=<redacted>" in rendered


def test_ephemeral_workspace_uses_tmpfs(tmp_path):
    config = _docker_config(workspace_mode="ephemeral")
    argv = _argv_with(
        _spec(workspace_mode="ephemeral", workspace_read_only=False), config
    )
    workspace_tmpfs = [
        item for item in argv if item.startswith("/workspace:")
    ]
    assert len(workspace_tmpfs) == 1
    assert "size=32m" in workspace_tmpfs[0]
    assert argv[argv.index("--workdir") + 1] == "/workspace"
    assert "--mount" not in argv


def test_configured_workspace_is_a_read_only_bind(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _docker_config(
        workspace_mode="configured", workspace_root=str(tmp_path)
    )
    argv = _argv_with(
        _spec(workspace_mode="configured", workspace=str(workspace)), config
    )
    mount = argv[argv.index("--mount") + 1]
    assert f"source={workspace.resolve()}" in mount
    assert "target=/workspace" in mount
    assert "readonly" in mount
    assert argv[argv.index("--workdir") + 1] == "/workspace"
    assert not any(item.startswith("/workspace:") for item in argv)


def test_inherit_workspace_mode_is_none_in_docker():
    argv = _argv_with(
        _spec(workspace_mode="inherit"),
        _docker_config(workspace_mode="none"),
    )
    assert "--mount" not in argv
    assert not any(item.startswith("/workspace:") for item in argv)
    assert argv[argv.index("--workdir") + 1] == "/tmp"


def test_workspace_path_rejects_roots_home_and_outside_root(tmp_path):
    with pytest.raises(SandboxPolicyError):
        validate_workspace_path(os.path.abspath(os.sep))
    with pytest.raises(SandboxPolicyError):
        validate_workspace_path(str(Path.home()))
    with pytest.raises(SandboxValidationError):
        validate_workspace_path("relative/workspace")
    with pytest.raises(SandboxPolicyError):
        validate_workspace_path(
            str(tmp_path / "workspace"), workspace_root=str(tmp_path / "other")
        )


def test_production_subprocess_gate_fails_closed():
    with pytest.raises(SandboxPolicyError) as excinfo:
        assert_stdio_sandbox_allowed(_settings(app_env="production"))
    assert excinfo.value.code == "MCP_SANDBOX_REQUIRED"

    assert_stdio_sandbox_allowed(_settings(app_env="development"))
    assert_stdio_sandbox_allowed(
        _settings(
            app_env="production",
            mcp_stdio_allow_unsandboxed=True,
        )
    )
    assert_stdio_sandbox_allowed(
        _settings(app_env="production", mcp_stdio_sandbox_backend="docker")
    )


def test_docker_backend_fails_closed_when_cli_is_unavailable(monkeypatch):
    monkeypatch.setattr(mcp_sandbox.shutil, "which", lambda *_args: None)
    settings = _settings(
        mcp_stdio_sandbox_backend="docker",
        mcp_stdio_docker_image=IMAGE,
        mcp_stdio_docker_images=IMAGE,
    )
    with pytest.raises(SandboxUnavailable):
        build_sandbox(settings)

    # A fallback requires both explicit switches.
    explicit_fallback = _settings(
        mcp_stdio_sandbox_backend="docker",
        mcp_stdio_docker_image=IMAGE,
        mcp_stdio_docker_images=IMAGE,
        mcp_stdio_sandbox_fallback="subprocess",
        mcp_stdio_allow_unsandboxed=True,
    )
    assert isinstance(build_sandbox(explicit_fallback), SubprocessSandbox)

    partial_fallback = _settings(
        mcp_stdio_sandbox_backend="docker",
        mcp_stdio_docker_image=IMAGE,
        mcp_stdio_docker_images=IMAGE,
        mcp_stdio_sandbox_fallback="subprocess",
        mcp_stdio_allow_unsandboxed=False,
    )
    with pytest.raises(SandboxUnavailable):
        build_sandbox(partial_fallback)


def test_docker_backend_requires_allowlisted_image():
    settings = _settings(
        mcp_stdio_sandbox_backend="docker",
        mcp_stdio_docker_image=IMAGE,
        mcp_stdio_docker_images=IMAGE,
    )
    with pytest.raises(SandboxPolicyError):
        build_sandbox(
            settings,
            image="ghcr.io/other/image:latest",
        )


def test_subprocess_sandbox_round_trip():
    async def scenario() -> None:
        client = StdioMCPClient(
            [sys.executable, "-c", STDIO_SERVER],
            timeout_s=10.0,
            sandbox=SubprocessSandbox(),
            server_id="srv-subprocess",
        )
        try:
            assert await client.ping() is True
            tools = await client.list_tools(timeout_s=10.0)
            assert [tool["name"] for tool in tools] == ["echo"]
            result = await client.call_tool(
                "echo", {"text": "hello"}, timeout_s=10.0
            )
            assert result["content"] == "hello"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_subprocess_timeout_still_kills_child():
    script = "import time; time.sleep(30)"

    async def scenario() -> None:
        client = StdioMCPClient(
            [sys.executable, "-c", script],
            timeout_s=0.25,
            sandbox=SubprocessSandbox(),
        )
        try:
            with pytest.raises(TimeoutError):
                await client.list_tools(timeout_s=0.25)
        finally:
            await client.close()

    asyncio.run(scenario())


def test_transport_wraps_sandbox_errors_without_argv_or_env():
    class FailingSandbox:
        name = "failing"

        async def start(self, spec):
            raise SandboxError("sandbox failed")

    client = StdioMCPClient(
        ["python", "--argv-secret"],
        env={"MCP_AUTH_TOKEN": "env-secret"},
        sandbox=FailingSandbox(),
    )

    async def scenario() -> None:
        with pytest.raises(MCPTransportError) as excinfo:
            await client.list_tools(timeout_s=1.0)
        message = str(excinfo.value)
        assert "MCP_SANDBOX_ERROR" in message
        assert "argv-secret" not in message
        assert "env-secret" not in message
        await client.close()

    asyncio.run(scenario())


def _stdio_server(**overrides) -> SimpleNamespace:
    values = {
        "id": "srv-factory",
        "endpoint": "python -m mcp_server",
        "transport": "stdio",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_factory_defaults_to_global_subprocess_and_never_probes_docker(monkeypatch):
    monkeypatch.setattr(
        mcp_sandbox.shutil,
        "which",
        lambda *_args, **_kwargs: pytest.fail("docker must not be probed"),
    )
    client = build_stdio_client(_stdio_server(), settings=_settings())
    assert client._sandbox.name == "subprocess"


def test_factory_uses_per_server_docker_config(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_sandbox.shutil, "which", lambda *_args: "docker")
    server = _stdio_server(
        sandbox_backend="docker",
        sandbox_image=IMAGE,
        sandbox_workspace_mode="configured",
        sandbox_workspace_path=str(tmp_path),
        sandbox_network="none",
        sandbox_read_only=True,
    )
    client = build_stdio_client(server, settings=_settings())
    sandbox = client._sandbox
    assert sandbox.name == "docker"

    spec = client._sandbox_spec()
    assert spec.image == IMAGE
    assert spec.workspace_mode == "configured"
    assert spec.workspace == str(tmp_path)
    assert spec.workspace_read_only is True
    argv = sandbox.build_docker_run_argv(
        spec, env_file="/tmp/mcp-test.env"
    )
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--workdir") + 1] == "/workspace"
    mount = argv[argv.index("--mount") + 1]
    assert f"source={tmp_path.resolve()}" in mount
    assert "readonly" in mount
    assert IMAGE in argv


def test_factory_uses_per_server_ephemeral_read_only_workspace(monkeypatch):
    monkeypatch.setattr(mcp_sandbox.shutil, "which", lambda *_args: "docker")
    server = _stdio_server(
        sandbox_backend="docker",
        sandbox_image=IMAGE,
        sandbox_workspace_mode="ephemeral",
        sandbox_read_only=True,
    )
    client = build_stdio_client(server, settings=_settings())
    argv = client._sandbox.build_docker_run_argv(
        client._sandbox_spec(), env_file="/tmp/mcp-test.env"
    )
    workspace_tmpfs = [
        item for item in argv if item.startswith("/workspace:")
    ]
    assert len(workspace_tmpfs) == 1
    assert ":ro," in workspace_tmpfs[0]
    assert argv[argv.index("--workdir") + 1] == "/workspace"


def test_factory_falls_back_to_global_docker_settings(monkeypatch):
    monkeypatch.setattr(mcp_sandbox.shutil, "which", lambda *_args: "docker")
    settings = _settings(
        mcp_stdio_sandbox_backend="docker",
        mcp_stdio_docker_image=IMAGE,
        mcp_stdio_docker_images=IMAGE,
    )
    client = build_stdio_client(_stdio_server(), settings=settings)
    assert client._sandbox.name == "docker"
    assert client._sandbox_spec().image == ""


def test_production_gate_uses_effective_per_server_backend():
    settings = _settings(
        app_env="production",
        mcp_stdio_sandbox_backend="docker",
        mcp_stdio_docker_image=IMAGE,
        mcp_stdio_docker_images=IMAGE,
    )
    server = _stdio_server(sandbox_backend="subprocess")
    with pytest.raises(SandboxPolicyError) as excinfo:
        build_stdio_client(server, settings=settings)
    assert excinfo.value.code == "MCP_SANDBOX_REQUIRED"
