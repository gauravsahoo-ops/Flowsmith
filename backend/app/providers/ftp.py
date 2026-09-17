"""FTP(S) helper (stdlib ftplib, blocking — callers run it in a thread).

Ops: list, download_text, upload_text, delete, mkdir. Listing prefers
MLSD machine-readable facts with NLST fallback. Text transfers are
size-capped so a runaway file cannot blow up an execution payload.
"""

from __future__ import annotations

import ftplib
import io
from typing import Any

from app.connectors import ConnectorErrorCode, make_connector_error

DEFAULT_MAX_BYTES = 1024 * 1024


def _conn_params(creds: dict) -> dict[str, Any]:
    host = str((creds or {}).get("host") or "").strip()
    if not host:
        raise make_connector_error(
            ConnectorErrorCode.NOT_CONFIGURED,
            "FTP node needs an 'ftp' credential with host (and username/password).",
            retryable=False,
        )
    try:
        port = int((creds or {}).get("port") or 21)
    except (TypeError, ValueError):
        port = 21
    return {
        "host": host,
        "port": port,
        "username": str((creds or {}).get("username") or ""),
        "password": str((creds or {}).get("password") or ""),
        "secure": bool((creds or {}).get("secure", False)),
        "timeout": float((creds or {}).get("timeout_seconds") or 30.0),
    }


class FtpSession:
    """Connected ftplib session usable as a context manager."""

    def __init__(self, creds: dict) -> None:
        params = _conn_params(creds)
        cls = ftplib.FTP_TLS if params["secure"] else ftplib.FTP
        try:
            self._ftp = cls()
            self._ftp.connect(params["host"], params["port"], timeout=params["timeout"])
            self._ftp.login(params["username"], params["password"])
            if params["secure"]:
                prot_p = getattr(self._ftp, "prot_p", None)
                if callable(prot_p):
                    prot_p()
        except OSError as exc:
            raise make_connector_error(
                ConnectorErrorCode.UNAVAILABLE, f"FTP server unreachable: {exc}", retryable=True,
            ) from exc
        except ftplib.error_perm as exc:
            raise make_connector_error(
                ConnectorErrorCode.AUTH_FAILED, f"FTP login failed: {exc}", retryable=False,
            ) from exc

    def __enter__(self) -> "FtpSession":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        try:
            self._ftp.quit()
        except Exception:
            try:
                self._ftp.close()
            except Exception:
                pass

    def list(self, path: str = "", limit: int = 100) -> list[dict[str, Any]]:
        target = path or "."
        try:
            entries = list(self._ftp.mlsd(target))
        except (ftplib.error_perm, ftplib.error_temp):
            names: list[str] = []
            self._ftp.retrlines(f"NLST {target}", names.append)
            entries = [(n, {"type": "unknown"}) for n in names]
        out = []
        for name, facts in entries[: max(1, limit)]:
            out.append({"name": name, "type": facts.get("type", "unknown"), "size": facts.get("size"), "modify": facts.get("modify")})
        return out

    def download_text(self, path: str, max_bytes: int = DEFAULT_MAX_BYTES, encoding: str = "utf-8") -> str:
        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "download needs a remote path.", retryable=False)
        buf = io.BytesIO()
        try:
            self._ftp.retrbinary(f"RETR {path}", buf.write)
        except ftplib.error_perm as exc:
            raise make_connector_error(
                ConnectorErrorCode.NOT_FOUND if "550" in str(exc) else ConnectorErrorCode.BAD_REQUEST,
                f"FTP download failed: {exc}", retryable=False,
            ) from exc
        data = buf.getvalue()
        if len(data) > max_bytes:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Remote file exceeds the {max_bytes}-byte text cap; fetch it via File I/O instead.",
                retryable=False,
            )
        return data.decode(encoding, errors="replace")

    def upload_text(self, path: str, content: str, encoding: str = "utf-8") -> dict[str, Any]:
        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "upload needs a remote path.", retryable=False)
        data = str(content or "").encode(encoding, errors="replace")
        try:
            self._ftp.storbinary(f"STOR {path}", io.BytesIO(data))
        except ftplib.error_perm as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"FTP upload failed: {exc}", retryable=False) from exc
        return {"ok": True, "path": path, "bytes": len(data)}

    def delete(self, path: str) -> dict[str, Any]:
        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "delete needs a remote path.", retryable=False)
        try:
            self._ftp.delete(path)
        except ftplib.error_perm as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"FTP delete failed: {exc}", retryable=False) from exc
        return {"ok": True, "path": path}

    def mkdir(self, path: str) -> dict[str, Any]:
        if not str(path or "").strip():
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, "mkdir needs a remote path.", retryable=False)
        try:
            self._ftp.mkd(path)
        except ftplib.error_perm as exc:
            raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f"FTP mkdir failed: {exc}", retryable=False) from exc
        return {"ok": True, "path": path}
