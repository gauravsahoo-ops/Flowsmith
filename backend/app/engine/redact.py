"""Secret redaction for execution payloads (Phase 13: workflow debugger).

The debugger surfaces raw node inputs/outputs. Nodes never see
credentials (those arrive via a side channel and are not recorded), but
node *outputs* can legitimately contain sensitive-looking material —
response headers with cookies, upstream API tokens echoed in a body,
env-derived values interpolated into parameters that then flow through
`set_data`.

Defence in depth: before an execution's trace/results leave the API,
every value stored under a key that LOOKS sensitive is replaced with a
fixed mask. Only key names are judged — ordinary fields (email, name,
total) are untouched, so debugging stays useful.

Pure functions; unit-tested directly.
"""

from __future__ import annotations

from typing import Any

MASK = "••••••••"

# Substring markers (case-insensitive) that mark a KEY as sensitive.
# Mirrors SafeHTTPClient's header-redaction vocabulary.
SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "cookie",
    "credential",
    "private_key",
    "access_key",
    "session",
    "signature",
)

_MAX_DEPTH = 12


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def redact_sensitive(value: Any, _depth: int = 0) -> Any:
    """Return a copy of *value* with sensitive-keyed strings masked."""
    if _depth > _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in value.items():
            if isinstance(val, (dict, list)):
                out[key] = redact_sensitive(val, _depth + 1)
            elif isinstance(val, str) and _is_sensitive_key(key):
                out[key] = MASK
            else:
                out[key] = val
        return out
    if isinstance(value, list):
        return [redact_sensitive(v, _depth + 1) for v in value]
    return value


def redact_trace_steps(steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Redact the inputs/outputs/error of every trace step."""
    if not steps:
        return steps or []
    out: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        scrubbed = dict(step)
        for field in ("inputs", "outputs", "full_inputs", "full_outputs", "error"):
            if field in scrubbed and scrubbed[field] is not None:
                scrubbed[field] = redact_sensitive(scrubbed[field])
        out.append(scrubbed)
    return out


def redact_results(results: dict[str, Any] | None) -> dict[str, Any] | None:
    """Redact the persisted results envelope ({outputs: node -> handle -> items})."""
    if not isinstance(results, dict):
        return results
    return redact_sensitive(results)


def redact_url(url: str | None) -> str:
    """Sanitize URL by masking secret query parameter values."""
    if not url:
        return ""
    try:
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        parsed = urlparse(url)
        if not parsed.query:
            return url
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        sanitized_pairs = []
        for k, v in query_pairs:
            if _is_sensitive_key(k):
                sanitized_pairs.append((k, MASK))
            else:
                sanitized_pairs.append((k, v))
        new_query = urlencode(sanitized_pairs)
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        ))
    except Exception:
        return url


def redact_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    """Sanitize request/response headers by masking sensitive values."""
    if not headers or not isinstance(headers, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in headers.items():
        v_str = str(v) if v is not None else ""
        if _is_sensitive_key(k) or k.lower() in ("authorization", "cookie", "set-cookie", "proxy-authorization", "x-api-key", "x-auth-token"):
            out[k] = MASK
        else:
            out[k] = v_str
    return out


def redact_payload(payload: Any, max_size_bytes: int = 65536) -> tuple[Any, bool]:
    """Redact sensitive keys from payload and enforce size limit.

    Returns (sanitized_payload, is_truncated).
    """
    if payload is None:
        return None, False

    scrubbed = redact_sensitive(payload)
    is_truncated = False

    if isinstance(scrubbed, (dict, list)):
        import json

        try:
            raw = json.dumps(scrubbed, default=str)
            if len(raw) > max_size_bytes:
                is_truncated = True
                # Bound dictionary or list items
                if isinstance(scrubbed, dict):
                    scrubbed = {k: v for i, (k, v) in enumerate(scrubbed.items()) if i < 50}
                    scrubbed["_truncated_notice"] = f"Payload exceeded {max_size_bytes} bytes; truncated for telemetry storage."
                elif isinstance(scrubbed, list):
                    scrubbed = scrubbed[:50]
                    scrubbed.append(f"[{len(payload) - 50} more items truncated]")
        except Exception:
            pass
    elif isinstance(scrubbed, str):
        if len(scrubbed) > max_size_bytes:
            scrubbed = scrubbed[:max_size_bytes] + "… [TRUNCATED]"
            is_truncated = True

    return scrubbed, is_truncated


def sanitize_error(error: Any) -> tuple[str, str, str]:
    """Extract safe (error_type, error_code, error_summary) from an error object."""
    if not error:
        return "UNKNOWN_ERROR", "ERROR", "An unspecified error occurred."

    err_dict: dict[str, Any] = {}
    if isinstance(error, dict):
        err_dict = error
    elif hasattr(error, "to_dict"):
        err_dict = error.to_dict()
    else:
        err_str = str(error)
        return "EXECUTION_ERROR", "EXECUTION_FAILED", err_str[:255]

    code = str(err_dict.get("code") or "EXECUTION_FAILED")
    msg = str(err_dict.get("message") or err_dict.get("error") or "Execution failed.")

    # Determine error type category
    code_upper = code.upper()
    if any(k in code_upper for k in ("AUTH", "UNAUTHORIZED", "FORBIDDEN", "CREDENTIAL", "TOKEN")):
        error_type = "AUTHENTICATION_ERROR"
    elif any(k in code_upper for k in ("RATE_LIMIT", "429", "THROTTLED")):
        error_type = "RATE_LIMITED"
    elif any(k in code_upper for k in ("TIMEOUT", "DEADLINE")):
        error_type = "TIMEOUT"
    elif any(k in code_upper for k in ("NETWORK", "CONNECT", "DISCONNECT", "SSRF")):
        error_type = "NETWORK_ERROR"
    elif any(k in code_upper for k in ("VALIDATION", "BAD_REQUEST", "INVALID", "SCHEMA")):
        error_type = "VALIDATION_ERROR"
    elif any(k in code_upper for k in ("CONNECTOR", "PROVIDER")):
        error_type = "CONNECTOR_ERROR"
    elif any(k in code_upper for k in ("CANCEL",)):
        error_type = "CANCELLED"
    else:
        error_type = "INTERNAL_ERROR"

    # Redact any accidental tokens from message
    for marker in SENSITIVE_KEY_MARKERS:
        if f"{marker}=" in msg.lower() or f"{marker}:" in msg.lower():
            import re
            msg = re.sub(rf"(?i)({marker}[:=\s]+)[^\s,;]+", rf"\1{MASK}", msg)

    summary = msg[:255]
    return error_type, code, summary


def sanitize_csv_cell(value: Any) -> str:
    """Escape CSV formula injection triggers (=, +, -, @, \\t, \\r).

    Prepends a single quote if the cell begins with an active formula character.
    """
    if value is None:
        return ""
    val_str = str(value)
    if not val_str:
        return ""
    if val_str[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{val_str}"
    return val_str

