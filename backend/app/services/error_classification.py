"""Error Classification and Sanitization Service.

Classifies arbitrary errors, exceptions, or error dictionaries into normalized,
actionable ErrorEvent metadata with strict secret redaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


# Keys that MUST be recursively redacted from technical details, payloads, and traces
SENSITIVE_KEY_PATTERNS = {
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "client_secret",
    "authorization",
    "auth",
    "cookie",
    "session",
    "private_key",
    "fernet",
    "bearer",
    "signature",
}

# Regex to detect tokens in raw strings/error messages (e.g. Bearer eyJ..., 00D5..., etc.)
BEARER_REGEX = re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]+)", re.IGNORECASE)
TOKEN_PARAM_REGEX = re.compile(
    r"(access_token|refresh_token|client_secret|api_key|password)=([A-Za-z0-9_\-\.\%]+)",
    re.IGNORECASE,
)


def sanitize_string(value: str) -> str:
    """Strip bearer tokens, secrets, and query parameters from error strings."""
    if not isinstance(value, str):
        return str(value)
    sanitized = BEARER_REGEX.sub("Bearer [REDACTED]", value)
    sanitized = TOKEN_PARAM_REGEX.sub(r"\1=[REDACTED]", sanitized)
    return sanitized


def is_sensitive_key(key: str) -> bool:
    k_lower = str(key).lower()
    if any(k_lower.endswith(sfx) for sfx in ("_count", "_usage", "_list", "_length", "_items")):
        return False
    if k_lower in ("total_tokens", "prompt_tokens", "completion_tokens", "token_count"):
        return False
    if k_lower in SENSITIVE_KEY_PATTERNS:
        return True
    parts = set(re.split(r"[_.\-]", k_lower))
    if any(p in SENSITIVE_KEY_PATTERNS for p in parts):
        return True
    return any(pattern in k_lower for pattern in SENSITIVE_KEY_PATTERNS)


def sanitize_payload(obj: Any, depth: int = 0) -> Any:
    """Recursively redact sensitive keys and values from dicts, lists, and primitives."""
    if depth > 10:
        return "[TRUNCATED_DEPTH]"
    if isinstance(obj, dict):
        sanitized_dict = {}
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                sanitized_dict[k] = sanitize_payload(v, depth + 1)
            elif is_sensitive_key(k):
                sanitized_dict[k] = "[REDACTED]"
            else:
                sanitized_dict[k] = sanitize_payload(v, depth + 1)
        return sanitized_dict
    elif isinstance(obj, list):
        return [sanitize_payload(item, depth + 1) for item in obj[:50]]
    elif isinstance(obj, str):
        return sanitize_string(obj)
    elif isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    else:
        return sanitize_string(str(obj))


class ErrorClassification:
    def __init__(
        self,
        category: str,
        code: str,
        severity: str,
        title: str,
        message: str,
        resolution: str,
        technical_details: dict[str, Any] | None = None,
    ):
        self.category = category
        self.code = code
        self.severity = severity
        self.title = title
        self.message = message
        self.resolution = resolution
        self.technical_details = sanitize_payload(technical_details or {})


def compute_fingerprint(
    category: str,
    code: str,
    user_id: int | None,
    workflow_id: str | None,
    node_id: str | None,
    connector_type: str | None,
) -> str:
    """Compute a deterministic hash for deduplication and alert throttling.

    Groups repeated failures of the same node / workflow / connector within a cooldown window.
    """
    raw = f"{user_id or 0}:{category}:{code}:{workflow_id or ''}:{node_id or ''}:{connector_type or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def classify_error(
    error_data: Any,
    workflow_name: str | None = None,
    node_name: str | None = None,
    connector_type: str | None = None,
) -> ErrorClassification:
    """Analyze an exception or error dict and produce a classified error structure."""
    raw_msg = ""
    raw_code = ""
    http_status = None
    tech_details: dict[str, Any] = {}

    if isinstance(error_data, dict):
        raw_msg = str(error_data.get("message") or error_data.get("detail") or error_data.get("error") or "")
        raw_code = str(error_data.get("code") or "")
        http_status = error_data.get("status_code") or error_data.get("http_status")
        tech_details = dict(error_data)
    elif isinstance(error_data, Exception):
        raw_msg = str(error_data)
        raw_code = error_data.__class__.__name__
        tech_details = {"exception_type": error_data.__class__.__name__, "exception_str": str(error_data)}
    elif isinstance(error_data, str):
        raw_msg = error_data
        tech_details = {"raw_error": error_data}
    else:
        raw_msg = str(error_data)
        tech_details = {"raw_error": raw_msg}

    lower_msg = raw_msg.lower()
    lower_code = raw_code.lower()
    provider_label = connector_type.replace("_", " ").title() if connector_type else "Integration"

    # 1. External OAuth & Credential Token Expiration / Revocation
    if any(
        term in lower_msg or term in lower_code
        for term in [
            "token refresh failed",
            "invalid_grant",
            "refresh token expired",
            "access token expired",
            "oauth token expired",
            "session expired",
            "authentication session has expired",
            "reconnect your account",
            "refresh_token_revoked",
            "unauthorized",
            "auth_session_expired",
            "authentication failed",
            "auth error",
        ]
    ) or http_status == 401 or (
        http_status == 403
        and any(w in lower_msg for w in ("token", "expired", "oauth", "auth", "permission"))
    ):
        return ErrorClassification(
            category="AUTH_SESSION_EXPIRED",
            code="OAUTH_SESSION_EXPIRED",
            severity="CRITICAL",
            title=f"Action Required: Your {provider_label} Session Has Expired",
            message=(
                f"Your Flowsmith workflow could not complete because the {provider_label} authentication "
                f"session has expired, and automatic token renewal was unsuccessful."
            ),
            resolution=(
                f"Reconnect your {provider_label} account in Flowsmith Settings > Credentials and "
                f"reauthorize the required permissions. Once restored, rerun the failed execution."
            ),
            technical_details=tech_details,
        )

    # 2. Credential Deleted, Missing, or Invalid Client Config
    if any(
        term in lower_msg or term in lower_code
        for term in [
            "credential missing",
            "credential not found",
            "credential deleted",
            "invalid_client",
            "client_secret missing",
            "missing credential",
        ]
    ):
        return ErrorClassification(
            category="CREDENTIAL_REVOKED",
            code="CREDENTIAL_NOT_FOUND_OR_INVALID",
            severity="CRITICAL",
            title=f"Configuration Error: {provider_label} Credential Missing or Invalid",
            message=f"The required credential for {provider_label} is missing, disabled, or contains invalid credentials.",
            resolution=f"Open Flowsmith Credentials and verify or re-create your {provider_label} connection.",
            technical_details=tech_details,
        )

    # 3. Rate Limiting (HTTP 429)
    if http_status == 429 or "rate limit" in lower_msg or "too many requests" in lower_msg:
        return ErrorClassification(
            category="CONNECTOR_RATE_LIMIT",
            code="API_RATE_LIMIT_EXCEEDED",
            severity="WARNING",
            title=f"API Rate Limit Exceeded: {provider_label}",
            message=(
                f"The external {provider_label} service temporarily rejected requests because the API rate "
                f"limit has been exceeded."
            ),
            resolution=(
                "Wait for the rate limit cooldown period to expire. Consider reducing workflow frequency, "
                "adding batching delays, or upgrading external API quota."
            ),
            technical_details=tech_details,
        )

    # 4. External Service Timeout / 503 Outage
    if (
        http_status in (502, 503, 504)
        or "timeout" in lower_msg
        or "timed out" in lower_msg
        or "service unavailable" in lower_msg
        or "connection reset" in lower_msg
    ):
        is_timeout = "timeout" in lower_msg or http_status == 504
        return ErrorClassification(
            category="EXTERNAL_SERVICE_UNAVAILABLE" if not is_timeout else "WORKFLOW_TIMEOUT",
            code="HTTP_TIMEOUT" if is_timeout else "EXTERNAL_SERVICE_UNAVAILABLE",
            severity="ERROR",
            title=f"{provider_label} Service Timeout or Outage" if is_timeout else f"{provider_label} Service Unavailable",
            message=(
                f"The external service {provider_label} took too long to respond or returned a temporary service outage error."
                if is_timeout
                else f"The external {provider_label} service returned an unavailable or bad gateway status ({http_status or '503'})."
            ),
            resolution="Review external service health status. If the outage is transient, automatic retry or re-running the execution will succeed.",
            technical_details=tech_details,
        )

    # 5. Schema Validation & Missing Variables
    if any(
        term in lower_msg
        for term in [
            "missing required",
            "validation error",
            "schema validation",
            "variable not found",
            "keyerror",
            "undefined variable",
        ]
    ):
        return ErrorClassification(
            category="SCHEMA_VALIDATION_ERROR",
            code="INVALID_DATA_SCHEMA",
            severity="ERROR",
            title=f"Data Validation Error in {node_name or 'Node'}",
            message=f"The workflow failed because required inputs or variables were missing or did not match the expected schema: {sanitize_string(raw_msg)[:200]}",
            resolution="Check the input mapping for this node and ensure upstream nodes provide the required variables.",
            technical_details=tech_details,
        )

    # 6. Expression / Transformation Failure
    if "expression" in lower_msg or "syntax error" in lower_msg or "json parse" in lower_msg:
        return ErrorClassification(
            category="NODE_EXECUTION_FAILED",
            code="EXPRESSION_EVALUATION_ERROR",
            severity="ERROR",
            title=f"Expression Evaluation Error in {node_name or 'Node'}",
            message=f"Flowsmith could not evaluate the dynamic expression or parse JSON payload: {sanitize_string(raw_msg)[:200]}",
            resolution="Review expression syntax in node configuration and verify incoming data formats.",
            technical_details=tech_details,
        )

    # 7. Worker Stopped or Infrastructure Failure
    if any(
        term in lower_msg
        for term in [
            "worker stopped",
            "worker crashed",
            "redis connection",
            "database connection",
            "deadlock",
        ]
    ):
        return ErrorClassification(
            category="INFRASTRUCTURE_FAILURE",
            code="WORKER_OR_INFRA_CRASH",
            severity="CRITICAL",
            title="Execution Interrupted by Background Worker",
            message="The execution was interrupted because the background worker process stopped or lost database connectivity.",
            resolution="The system has preserved execution state. Check server logs or retry the execution.",
            technical_details=tech_details,
        )

    # 8. Node Execution Failure (General)
    if node_name or "node" in lower_msg:
        return ErrorClassification(
            category="NODE_EXECUTION_FAILED",
            code="NODE_EXECUTION_ERROR",
            severity="ERROR",
            title=f"Workflow Node Failed: {node_name or 'Execution Step'}",
            message=f"Node '{node_name or 'Step'}' failed during workflow execution: {sanitize_string(raw_msg)[:250]}",
            resolution="Inspect node configuration, verify connector authentication, and review execution logs for input/output payloads.",
            technical_details=tech_details,
        )

    # 9. Fallback Unexpected Error
    return ErrorClassification(
        category="UNEXPECTED_ERROR",
        code=raw_code or "UNEXPECTED_FAILURE",
        severity="ERROR",
        title=f"Workflow Execution Failed: {workflow_name or 'Workflow'}",
        message=f"The workflow encountered an unexpected failure: {sanitize_string(raw_msg)[:250]}",
        resolution="Review execution details and logs. If this issue persists, contact your workspace administrator.",
        technical_details=tech_details,
    )
