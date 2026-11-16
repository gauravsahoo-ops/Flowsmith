"""Sandbox seam for MCP stdio servers.

The default backend preserves the historical behavior: a direct child process
with a minimized environment and POSIX resource limits. An opt-in Docker
backend runs the same command inside a locked-down, networkless container.
Docker is never selected implicitly and never silently falls back to a host
process.

Security invariants enforced here:

- environment values, argv, and secrets are never logged or included in
  error messages;
- child environments are minimized and dangerous interpreter/proxy variables
  are rejected when supplied explicitly;
- container images and networks must be allowlisted, containers run as a
  non-root user, and the root filesystem is read-only;
- workspace mounts are limited to safe, non-system directories and are
  read-only for host binds.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import shlex
import shutil
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("tools.mcp.sandbox")

DEFAULT_STREAM_LIMIT_BYTES = 8 * 1024 * 1024
_DIAGNOSTIC_LIMIT_BYTES = 4096
_CONTAINER_WORKSPACE = "/workspace"
_CONTAINER_TMP = "/tmp"
_CONTAINER_RUN = "/run"

# Only these variables are inherited by a host subprocess by default. This is
# the same allowlist the stdio transport has always used.
SUBPROCESS_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "HOME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
)

# Variables that can inject code into an interpreter, hijack library
# resolution, or redirect traffic through an unintended proxy. They are
# rejected when supplied explicitly through a sandbox spec.
DANGEROUS_ENV_KEYS = frozenset(
    {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
        "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
        "PERL5LIB",
        "PERL5OPT",
        "PERLLIB",
        "PERL_UNICODE",
        "RUBYLIB",
        "RUBYOPT",
        "NODE_OPTIONS",
        "NODE_PATH",
        "JAVA_TOOL_OPTIONS",
        "_JAVA_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "DYLD_FRAMEWORK_PATH",
        "BASH_ENV",
        "ENV",
        "SHELLOPTS",
        "BASHOPTS",
        "PS4",
        "PROMPT_COMMAND",
        "GCONV_PATH",
        "GLIBC_TUNABLES",
        "MALLOC_CONF",
        "LOCALDOMAIN",
        "RES_OPTIONS",
        "HOSTALIASES",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "FTP_PROXY",
        "SOCKS_PROXY",
    }
)

FORBIDDEN_NETWORKS = frozenset({"host", "bridge", "default", "backend", "docker0"})
_ALLOWED_PULL_MODES = frozenset({"never", "missing"})
SANDBOX_BACKENDS = frozenset({"subprocess", "docker"})
SANDBOX_WORKSPACE_MODES = frozenset(
    {"none", "ephemeral", "configured", "inherit"}
)
_WORKSPACE_MODES = SANDBOX_WORKSPACE_MODES
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_USER_RE = re.compile(r"^(?P<uid>\d+)(?::(?P<gid>\d+))?$")
_DIGEST_RE = re.compile(r"@sha256:[0-9a-fA-F]{64}$")
_CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

_SECRET_PATTERN = re.compile(
    r"(?i)([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|"
    r"AUTHORIZATION|CREDENTIAL)[A-Z0-9_]*)\s*[=:]\s*([^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}")


class SandboxError(RuntimeError):
    """Base class for MCP sandbox failures with a stable machine code."""

    code = "MCP_SANDBOX_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class SandboxValidationError(SandboxError):
    """A sandbox command, environment, or configuration is invalid."""

    code = "MCP_SANDBOX_INVALID"


class SandboxPolicyError(SandboxError):
    """A sandbox request violates an explicit security policy."""

    code = "MCP_SANDBOX_POLICY"


class SandboxUnavailable(SandboxError):
    """The selected sandbox backend cannot be started on this host."""

    code = "MCP_SANDBOX_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """Resource limits applied to a sandboxed stdio server."""

    memory_mb: int = 256
    cpu_seconds: int = 60
    pids: int = 64
    nofile: int = 256
    fsize_mb: int = 64


@dataclass(frozen=True)
class SandboxSpec:
    """One sandbox start request.

    ``env`` and ``cwd`` are excluded from ``repr`` and never appear in error
    messages. Argv is represented only by its length for the same reason:
    command arguments can legitimately carry credentials.
    """

    argv: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict, repr=False)
    cwd: str | None = field(default=None, repr=False)
    limits: SandboxLimits = field(default_factory=SandboxLimits)
    workspace_mode: str = "none"
    workspace: str | None = field(default=None, repr=False)
    workspace_read_only: bool = False
    server_id: str = ""
    image: str = ""
    network: str = "none"
    stream_limit_bytes: int = DEFAULT_STREAM_LIMIT_BYTES

    def __post_init__(self) -> None:
        raw_argv = self.argv
        if isinstance(raw_argv, str):
            object.__setattr__(
                self, "argv", tuple(parse_container_command(raw_argv))
            )
        else:
            object.__setattr__(
                self, "argv", tuple(str(part) for part in raw_argv)
            )
        object.__setattr__(
            self,
            "env",
            {
                str(key): str(value)
                for key, value in dict(self.env or {}).items()
            },
        )
        if self.cwd is not None:
            object.__setattr__(self, "cwd", os.fspath(self.cwd))
        if self.workspace is not None:
            object.__setattr__(self, "workspace", os.fspath(self.workspace))

    def __repr__(self) -> str:
        return (
            "SandboxSpec("
            f"server_id={self.server_id!r}, "
            f"argv=<{len(self.argv)} args>, "
            f"env=<{len(self.env)} vars>, "
            "cwd=<redacted>, "
            f"limits={self.limits!r}, "
            f"workspace_mode={self.workspace_mode!r}, "
            "workspace=<redacted>, "
            f"workspace_read_only={self.workspace_read_only!r}, "
            f"image={self.image!r}, "
            f"network={self.network!r}, "
            f"stream_limit_bytes={self.stream_limit_bytes})"
        )


@runtime_checkable
class SandboxHandle(Protocol):
    """A live sandbox process exposed to the stdio transport."""

    @property
    def process(self) -> asyncio.subprocess.Process: ...

    async def close(self, *, kill: bool = False) -> None: ...


@runtime_checkable
class MCPSandbox(Protocol):
    """A sandbox backend that can start stdio servers."""

    name: str

    async def start(self, spec: SandboxSpec) -> SandboxHandle: ...


def parse_container_command(command: str | Sequence[str]) -> list[str]:
    """Parse a container command with POSIX shell rules on every platform.

    Container argv is always a POSIX command line even when the control plane
    runs on Windows, so ``posix=True`` is intentional here.
    """
    if isinstance(command, str):
        text = command.strip()
        if not text:
            raise SandboxValidationError("MCP sandbox command is empty.")
        try:
            parts = shlex.split(text, posix=True)
        except ValueError as exc:
            raise SandboxValidationError(
                "MCP sandbox command could not be parsed."
            ) from exc
    else:
        try:
            parts = [str(part) for part in command]
        except TypeError as exc:
            raise SandboxValidationError(
                "MCP sandbox command must be a string or a sequence of arguments."
            ) from exc
    if not parts or not parts[0].strip():
        raise SandboxValidationError("MCP sandbox command is empty.")
    return parts


def _has_control_characters(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def validate_stdio_command(
    command: str | Sequence[str],
    *,
    max_args: int = 64,
    max_arg_length: int = 4096,
) -> list[str]:
    """Validate a stdio command without echoing its contents on failure."""
    argv = parse_container_command(command)
    limit_args = max(1, int(max_args))
    limit_length = max(1, int(max_arg_length))
    if len(argv) > limit_args:
        raise SandboxValidationError(
            f"MCP stdio command has more than {limit_args} arguments."
        )
    if argv[0].startswith("-"):
        raise SandboxValidationError("MCP stdio command executable is invalid.")
    if argv[0] != argv[0].strip():
        raise SandboxValidationError("MCP stdio command executable is invalid.")
    for index, arg in enumerate(argv):
        if "\x00" in arg:
            raise SandboxValidationError("MCP stdio command contains a NUL byte.")
        if "\r" in arg or "\n" in arg:
            raise SandboxValidationError(
                "MCP stdio command contains a line break."
            )
        if len(arg) > limit_length:
            raise SandboxValidationError(
                f"MCP stdio command argument {index} exceeds the maximum length."
            )
    return argv


def _csv(value: Any) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


def validate_image(
    image: str,
    *,
    allowed_images: Sequence[str] = (),
    require_digest: bool = False,
) -> str:
    """Validate an image reference and enforce an exact allowlist."""
    clean = str(image or "")
    if not clean or clean != clean.strip() or clean.startswith("-"):
        raise SandboxValidationError("MCP sandbox image reference is invalid.")
    if any(char.isspace() or _has_control_characters(char) for char in clean):
        raise SandboxValidationError("MCP sandbox image reference is invalid.")
    if require_digest and not _DIGEST_RE.search(clean):
        raise SandboxPolicyError(
            "MCP sandbox image must be pinned by sha256 digest."
        )
    allowed = {str(item) for item in allowed_images}
    if allowed and clean not in allowed:
        raise SandboxPolicyError("MCP sandbox image is not allowlisted.")
    return clean


def validate_network(
    network: str,
    *,
    allowed_networks: Sequence[str] = ("none",),
) -> str:
    """Validate a Docker network mode, defaulting to ``none``."""
    raw = str(network or "")
    if not raw.strip():
        clean = "none"
    else:
        clean = raw
    if (
        not clean
        or clean != clean.strip()
        or clean.startswith("-")
        or _has_control_characters(clean)
        or any(char.isspace() for char in clean)
    ):
        raise SandboxValidationError("MCP sandbox network mode is invalid.")
    lowered = clean.lower()
    if lowered in FORBIDDEN_NETWORKS or lowered.startswith("container:"):
        raise SandboxPolicyError("MCP sandbox network mode is not allowed.")
    allowed = {str(item) for item in allowed_networks}
    if allowed and clean not in allowed:
        raise SandboxPolicyError("MCP sandbox network is not allowlisted.")
    return clean


def validate_container_user(user: str, *, allow_root: bool = False) -> str:
    """Require a numeric non-root uid (optionally with a gid)."""
    raw = str(user or "")
    clean = raw.strip()
    if not clean or clean != raw or _has_control_characters(clean):
        raise SandboxPolicyError(
            "MCP sandbox container user must be a numeric uid[:gid]."
        )
    match = _USER_RE.fullmatch(clean)
    if match is None:
        raise SandboxPolicyError(
            "MCP sandbox container user must be a numeric uid[:gid]."
        )
    uid = int(match.group("uid"))
    gid_text = match.group("gid")
    gid = int(gid_text) if gid_text is not None else None
    if not allow_root and (uid == 0 or gid == 0):
        raise SandboxPolicyError(
            "MCP sandbox container user must be non-root."
        )
    return clean


def _repo_root() -> Path:
    # backend/app/tools/mcp/sandbox.py -> repository root
    try:
        return Path(__file__).resolve().parents[4]
    except IndexError:  # pragma: no cover - defensive for unusual layouts
        return Path.cwd().resolve()


def _is_under(path: Path, parent: Path) -> bool:
    try:
        return path == parent or path.is_relative_to(parent)
    except (OSError, ValueError):  # pragma: no cover - platform edge cases
        return False


def validate_workspace_path(
    workspace: str | os.PathLike[str] | None,
    *,
    workspace_root: str | os.PathLike[str] | None = None,
) -> str:
    """Validate a host workspace path used for a read-only container bind."""
    raw = os.fspath(workspace) if workspace is not None else ""
    if not raw or "\x00" in raw or "\r" in raw or "\n" in raw:
        raise SandboxValidationError("MCP sandbox workspace path is invalid.")
    path = Path(raw)
    if not path.is_absolute():
        raise SandboxValidationError("MCP sandbox workspace path must be absolute.")
    if "," in raw:
        raise SandboxValidationError("MCP sandbox workspace path is invalid.")
    resolved = path.resolve(strict=False)

    anchor = Path(resolved.anchor)
    if resolved == anchor:
        raise SandboxPolicyError("MCP sandbox must not mount a filesystem root.")

    home = Path.home().resolve(strict=False)
    repo_root = _repo_root()
    for forbidden in (home, repo_root):
        if resolved == forbidden or _is_under(forbidden, resolved):
            raise SandboxPolicyError(
                "MCP sandbox must not mount a home or repository root."
            )

    parts = resolved.parts
    if len(parts) >= 2 and parts[0] == os.sep and parts[1] in {"dev", "proc", "sys"}:
        raise SandboxPolicyError(
            "MCP sandbox must not mount host system directories."
        )
    if parts == (os.sep, "run") or parts[:3] == (os.sep, "var", "run"):
        raise SandboxPolicyError(
            "MCP sandbox must not mount host system directories."
        )
    lowered = str(resolved).lower()
    if (
        any(part.lower() == "docker.sock" for part in parts)
        or "docker_engine" in lowered
        or "globalroot" in lowered
        or lowered.startswith("\\\\.\\")
    ):
        raise SandboxPolicyError("MCP sandbox must not mount host devices.")

    if workspace_root is not None and str(workspace_root).strip():
        root_raw = os.fspath(workspace_root)
        root = Path(root_raw)
        if not root.is_absolute():
            raise SandboxValidationError(
                "MCP sandbox workspace root must be absolute."
            )
        root_resolved = root.resolve(strict=False)
        if not _is_under(resolved, root_resolved):
            raise SandboxPolicyError(
                "MCP sandbox workspace is outside the configured root."
            )
    try:
        if resolved.exists() and not resolved.is_dir():
            raise SandboxValidationError(
                "MCP sandbox workspace path must be a directory."
            )
    except OSError:  # pragma: no cover - unreadable path
        raise SandboxValidationError(
            "MCP sandbox workspace path is not accessible."
        ) from None
    return str(resolved)


def _validate_env(env: Mapping[str, str] | None) -> dict[str, str]:
    if env is None:
        return {}
    if not isinstance(env, Mapping):
        raise SandboxValidationError(
            "MCP sandbox environment must be a mapping of strings."
        )
    clean: dict[str, str] = {}
    for raw_key, raw_value in env.items():
        key = str(raw_key)
        if not _ENV_KEY_RE.fullmatch(key):
            raise SandboxValidationError(
                "MCP sandbox environment contains an invalid variable name."
            )
        if key.upper() in DANGEROUS_ENV_KEYS:
            raise SandboxValidationError(
                "MCP sandbox environment contains a disallowed variable."
            )
        value = str(raw_value)
        if "\x00" in value or "\r" in value or "\n" in value:
            raise SandboxValidationError(
                "MCP sandbox environment contains an invalid value."
            )
        clean[key] = value
    return clean


def build_subprocess_env(
    env: Mapping[str, str] | None = None,
    *,
    inherit_env: bool = False,
) -> dict[str, str]:
    """Build a child environment for the host subprocess backend.

    When ``inherit_env`` is false (the default) only the historical minimal
    allowlist is copied. Explicit values are validated and dangerous
    interpreter/proxy keys are rejected.
    """
    explicit = _validate_env(env)
    if inherit_env:
        child_env = dict(os.environ)
    else:
        child_env = {
            key: value
            for key, value in os.environ.items()
            if key in SUBPROCESS_ENV_ALLOWLIST
        }
    child_env.update(explicit)
    return child_env


def build_container_env(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the explicit environment passed to a Docker child.

    Nothing is inherited from the host. ``HOME`` and ``TMPDIR`` always point
    at writable tmpfs paths inside the read-only container.
    """
    explicit = _validate_env(env)
    child_env: dict[str, str] = {"HOME": _CONTAINER_TMP, "TMPDIR": _CONTAINER_TMP}
    child_env.update(explicit)
    child_env["HOME"] = _CONTAINER_TMP
    child_env["TMPDIR"] = _CONTAINER_TMP
    return child_env


def write_env_file(env: Mapping[str, str]) -> str:
    """Write a 0600 Docker ``--env-file`` and return its path."""
    clean_env = _validate_env(env)
    fd = -1
    path = ""
    try:
        fd, path = tempfile.mkstemp(
            prefix="flowsmith-mcp-sandbox-", suffix=".env"
        )
        if hasattr(os, "fchmod"):
            try:
                os.fchmod(fd, 0o600)
            except OSError:  # pragma: no cover - Windows / exotic filesystems
                pass
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = -1
            for key, value in clean_env.items():
                handle.write(f"{key}={value}\n")
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - Windows mode semantics
            pass
        return path
    except SandboxError:
        raise
    except OSError as exc:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise SandboxError(
            "MCP sandbox environment file could not be created."
        ) from exc


def remove_env_file(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def redact_diagnostics(text: str, *, limit: int = _DIAGNOSTIC_LIMIT_BYTES) -> str:
    """Bound and redact Docker stderr before surfacing it."""
    cleaned = (text or "").replace("\x00", "")
    cleaned = _BEARER_PATTERN.sub(r"\1 <redacted>", cleaned)
    cleaned = _SECRET_PATTERN.sub(r"\1=<redacted>", cleaned)
    if limit > 0 and len(cleaned) > limit:
        suffix = "... (truncated)"
        cleaned = cleaned[: max(0, limit - len(suffix))] + suffix
    return cleaned


class SubprocessSandboxHandle:
    """Handle for a directly spawned child process."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        close_timeout_s: float,
    ) -> None:
        self._process = process
        self._close_timeout_s = max(0.1, float(close_timeout_s))
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def process(self) -> asyncio.subprocess.Process:
        return self._process

    async def close(self, *, kill: bool = False) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            process = self._process
            if process.returncode is None and kill:
                try:
                    process.kill()
                except (ProcessLookupError, RuntimeError):
                    pass
            stdin = process.stdin
            if process.returncode is None and not kill and stdin is not None:
                if not stdin.is_closing():
                    try:
                        stdin.close()
                    except (OSError, RuntimeError):
                        pass
            try:
                await asyncio.wait_for(process.wait(), self._close_timeout_s)
            except TimeoutError:
                try:
                    process.kill()
                except (ProcessLookupError, RuntimeError):
                    pass
                try:
                    await asyncio.wait_for(
                        process.wait(), self._close_timeout_s
                    )
                except TimeoutError:
                    pass
            if stdin is not None:
                try:
                    stdin.close()
                except (OSError, RuntimeError):
                    pass


def _posix_preexec(limits: SandboxLimits) -> Any:
    import resource

    setrlimit = getattr(resource, "setrlimit")
    rlimit_as = getattr(resource, "RLIMIT_AS")
    rlimit_cpu = getattr(resource, "RLIMIT_CPU")
    memory_bytes = max(1, int(limits.memory_mb)) * 1024 * 1024
    cpu_seconds = max(1, int(limits.cpu_seconds))
    nofile = max(1, int(limits.nofile))
    fsize_bytes = max(1, int(limits.fsize_mb)) * 1024 * 1024
    pids = max(1, int(limits.pids))

    def _limit_child() -> None:
        setrlimit(rlimit_as, (memory_bytes, memory_bytes))
        setrlimit(rlimit_cpu, (cpu_seconds, cpu_seconds))
        optional = (
            ("RLIMIT_NOFILE", nofile),
            ("RLIMIT_FSIZE", fsize_bytes),
            ("RLIMIT_CORE", 0),
            ("RLIMIT_NPROC", pids),
        )
        for name, value in optional:
            resource_id = getattr(resource, name, None)
            if resource_id is None:
                continue
            try:
                setrlimit(resource_id, (value, value))
            except (OSError, ValueError):
                # Not every platform/kernel permits every limit; the memory
                # and CPU limits above remain mandatory and unchanged.
                pass

    return _limit_child


class SubprocessSandbox:
    """Historical host-subprocess behavior behind the sandbox seam."""

    name = "subprocess"

    def __init__(
        self,
        *,
        inherit_env: bool = False,
        close_timeout_s: float = 5.0,
        limits: SandboxLimits | None = None,
    ) -> None:
        self._inherit_env = bool(inherit_env)
        self._close_timeout_s = max(0.1, float(close_timeout_s))
        self._limits = limits

    async def start(self, spec: SandboxSpec) -> SandboxHandle:
        if not spec.argv:
            raise SandboxValidationError("MCP sandbox command is empty.")
        child_env = build_subprocess_env(
            spec.env, inherit_env=self._inherit_env
        )
        limits = self._limits or spec.limits
        preexec_fn = None
        if os.name != "nt":
            preexec_fn = _posix_preexec(limits)
        try:
            process = await asyncio.create_subprocess_exec(
                *spec.argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=spec.cwd,
                env=child_env,
                limit=max(1024, int(spec.stream_limit_bytes)),
                preexec_fn=preexec_fn,
            )
        except (OSError, ValueError) as exc:
            # Exception text can contain argv/env fragments; surface only the
            # failure class.
            raise SandboxError(
                f"MCP subprocess sandbox failed to start ({type(exc).__name__})."
            ) from exc
        return SubprocessSandboxHandle(
            process, close_timeout_s=self._close_timeout_s
        )


@dataclass(frozen=True, slots=True)
class DockerSandboxConfig:
    """Docker backend policy and defaults."""

    image: str = ""
    images: tuple[str, ...] = ()
    network: str = "none"
    networks: tuple[str, ...] = ("none",)
    user: str = "65534:65534"
    allow_root: bool = False
    cpus: float = 1.0
    tmpfs_mb: int = 16
    run_tmpfs_mb: int = 16
    shm_mb: int = 64
    workspace_tmpfs_mb: int = 64
    pull: str = "never"
    startup_timeout_s: float = 15.0
    close_timeout_s: float = 5.0
    require_digest: bool = False
    workspace_mode: str = "none"
    workspace_root: str = ""
    workspace_read_only: bool = False
    docker_executable: str = "docker"
    # Explicit allowlists (aliases for ``images``/``networks``). Both spellings
    # are accepted; explicit allowlists win when both are supplied.
    allowed_images: tuple[str, ...] = ()
    allowed_networks: tuple[str, ...] = ()
    # Size aliases (accepted for callers that spell the unit explicitly).
    tmpfs_size_mb: int = 0
    run_tmpfs_size_mb: int = 0
    shm_size_mb: int = 0
    workspace_tmpfs_size_mb: int = 0

    def __post_init__(self) -> None:
        if int(self.tmpfs_size_mb) > 0:
            object.__setattr__(self, "tmpfs_mb", int(self.tmpfs_size_mb))
        if int(self.run_tmpfs_size_mb) > 0:
            object.__setattr__(
                self, "run_tmpfs_mb", int(self.run_tmpfs_size_mb)
            )
        if int(self.shm_size_mb) > 0:
            object.__setattr__(self, "shm_mb", int(self.shm_size_mb))
        if int(self.workspace_tmpfs_size_mb) > 0:
            object.__setattr__(
                self,
                "workspace_tmpfs_mb",
                int(self.workspace_tmpfs_size_mb),
            )
        executable = str(self.docker_executable or "").strip()
        if (
            not executable
            or executable.startswith("-")
            or _has_control_characters(executable)
        ):
            raise SandboxValidationError(
                "MCP sandbox Docker executable is invalid."
            )
        object.__setattr__(self, "docker_executable", executable)

        mode = str(self.workspace_mode or "none").strip().lower()
        if mode not in _WORKSPACE_MODES:
            raise SandboxValidationError("MCP sandbox workspace mode is invalid.")
        if mode == "inherit":
            mode = "none"
        object.__setattr__(self, "workspace_mode", mode)

        pull = str(self.pull or "never").strip().lower()
        if pull not in _ALLOWED_PULL_MODES:
            raise SandboxPolicyError(
                "MCP sandbox Docker pull policy must be 'never' or 'missing'."
            )
        object.__setattr__(self, "pull", pull)

        if not math.isfinite(float(self.cpus)) or float(self.cpus) <= 0:
            raise SandboxValidationError("MCP sandbox CPU limit must be positive.")
        for value in (
            self.tmpfs_mb,
            self.run_tmpfs_mb,
            self.shm_mb,
            self.workspace_tmpfs_mb,
        ):
            if int(value) <= 0:
                raise SandboxValidationError(
                    "MCP sandbox tmpfs sizes must be positive."
                )

        effective_images = tuple(
            str(item)
            for item in (
                self.allowed_images
                or self.images
                or ((self.image,) if self.image else ())
            )
        )
        object.__setattr__(self, "allowed_images", effective_images)
        effective_networks = tuple(
            str(item)
            for item in (
                self.allowed_networks
                or self.networks
                or (((self.network or "none"),) if self.network else ("none",))
            )
        )
        object.__setattr__(self, "allowed_networks", effective_networks)

        validate_container_user(self.user, allow_root=self.allow_root)
        for candidate in effective_images:
            validate_image(candidate)
        if self.image:
            validate_image(
                self.image,
                allowed_images=effective_images,
                require_digest=self.require_digest,
            )
        for candidate in effective_networks:
            validate_network(candidate, allowed_networks=(candidate,))
        if self.network:
            validate_network(self.network, allowed_networks=effective_networks)
        if mode == "configured":
            if str(self.workspace_root or "").strip():
                validate_workspace_path(self.workspace_root)

    def with_overrides(self, **overrides: Any) -> "DockerSandboxConfig":
        """Return a validated copy with selected policy fields overridden."""
        values = {item.name: getattr(self, item.name) for item in fields(self)}
        values.update(overrides)
        return DockerSandboxConfig(**values)

    @classmethod
    def from_settings(cls, settings: Any) -> "DockerSandboxConfig":
        def value(name: str, default: Any) -> Any:
            return getattr(settings, name, default)

        image = str(value("mcp_stdio_docker_image", "") or "")
        network = str(value("mcp_stdio_docker_network", "none") or "none")
        images = _csv(value("mcp_stdio_docker_images", ""))
        networks = _csv(value("mcp_stdio_docker_networks", ""))
        if not networks or (
            networks == ("none",) and network and network != "none"
        ):
            networks = (network,) if network else ("none",)
        return cls(
            image=image,
            images=images,
            network=network,
            networks=networks,
            user=str(value("mcp_stdio_docker_user", "65534:65534") or ""),
            allow_root=bool(value("mcp_stdio_docker_allow_root", False)),
            cpus=float(value("mcp_stdio_docker_cpus", 1.0)),
            tmpfs_mb=int(value("mcp_stdio_docker_tmpfs_mb", 16)),
            run_tmpfs_mb=int(value("mcp_stdio_docker_run_tmpfs_mb", 16)),
            shm_mb=int(value("mcp_stdio_docker_shm_mb", 64)),
            workspace_tmpfs_mb=int(
                value("mcp_stdio_docker_workspace_tmpfs_mb", 64)
            ),
            pull=str(value("mcp_stdio_docker_pull", "never") or "never"),
            startup_timeout_s=float(
                value("mcp_stdio_docker_startup_timeout_s", 15.0)
            ),
            close_timeout_s=float(
                value("mcp_stdio_close_timeout_s", 5.0)
            ),
            require_digest=bool(
                value("mcp_stdio_docker_require_digest", False)
            ),
            workspace_mode=str(
                value("mcp_stdio_sandbox_workspace_mode", "none") or "none"
            ),
            workspace_root=str(
                value("mcp_stdio_sandbox_workspace_root", "") or ""
            ),
            workspace_read_only=bool(
                value("mcp_stdio_sandbox_workspace_read_only", False)
            ),
            docker_executable=str(
                value("mcp_stdio_docker_executable", "docker") or "docker"
            ),
        )


def _container_name(server_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(server_id or "server"))
    safe = safe.strip("-_.")[:40] or "server"
    if not safe[0].isalnum():
        safe = f"s-{safe}"[:40]
    return f"flowsmith-mcp-{safe}-{uuid.uuid4().hex[:8]}"


def _safe_label(value: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", str(value or ""))
    return cleaned[:128] or "unknown"


def _workspace_argv(
    spec: SandboxSpec, config: DockerSandboxConfig
) -> tuple[str, list[str]]:
    mode = str(spec.workspace_mode or "").strip().lower()
    if not mode or mode == "none":
        configured_mode = config.workspace_mode
        if configured_mode and configured_mode != "none":
            mode = configured_mode
    if mode == "inherit":
        mode = "none"
    if mode not in _WORKSPACE_MODES:
        raise SandboxValidationError("MCP sandbox workspace mode is invalid.")
    if mode == "none":
        return _CONTAINER_TMP, []
    if mode == "ephemeral":
        access = "ro" if spec.workspace_read_only or config.workspace_read_only else "rw"
        return (
            _CONTAINER_WORKSPACE,
            [
                "--tmpfs",
                f"{_CONTAINER_WORKSPACE}:{access},"
                f"size={max(1, int(config.workspace_tmpfs_mb))}m,mode=1777",
            ],
        )
    source = spec.workspace or config.workspace_root
    resolved = validate_workspace_path(
        source,
        workspace_root=config.workspace_root or None,
    )
    return (
        _CONTAINER_WORKSPACE,
        [
            "--mount",
            f"type=bind,source={resolved},target={_CONTAINER_WORKSPACE},readonly",
        ],
    )


def build_docker_run_argv(
    spec: SandboxSpec,
    config: DockerSandboxConfig,
    container_name: str | None = None,
    env_file: str | None = None,
    *,
    name: str | None = None,
    image: str | None = None,
    network: str | None = None,
    created_at: float | None = None,
) -> list[str]:
    """Build the complete ``docker run`` argv without touching the host.

    ``env_file`` must already exist and is created by
    :func:`write_env_file`; its contents never appear in argv.
    """
    chosen_name = container_name or name
    if not chosen_name:
        chosen_name = _container_name(spec.server_id)
    if (
        not _CONTAINER_NAME_RE.fullmatch(chosen_name)
        or chosen_name.startswith("-")
    ):
        raise SandboxValidationError("MCP sandbox container name is invalid.")
    if not env_file or _has_control_characters(str(env_file)):
        raise SandboxValidationError("MCP sandbox env file path is invalid.")

    allowed_images = config.allowed_images
    selected_image = image or spec.image or config.image
    if not selected_image:
        raise SandboxPolicyError("MCP sandbox image is not configured.")
    if not allowed_images:
        allowed_images = (selected_image,)
    selected_image = validate_image(
        selected_image,
        allowed_images=allowed_images,
        require_digest=config.require_digest,
    )

    allowed_networks = config.allowed_networks or ("none",)
    requested_network = network or spec.network or ""
    if not requested_network or requested_network.lower() == "none":
        if config.network and config.network.lower() != "none":
            requested_network = config.network
    selected_network = validate_network(
        requested_network or "none", allowed_networks=allowed_networks
    )

    user = validate_container_user(
        config.user, allow_root=config.allow_root
    )
    workdir, workspace_args = _workspace_argv(spec, config)
    limits = spec.limits
    memory_mb = max(1, int(limits.memory_mb))
    pids = max(1, int(limits.pids))
    nofile = max(1, int(limits.nofile))
    fsize_bytes = max(1, int(limits.fsize_mb)) * 1024 * 1024
    cpus = float(config.cpus)
    tmpfs_mb = max(1, int(config.tmpfs_mb))
    run_tmpfs_mb = max(1, int(config.run_tmpfs_mb))
    shm_mb = max(1, int(config.shm_mb))

    argv = [
        config.docker_executable,
        "run",
        "--rm",
        "--init",
        "-i",
        "--name",
        chosen_name,
        "--label",
        f"flowsmith.mcp.server={_safe_label(spec.server_id)}",
        "--label",
        f"flowsmith.mcp.server_id={_safe_label(spec.server_id)}",
        "--label",
        "flowsmith.mcp.sandbox=true",
        "--label",
        f"flowsmith.mcp.created={int(created_at if created_at is not None else time.time())}",
        "--network",
        selected_network,
        "--read-only",
        "--tmpfs",
        f"{_CONTAINER_TMP}:rw,size={tmpfs_mb}m,mode=1777",
        "--tmpfs",
        f"{_CONTAINER_RUN}:rw,size={run_tmpfs_mb}m,mode=1777",
        "--user",
        user,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        str(pids),
        "--memory",
        f"{memory_mb}m",
        "--memory-swap",
        f"{memory_mb}m",
        "--cpus",
        str(cpus),
        "--ulimit",
        f"cpu={max(1, int(limits.cpu_seconds))}",
        "--ulimit",
        f"nofile={nofile}",
        "--ulimit",
        "core=0",
        "--ulimit",
        f"fsize={fsize_bytes}",
        "--shm-size",
        f"{shm_mb}m",
        "--stop-timeout",
        "2",
        "--log-driver",
        "none",
        "--pull",
        config.pull,
        "--env-file",
        str(env_file),
        "--env",
        f"HOME={_CONTAINER_TMP}",
        "--env",
        f"TMPDIR={_CONTAINER_TMP}",
        "--workdir",
        workdir,
    ]
    argv.extend(workspace_args)
    argv.append(selected_image)
    argv.extend(str(part) for part in spec.argv)
    return argv


def docker_available(config: DockerSandboxConfig) -> bool:
    """Return True when the configured Docker CLI appears to exist."""
    executable = config.docker_executable
    if os.path.dirname(executable):
        return Path(executable).is_file()
    return bool(shutil.which(executable))


class DockerSandboxHandle:
    """Handle for a ``docker run`` CLI process attached to stdio."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        docker_executable: str,
        container_name: str,
        env_file: str,
        close_timeout_s: float,
        startup_timeout_s: float,
    ) -> None:
        self._process = process
        self._docker_executable = docker_executable
        self._container_name = container_name
        self._env_file = env_file
        self._close_timeout_s = max(0.1, float(close_timeout_s))
        self._startup_timeout_s = max(0.1, float(startup_timeout_s))
        self._stderr = bytearray()
        self._stderr_task: asyncio.Task[None] | None = None
        if process.stderr is not None:
            self._stderr_task = asyncio.create_task(
                self._drain_stderr(process.stderr)
            )
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def process(self) -> asyncio.subprocess.Process:
        return self._process

    @property
    def container_name(self) -> str:
        return self._container_name

    @property
    def env_file(self) -> str:
        return self._env_file

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        try:
            while True:
                chunk = await stream.read(1024)
                if not chunk:
                    break
                remaining = _DIAGNOSTIC_LIMIT_BYTES - len(self._stderr)
                if remaining > 0:
                    self._stderr.extend(chunk[:remaining])
        except asyncio.CancelledError:
            return
        except (OSError, ValueError):
            return

    async def wait_startup(self) -> bool:
        """Wait briefly for an immediate CLI failure; True means it failed."""
        if self._process.returncode is not None:
            return True
        try:
            await asyncio.wait_for(
                self._process.wait(),
                min(0.25, self._startup_timeout_s),
            )
        except TimeoutError:
            return False
        return True

    async def diagnostics(self) -> str:
        task = self._stderr_task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, 0.5)
            except (TimeoutError, asyncio.CancelledError):
                pass
        return redact_diagnostics(
            self._stderr.decode("utf-8", errors="replace")
        )

    async def _force_remove(self) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                self._docker_executable,
                "rm",
                "-f",
                self._container_name,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), 2.0)
        except (OSError, ValueError, TimeoutError):
            pass

    async def close(self, *, kill: bool = False) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            force_remove = bool(kill)
            process = self._process
            stdin = process.stdin
            if process.returncode is None and kill:
                try:
                    process.kill()
                except (ProcessLookupError, RuntimeError):
                    pass
            if process.returncode is None and not kill and stdin is not None:
                if not stdin.is_closing():
                    try:
                        stdin.close()
                    except (OSError, RuntimeError):
                        pass
            try:
                await asyncio.wait_for(process.wait(), self._close_timeout_s)
            except TimeoutError:
                force_remove = True
                try:
                    process.kill()
                except (ProcessLookupError, RuntimeError):
                    pass
                try:
                    await asyncio.wait_for(
                        process.wait(), self._close_timeout_s
                    )
                except TimeoutError:
                    pass
            if stdin is not None:
                try:
                    stdin.close()
                except (OSError, RuntimeError):
                    pass
            if force_remove:
                await self._force_remove()
            task = self._stderr_task
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, OSError, ValueError):
                    pass
            remove_env_file(self._env_file)


class DockerSandbox:
    """Opt-in Docker backend that runs one stdio server per container."""

    name = "docker"

    def __init__(
        self,
        config: DockerSandboxConfig,
        server_id: str = "",
        image: str | None = None,
        limits: SandboxLimits | None = None,
        max_args: int = 64,
        max_arg_length: int = 4096,
    ) -> None:
        self._config = config
        self._server_id = str(server_id or "")
        self._image = str(image if image is not None else config.image)
        self._limits = limits
        self._max_args = max(1, int(max_args))
        self._max_arg_length = max(1, int(max_arg_length))
        if self._image:
            allowed = config.allowed_images or (self._image,)
            validate_image(
                self._image,
                allowed_images=allowed,
                require_digest=config.require_digest,
            )

    def available(self) -> bool:
        return docker_available(self._config)

    def build_docker_run_argv(
        self,
        spec: SandboxSpec,
        container_name: str | None = None,
        env_file: str | None = None,
        *,
        name: str | None = None,
    ) -> list[str]:
        return build_docker_run_argv(
            spec,
            self._config,
            container_name=container_name,
            env_file=env_file,
            name=name,
            image=self._image or spec.image or None,
            created_at=time.time(),
        )

    async def start(self, spec: SandboxSpec) -> SandboxHandle:
        validate_stdio_command(
            spec.argv,
            max_args=self._max_args,
            max_arg_length=self._max_arg_length,
        )
        effective_server_id = spec.server_id or self._server_id
        spec = SandboxSpec(
            argv=spec.argv,
            env=spec.env,
            cwd=spec.cwd,
            limits=self._limits or spec.limits,
            workspace_mode=spec.workspace_mode,
            workspace=spec.workspace,
            workspace_read_only=spec.workspace_read_only,
            server_id=effective_server_id,
            image=spec.image,
            network=spec.network,
            stream_limit_bytes=spec.stream_limit_bytes,
        )
        container_name = _container_name(effective_server_id)
        env = build_container_env(spec.env)
        env_file = write_env_file(env)
        try:
            run_argv = build_docker_run_argv(
                spec,
                self._config,
                container_name=container_name,
                env_file=env_file,
                image=self._image or spec.image or None,
            )
        except Exception:
            remove_env_file(env_file)
            raise
        try:
            process = await asyncio.create_subprocess_exec(
                *run_argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            remove_env_file(env_file)
            raise SandboxUnavailable(
                "MCP sandbox Docker executable is unavailable."
            ) from exc
        except ValueError as exc:
            remove_env_file(env_file)
            raise SandboxError(
                f"MCP docker sandbox failed to start ({type(exc).__name__})."
            ) from exc

        handle = DockerSandboxHandle(
            process,
            docker_executable=self._config.docker_executable,
            container_name=container_name,
            env_file=env_file,
            close_timeout_s=self._config.close_timeout_s,
            startup_timeout_s=self._config.startup_timeout_s,
        )
        if await handle.wait_startup():
            exit_code = handle.process.returncode
            await handle.close(kill=True)
            raise SandboxUnavailable(
                "MCP docker sandbox failed to start "
                f"(exit code {exit_code})."
            )
        return handle


def _limits_from_settings(settings: Any) -> SandboxLimits:
    return SandboxLimits(
        memory_mb=max(64, int(getattr(settings, "mcp_stdio_sandbox_memory_mb", 256))),
        cpu_seconds=max(
            1, int(getattr(settings, "mcp_stdio_sandbox_cpu_seconds", 60))
        ),
        pids=max(1, int(getattr(settings, "mcp_stdio_sandbox_pids", 64))),
        nofile=max(
            16, int(getattr(settings, "mcp_stdio_sandbox_nofile", 256))
        ),
        fsize_mb=max(
            1, int(getattr(settings, "mcp_stdio_sandbox_fsize_mb", 64))
        ),
    )


def _fallback_allowed(settings: Any) -> bool:
    fallback = str(
        getattr(settings, "mcp_stdio_sandbox_fallback", "fail") or "fail"
    ).strip().lower()
    allow_unsandboxed = bool(
        getattr(settings, "mcp_stdio_allow_unsandboxed", False)
    )
    return fallback == "subprocess" and allow_unsandboxed


def _effective_sandbox_backend(settings: Any, backend: str | None = None) -> str:
    raw = backend
    if raw is None or not str(raw).strip():
        raw = getattr(settings, "mcp_stdio_sandbox_backend", "subprocess")
    clean = str(raw or "subprocess").strip().lower()
    if clean not in SANDBOX_BACKENDS:
        raise SandboxValidationError("Unsupported MCP sandbox backend.")
    return clean


def docker_config_for_server(
    settings: Any,
    *,
    image: str | None = None,
    workspace_mode: str | None = None,
    workspace_path: str | None = None,
    network: str | None = None,
    read_only: bool | None = None,
) -> DockerSandboxConfig:
    """Merge per-server sandbox choices over global Docker policy.

    Global settings remain the fallback for every field that is empty on the
    server record. The global image allowlist and workspace root remain hard
    boundaries: a per-server image must pass the same syntax, digest, and
    allowlist checks as a global image.
    """
    base = DockerSandboxConfig.from_settings(settings)

    selected_image = str(image or "").strip()
    if selected_image:
        validate_image(
            selected_image,
            allowed_images=base.allowed_images,
            require_digest=base.require_digest,
        )

    mode = str(workspace_mode or "").strip().lower()
    if not mode:
        mode = base.workspace_mode
    if mode not in SANDBOX_WORKSPACE_MODES:
        raise SandboxValidationError("MCP sandbox workspace mode is invalid.")
    path = str(workspace_path or "").strip()
    effective_path = path or base.workspace_root
    if mode == "configured":
        if not effective_path:
            raise SandboxPolicyError("MCP sandbox workspace path is not configured.")
        validate_workspace_path(
            effective_path, workspace_root=base.workspace_root or None
        )

    requested_network = str(network or "").strip().lower()
    if not requested_network:
        requested_network = base.network or "none"
    allowed_networks = tuple(dict.fromkeys(("none", *base.allowed_networks)))
    validate_network(requested_network, allowed_networks=allowed_networks)

    return base.with_overrides(
        network=requested_network,
        networks=allowed_networks,
        allowed_networks=allowed_networks,
        workspace_mode=mode,
        workspace_read_only=(
            base.workspace_read_only if read_only is None else bool(read_only)
        ),
    )


def build_sandbox(
    settings: Any,
    *,
    server_id: str = "",
    backend: str | None = None,
    image: str | None = None,
    workspace_mode: str | None = None,
    workspace_path: str | None = None,
    network: str | None = None,
    read_only: bool | None = None,
) -> MCPSandbox:
    """Select the effective sandbox backend, failing closed by default.

    Per-server values win when supplied; missing values fall back to the
    global ``MCP_STDIO_*`` settings. Docker is never selected implicitly.
    """
    effective_backend = _effective_sandbox_backend(settings, backend)
    assert_stdio_sandbox_allowed(settings, backend=effective_backend)
    close_timeout_s = float(
        getattr(settings, "mcp_stdio_close_timeout_s", 5.0)
    )
    limits = _limits_from_settings(settings)
    if effective_backend == "subprocess":
        return SubprocessSandbox(
            close_timeout_s=close_timeout_s, limits=limits
        )

    config = docker_config_for_server(
        settings,
        image=image,
        workspace_mode=workspace_mode,
        workspace_path=workspace_path,
        network=network,
        read_only=read_only,
    )
    default_image = config.image or (
        config.allowed_images[0] if config.allowed_images else ""
    )
    selected_image = str(image or "").strip() or default_image
    if not selected_image:
        raise SandboxPolicyError("MCP sandbox image is not configured.")
    sandbox = DockerSandbox(
        config,
        server_id=server_id,
        image=selected_image,
        limits=limits,
        max_args=int(
            getattr(settings, "mcp_stdio_max_command_args", 64)
        ),
        max_arg_length=int(
            getattr(settings, "mcp_stdio_max_command_arg_length", 4096)
        ),
    )
    if not sandbox.available():
        if _fallback_allowed(settings):
            return SubprocessSandbox(
                close_timeout_s=close_timeout_s, limits=limits
            )
        raise SandboxUnavailable("MCP docker sandbox backend is unavailable.")
    return sandbox


def assert_stdio_sandbox_allowed(
    settings: Any, *, backend: str | None = None
) -> None:
    """Reject unsandboxed stdio execution in production unless opted in.

    ``backend`` should be the effective per-server backend; when omitted the
    global configuration decides, preserving existing callers.
    """
    effective_backend = _effective_sandbox_backend(settings, backend)
    if effective_backend == "docker":
        return
    app_env = str(getattr(settings, "app_env", "development") or "").strip().lower()
    allow_unsandboxed = bool(
        getattr(settings, "mcp_stdio_allow_unsandboxed", False)
    )
    if app_env == "production" and not allow_unsandboxed:
        raise SandboxPolicyError(
            "MCP_SANDBOX_REQUIRED: MCP stdio sandbox is required in "
            "production; set MCP_STDIO_ALLOW_UNSANDBOXED=true only for an "
            "explicit unsandboxed exception.",
            code="MCP_SANDBOX_REQUIRED",
        )
