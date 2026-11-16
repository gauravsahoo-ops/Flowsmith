"""Async stdio transport for MCP JSON-RPC servers.

The transport owns at most one child process and speaks line-delimited JSON-RPC
2.0 over its stdin/stdout. Commands are parsed with :func:`shlex.split` and are
never run through a shell. Child environment values are passed straight to the
process and are never logged, echoed in errors, or included in tracebacks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from collections.abc import Mapping, Sequence
from typing import Any

from app.tools.mcp.sandbox import (
    MCPSandbox,
    SandboxError,
    SandboxHandle,
    SandboxLimits,
    SandboxSpec,
    SubprocessSandbox,
)

logger = logging.getLogger("tools.mcp.stdio")

MAX_MESSAGE_BYTES = 8 * 1024 * 1024


class MCPTransportError(RuntimeError):
    """The stdio child process could not be started, reached, or stopped."""


class MCPProtocolError(MCPTransportError):
    """The child process returned an invalid JSON-RPC response."""


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def parse_stdio_command(command: str | Sequence[str]) -> list[str]:
    """Parse a stdio command into an argv list without invoking a shell.

    ``shlex.split`` is POSIX-aware by default; on Windows ``posix=False`` is
    used so backslashes in executable paths survive, then the quote characters
    that mode preserves are removed.
    """
    if isinstance(command, str):
        text = command.strip()
        if not text:
            raise MCPTransportError("MCP stdio command is empty.")
        try:
            parts = shlex.split(text, posix=os.name != "nt")
        except ValueError as exc:
            raise MCPTransportError("MCP stdio command could not be parsed.") from exc
        if os.name == "nt":
            parts = [_unquote(part) for part in parts]
    else:
        parts = [str(part) for part in command]
    if not parts or not parts[0].strip():
        raise MCPTransportError("MCP stdio command is empty.")
    return parts


class StdioMCPClient:
    """Minimal MCP client for a newline-delimited JSON-RPC child process.

    The process starts lazily on the first request and is reused for the
    lifetime of the client. Call :meth:`close` (or use the async context
    manager) so the child is shut down deterministically.
    """

    def __init__(
        self,
        command: str | Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        timeout_s: float = 30.0,
        close_timeout_s: float = 5.0,
        max_memory_mb: int = 256,
        max_cpu_seconds: int = 60,
        inherit_env: bool = False,
        sandbox: MCPSandbox | None = None,
        server_id: str = "",
        sandbox_workspace_mode: str = "none",
        sandbox_workspace: str | os.PathLike[str] | None = None,
        sandbox_workspace_read_only: bool | None = None,
        sandbox_image: str = "",
        sandbox_network: str = "none",
    ) -> None:
        self._argv = parse_stdio_command(command)
        # Retained only for process creation; never logged or serialized.
        self._env = {str(key): str(value) for key, value in (env or {}).items()}
        self._cwd = os.fspath(cwd) if cwd is not None else None
        self._timeout_s = max(0.1, float(timeout_s))
        self._close_timeout_s = max(0.1, float(close_timeout_s))
        self._max_memory_mb = max(64, int(max_memory_mb))
        self._max_cpu_seconds = max(1, int(max_cpu_seconds))
        self._inherit_env = bool(inherit_env)
        self._sandbox = sandbox
        self._default_sandbox: MCPSandbox | None = None
        self._server_id = str(server_id or "")
        self._sandbox_workspace_mode = str(sandbox_workspace_mode or "none")
        self._sandbox_workspace = (
            os.fspath(sandbox_workspace) if sandbox_workspace is not None else None
        )
        self._sandbox_workspace_read_only = sandbox_workspace_read_only
        self._sandbox_image = str(sandbox_image or "")
        self._sandbox_network = str(sandbox_network or "none")
        self._limits = SandboxLimits(
            memory_mb=self._max_memory_mb,
            cpu_seconds=self._max_cpu_seconds,
        )
        self._handle: SandboxHandle | None = None
        self._lock = asyncio.Lock()
        self._request_id = 0
        self._initialized = False

    async def __aenter__(self) -> "StdioMCPClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    def _timeout(self, timeout_s: float | None) -> float:
        if timeout_s is None:
            return self._timeout_s
        return max(0.1, float(timeout_s))

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _sandbox_instance(self) -> MCPSandbox:
        if self._sandbox is not None:
            return self._sandbox
        if self._default_sandbox is None:
            self._default_sandbox = SubprocessSandbox(
                inherit_env=self._inherit_env,
                close_timeout_s=self._close_timeout_s,
                limits=self._limits,
            )
        return self._default_sandbox

    def _sandbox_spec(self) -> SandboxSpec:
        return SandboxSpec(
            argv=tuple(self._argv),
            env=dict(self._env),
            cwd=self._cwd,
            limits=self._limits,
            workspace_mode=self._sandbox_workspace_mode,
            workspace=self._sandbox_workspace,
            workspace_read_only=bool(self._sandbox_workspace_read_only),
            server_id=self._server_id,
            image=self._sandbox_image,
            network=self._sandbox_network,
            stream_limit_bytes=MAX_MESSAGE_BYTES,
        )

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        handle = self._handle
        if handle is not None:
            process = handle.process
            if process.returncode is None:
                return process
            self._handle = None
            self._initialized = False
            await self._reap(handle, kill=True)

        try:
            handle = await self._sandbox_instance().start(self._sandbox_spec())
        except SandboxError as exc:
            # Sandbox failures carry a stable code; never include argv/env.
            raise MCPTransportError(
                f"MCP stdio sandbox could not start ({exc.code})."
            ) from exc
        except (OSError, ValueError) as exc:  # defensive: custom backends
            raise MCPTransportError(
                f"Failed to start MCP stdio server ({type(exc).__name__})."
            ) from exc
        self._handle = handle
        return handle.process

    async def _reap(self, handle: SandboxHandle, *, kill: bool) -> None:
        try:
            await handle.close(kill=kill)
        except (SandboxError, OSError, RuntimeError, TimeoutError):
            # Cleanup must not mask the request failure; details are never
            # logged because handles may hold argv/environment state.
            logger.debug("MCP stdio sandbox cleanup failed.")

    def _take_handle(self) -> SandboxHandle | None:
        handle = self._handle
        self._handle = None
        self._initialized = False
        return handle

    @staticmethod
    def _decode(line: bytes, method: str) -> dict[str, Any]:
        try:
            payload = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MCPProtocolError(
                f"MCP stdio response to {method} was not valid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise MCPProtocolError(
                f"MCP stdio response to {method} was not a JSON object."
            )
        return payload

    @staticmethod
    def _rpc_error_message(method: str, error: Any) -> str:
        if isinstance(error, dict):
            code = error.get("code")
            message = str(error.get("message") or "").strip()
            if code is not None and message:
                detail = f"{code}: {message}"
            else:
                detail = message or str(code or "")
        else:
            detail = str(error or "").strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        return f"MCP stdio {method} failed" + (f": {detail}" if detail else ".")

    async def _request(
        self,
        method: str,
        params: dict[str, Any],
        timeout_s: float | None,
    ) -> Any:
        timeout = self._timeout(timeout_s)
        async with self._lock:
            process = await self._ensure_process()
            stdin = process.stdin
            stdout = process.stdout
            if stdin is None or stdout is None:
                raise MCPTransportError(
                    "MCP stdio process has no stdin/stdout pipes."
                )

            request_id = self._next_id()
            message = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
            try:
                stdin.write(
                    json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
                )
                await asyncio.wait_for(stdin.drain(), timeout)

                while True:
                    line = await asyncio.wait_for(stdout.readline(), timeout)
                    if not line:
                        exit_code = process.returncode
                        handle = self._take_handle()
                        if handle is not None:
                            await self._reap(handle, kill=True)
                        raise MCPTransportError(
                            f"MCP stdio server closed the connection during {method} "
                            f"(exit code {exit_code})."
                        )
                    if len(line) > MAX_MESSAGE_BYTES:
                        raise MCPProtocolError(
                            f"MCP stdio response to {method} exceeded the size limit."
                        )
                    response = self._decode(line, method)
                    if "id" not in response:
                        # Server-initiated notification; not a response.
                        continue
                    if response.get("id") != request_id:
                        raise MCPProtocolError(
                            f"MCP stdio response id did not match the {method} request."
                        )
                    if "error" in response:
                        raise MCPProtocolError(
                            self._rpc_error_message(method, response.get("error"))
                        )
                    if "result" not in response:
                        raise MCPProtocolError(
                            f"MCP stdio response to {method} had no result."
                        )
                    return response["result"]
            except TimeoutError:
                handle = self._take_handle()
                if handle is not None:
                    await self._reap(handle, kill=True)
                raise TimeoutError(
                    f"MCP stdio {method} timed out after {timeout:.1f}s."
                ) from None
            except MCPTransportError:
                raise
            except ValueError as exc:
                handle = self._take_handle()
                if handle is not None:
                    await self._reap(handle, kill=True)
                raise MCPProtocolError(
                    f"MCP stdio {method} response exceeded the size limit."
                ) from exc
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                handle = self._take_handle()
                if handle is not None:
                    await self._reap(handle, kill=True)
                raise MCPTransportError(
                    f"MCP stdio {method} transport failed ({type(exc).__name__})."
                ) from exc

    async def _notify(
        self,
        method: str,
        params: dict[str, Any],
        timeout_s: float | None = None,
    ) -> None:
        timeout = self._timeout(timeout_s)
        async with self._lock:
            process = await self._ensure_process()
            stdin = process.stdin
            if stdin is None:
                raise MCPTransportError("MCP stdio process has no stdin pipe.")
            message = {"jsonrpc": "2.0", "method": method, "params": params}
            try:
                stdin.write(
                    json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
                )
                await asyncio.wait_for(stdin.drain(), timeout)
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                handle = self._take_handle()
                if handle is not None:
                    await self._reap(handle, kill=True)
                raise MCPTransportError(
                    f"MCP stdio {method} transport failed ({type(exc).__name__})."
                ) from exc

    async def initialize(self, timeout_s: float | None = None) -> None:
        """Perform the MCP initialize handshake once per child process."""
        if self._initialized:
            return
        await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "flowsmith", "version": "1.6.0"},
            },
            timeout_s,
        )
        await self._notify("notifications/initialized", {}, timeout_s)
        self._initialized = True

    async def ping(self, timeout_s: float | None = None) -> bool:
        """Send a JSON-RPC ``ping`` and return ``True`` on success."""
        await self.initialize(timeout_s)
        await self._request("ping", {}, timeout_s)
        return True

    async def list_tools(self, timeout_s: float | None = None) -> list[dict[str, Any]]:
        """Return raw ``tools/list`` declarations (same shape as ``MCPClient``)."""
        await self.initialize(timeout_s)
        result = await self._request("tools/list", {}, timeout_s)
        if not isinstance(result, dict):
            raise MCPProtocolError("MCP tools/list returned a non-object result.")
        tools = result.get("tools")
        if tools is None:
            return []
        if not isinstance(tools, list):
            raise MCPProtocolError("MCP tools/list returned a non-list result.")
        return [tool for tool in tools if isinstance(tool, dict)]

    async def list_tools_strict(
        self, timeout_s: float | None = None
    ) -> list[dict[str, Any]]:
        """Strict alias used by discovery; transport failures always raise."""
        return await self.list_tools(timeout_s=timeout_s)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """Call ``tools/call`` and normalize the result like ``MCPClient``."""
        await self.initialize(timeout_s)
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
            timeout_s,
        )
        if not isinstance(result, dict):
            raise MCPProtocolError("MCP tools/call returned a non-object result.")

        content = result.get("content")
        if not isinstance(content, list):
            content = []
        text_parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return {
            "tool": name,
            "raw_result": result,
            "content": "\n".join(text_parts) if text_parts else "",
            "is_error": bool(result.get("isError", False)),
            "content_count": len(content),
            "capability_type": "MCP_TOOL",
        }

    async def close(self) -> None:
        """Close stdin, then terminate/kill the child if it does not exit."""
        async with self._lock:
            handle = self._take_handle()
            if handle is None:
                return
            await handle.close(kill=False)
