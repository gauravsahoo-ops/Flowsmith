"""SSH helper (paramiko, blocking — callers run it in a thread).

Ops: exec a remote command, download/upload small text files over SFTP.
paramiko is a lazy import so the app boots without it; callers get a
clear install hint instead of an ImportError. Auth: password or
private key (+optional passphrase).
"""

from __future__ import annotations

from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error

DEFAULT_MAX_BYTES = 1024 * 1024


def _paramiko() -> Any:
    try:
        import paramiko  # type: ignore[import-not-found]
    except ImportError as exc:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "SSH support needs the 'paramiko' package: pip install paramiko.",
            retryable=False,
        ) from exc
    return paramiko


def _conn_params(creds: dict) -> dict[str, Any]:
    host = str((creds or {}).get("host") or "").strip()
    username = str((creds or {}).get("username") or "").strip()
    if not host or not username:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "SSH node needs an 'ssh' credential with host and username.",
            retryable=False,
        )
    try:
        port = int((creds or {}).get("port") or 22)
    except (TypeError, ValueError):
        port = 22
    password = str((creds or {}).get("password") or "")
    private_key = str((creds or {}).get("private_key") or "")
    if not password and not private_key:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "SSH node needs a password or a private key in its 'ssh' credential.",
            retryable=False,
        )
    return {
        "host": host, "port": port, "username": username,
        "password": password or None, "private_key": private_key,
        "passphrase": str((creds or {}).get("passphrase") or "") or None,
        "timeout": float((creds or {}).get("timeout_seconds") or 30.0),
    }


class SshSession:
    """Connected paramiko session usable as a context manager."""

    def __init__(self, creds: dict) -> None:
        paramiko = _paramiko()
        params = _conn_params(creds)
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict[str, Any] = {
            "hostname": params["host"], "port": params["port"],
            "username": params["username"], "timeout": params["timeout"],
            "banner_timeout": params["timeout"], "auth_timeout": params["timeout"],
        }
        if params["private_key"]:
            import io as _io

            try:
                key_file = _io.StringIO(params["private_key"])
                pkey: Any = None
                for loader in (paramiko.RSAKey, paramiko.Ed25519Key,
                               paramiko.ECDSAKey, paramiko.DSSKey):
                    try:
                        key_file.seek(0)
                        pkey = loader.from_private_key(key_file, password=params["passphrase"])
                        break
                    except Exception:
                        continue
                if pkey is None:
                    raise ValueError("unrecognized private key format")
            except Exception as exc:
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST, f"SSH private key rejected: {exc}", retryable=False,
                ) from exc
            kwargs["pkey"] = pkey
        else:
            kwargs["password"] = params["password"]
        try:
            self._client.connect(**kwargs)
        except Exception as exc:
            name = type(exc).__name__
            if "Authentication" in name:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED, f"SSH authentication failed: {exc}", retryable=False,
                ) from exc
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"SSH server unreachable: {exc}", retryable=True,
            ) from exc

    def __enter__(self) -> "SshSession":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def sftp(self) -> Any:
        """Open an SFTP channel on this session (caller owns close())."""
        return self._client.open_sftp()

    def exec(self, command: str, timeout: float = 30.0) -> dict[str, Any]:
        if not str(command or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "exec needs a command.", retryable=False)
        try:
            _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            return {
                "ok": exit_code == 0,
                "exit_code": exit_code,
                "stdout": stdout.read().decode(errors="replace"),
                "stderr": stderr.read().decode(errors="replace"),
            }
        except make_connector_error:
            raise
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"SSH exec failed: {exc}", retryable=True,
            ) from exc

    def download_text(self, path: str, max_bytes: int = DEFAULT_MAX_BYTES, encoding: str = "utf-8") -> str:
        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "download needs a remote path.", retryable=False)
        try:
            sftp = self._client.open_sftp()
            try:
                with sftp.open(path, "rb") as handle:
                    chunks: list[bytes] = []
                    total = 0
                    while True:
                        piece = handle.read(65536)
                        if not piece:
                            break
                        total += len(piece)
                        if total > max_bytes:
                            raise make_connector_error(
                                ConnectorErrorCode.BAD_REQUEST,
                                f"Remote file exceeds the {max_bytes}-byte text cap.",
                                retryable=False,
                            )
                        chunks.append(piece)
            finally:
                sftp.close()
        except make_connector_error:
            raise
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"SSH download failed: {exc}", retryable=False,
            ) from exc
        return b"".join(chunks).decode(encoding, errors="replace")

    def upload_text(self, path: str, content: str, encoding: str = "utf-8") -> dict[str, Any]:
        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "upload needs a remote path.", retryable=False)
        data = str(content or "").encode(encoding, errors="replace")
        try:
            sftp = self._client.open_sftp()
            try:
                with sftp.open(path, "wb") as handle:
                    handle.write(data)
            finally:
                sftp.close()
        except make_connector_error:
            raise
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f"SSH upload failed: {exc}", retryable=False,
            ) from exc
        return {"ok": True, "path": path, "bytes": len(data)}
