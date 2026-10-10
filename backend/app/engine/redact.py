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
    lowered = str(key).lower()
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
