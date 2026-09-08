"""CredentialValidator — validates workflow credential references before queue (spec)."""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from .resolver import get_credential_resolver
from .type_registry import get_credential_type_registry
from app.engine.errors import WorkflowValidationError


def validate_workflow_credentials(workflow: Dict[str, Any], db: Session, user_id: int) -> None:
    """Validate every node's credential references and HTTP config before queue.

    If any step fails, DO NOT QUEUE — raise WorkflowValidationError with issues.
    """
    issues: List[Dict[str, Any]] = []
    nodes = workflow.get("nodes", [])
    for node in nodes:
        node_id = node.get("id", "unknown")
        node_type = node.get("type", "")
        creds: Dict[str, str] = node.get("credentials") or {}
        for cred_type, cred_id in creds.items():
            # Check type known
            type_reg = get_credential_type_registry()
            entry = type_reg.get(cred_type)
            if entry and not entry.get("implemented"):
                issues.append({
                    "code": "CREDENTIAL_PROVIDER_NOT_IMPLEMENTED",
                    "node_id": node_id,
                    "field": f"credentials.{cred_type}",
                    "message": f"Authentication provider '{entry.get('provider')}' for '{cred_type}' not implemented yet.",
                })
                continue
            # Resolve — may raise CredentialError or ValueError
            try:
                resolver = get_credential_resolver()
                resolver.resolve(db, user_id, cred_type, cred_id)
            except Exception as e:
                code = getattr(e, "code", "CREDENTIAL_ERROR")
                issues.append({
                    "code": code,
                    "node_id": node_id,
                    "field": f"credentials.{cred_type}",
                    "message": str(e),
                })
        # HTTP Request node specific validation before queue (URL, method, auth, headers, query, body, options)
        if node_type == "http_request":
            params = node.get("parameters") or {}
            # Method
            method = str(params.get("method", "GET")).upper()
            if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
                issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.method", "message": f"Invalid method '{method}'."})
            # URL
            url = str(params.get("url", "")).strip()
            if not url:
                issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.url", "message": "URL is required."})
            elif "{{" not in url:
                from urllib.parse import urlparse
                try:
                    pu = urlparse(url)
                    if pu.scheme not in ("http", "https"):
                        issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.url", "message": f"URL must start with http:// or https:// (got '{url}')."})
                    elif not pu.netloc:
                        issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.url", "message": f"URL is missing a host (got '{url}')."})
                except Exception as e:
                    issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.url", "message": f"Invalid URL: {e}"})
            # Authentication — check predefined implemented
            auth_mode = params.get("authentication", "none")
            if auth_mode == "predefined":
                pre_id = str(params.get("predefinedType", "")).strip()
                if not pre_id:
                    issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.predefinedType", "message": "Predefined Credential Type is required."})
                else:
                    # Find predefined entry
                    from app.credentials.registry import PREDEFINED_CREDENTIALS
                    pre = next((p for p in PREDEFINED_CREDENTIALS if p["id"] == pre_id), None)
                    if pre and not pre.get("implemented"):
                        issues.append({"code": "CREDENTIAL_PROVIDER_NOT_IMPLEMENTED", "node_id": node_id, "field": "parameters.predefinedType", "message": f"Authentication provider '{pre.get('provider')}' not implemented yet."})
                    elif not pre:
                        issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.predefinedType", "message": f"Unknown predefined type '{pre_id}'."})
            elif auth_mode == "generic":
                at = str(params.get("auth_type", "none"))
                if at == "none" or not at:
                    pass  # Silently treat as no auth — user selected Generic but didn't pick a sub-type
                # Check provider implemented for generic
                else:
                    from app.credentials.registry import CREDENTIAL_IMPLEMENTED
                    # Map auth_type to credential type for implemented check
                    m = {"bearer":"bearer_auth","basic":"basic_auth","header":"header_auth","query":"query_auth","digest":"digest_auth","custom":"custom_auth","oauth2":"oauth2","oauth1":"oauth1","api_key":"header_auth"}
                    ct = m.get(at, at)
                    if ct in CREDENTIAL_IMPLEMENTED and not CREDENTIAL_IMPLEMENTED.get(ct):
                        issues.append({"code": "CREDENTIAL_PROVIDER_NOT_IMPLEMENTED", "node_id": node_id, "field": "parameters.auth_type", "message": f"Provider '{at}' not implemented."})
            # Headers / Query / Body type checks (light)
            if params.get("headers") is not None and not isinstance(params.get("headers"), dict):
                issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.headers", "message": "Headers must be an object."})
            if params.get("query") is not None and not isinstance(params.get("query"), dict):
                issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.query", "message": "Query must be an object."})
            # Header JSON mode validation
            if params.get("sendHeaders") and params.get("headerMode") == "json" and params.get("headerJson") is not None:
                hj = str(params.get("headerJson", "")).strip()
                if hj and "{{" not in hj:
                    import json as _json
                    try:
                        parsed = _json.loads(hj)
                        if not isinstance(parsed, dict):
                            issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.headerJson", "message": "Headers JSON must be an object."})
                        else:
                            for k in parsed.keys():
                                if not str(k).strip():
                                    issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.headerJson", "message": "Header name must not be empty."})
                    except Exception as e:
                        import json as _json2
                        try:
                            _json2.loads(hj)
                        except _json2.JSONDecodeError as je:
                            issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.headerJson", "message": f"Invalid Headers JSON: {je.msg} at line {je.lineno}."})
                        else:
                            issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.headerJson", "message": f"Invalid Headers JSON: {e}"})
            if params.get("sendHeaders") and params.get("headerMode", "fields") == "fields":
                headers = params.get("headers") or {}
                if isinstance(headers, dict):
                    for k in headers.keys():
                        if not str(k).strip():
                            issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.headers", "message": "Header name must not be empty."})
            # Timeout, etc.
            try:
                tout = float(params.get("timeout_seconds", 30))
                if not (0.5 <= tout <= 300):
                    issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.timeout_seconds", "message": "Timeout must be 0.5-300 seconds."})
            except Exception:
                issues.append({"code": "INVALID_PARAMETER", "node_id": node_id, "field": "parameters.timeout_seconds", "message": "Invalid timeout."})
    if issues:
        raise WorkflowValidationError(issues)
