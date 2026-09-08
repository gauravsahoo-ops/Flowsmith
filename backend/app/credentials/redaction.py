"""Secret redaction helpers — never expose secrets in logs, outputs, errors."""
from __future__ import annotations

from typing import Any, Dict

from app.engine.redact import redact_sensitive, MASK  # reuse engine's sensitive markers


def redact_secret(data: Any) -> Any:
    return redact_sensitive(data)


def sanitize_credential(data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove secrets from credential data for logging."""
    out: Dict[str, Any] = {}
    for k, v in data.items():
        lk = k.lower()
        if any(s in lk for s in ("password", "secret", "token", "key", "api_key")):
            out[k] = MASK if v else ""
        else:
            out[k] = v
    return out


def sanitize_request(request: Dict[str, Any]) -> Dict[str, Any]:
    headers = dict(request.get("headers") or {})
    redacted: Dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if any(s in lk for s in ("authorization", "cookie", "x-api-key", "token", "secret", "key")):
            redacted[k] = MASK
        else:
            redacted[k] = v
    out = dict(request)
    out["headers"] = redacted
    # Also redact query auth
    query = dict(request.get("query") or {})
    redacted_q = {}
    for k, v in query.items():
        if "key" in k.lower() or "token" in k.lower():
            redacted_q[k] = MASK
        else:
            redacted_q[k] = v
    out["query"] = redacted_q
    return out


def sanitize_error(err: Dict[str, Any]) -> Dict[str, Any]:
    return redact_sensitive(err)
