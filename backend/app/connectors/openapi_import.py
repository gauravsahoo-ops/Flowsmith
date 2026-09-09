"""OpenAPI importer, Phase 1 (original implementation).

Pure parser: OpenAPI 3.x (JSON/YAML, string or dict) into a small
intermediate model (`ApiSpec`/`ApiOperation`) that the code emitter
(step 2) turns into Flowsmith provider + definition + connector
modules. No network, no file writes here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

AuthKind = Literal["api_key_header", "api_key_query", "bearer", "basic", "oauth2", "none"]

_MAX_OPS = 50
_KEY_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class ApiParam:
    name: str
    location: str  # path | query
    required: bool = False


@dataclass
class ApiOperation:
    operation_key: str
    method: str
    path: str
    summary: str = ""
    path_params: list[str] = field(default_factory=list)
    query_params: list[ApiParam] = field(default_factory=list)
    has_body: bool = False


@dataclass
class ApiAuth:
    kind: AuthKind = "none"
    name: str = ""  # header/query param name for apiKey
    header_value: str = ""  # e.g. "Bearer " prefix hint (from description)


@dataclass
class ApiSpec:
    title: str
    base_url: str
    operations: list[ApiOperation] = field(default_factory=list)
    auth: ApiAuth = field(default_factory=ApiAuth)


def _slug(text: str) -> str:
    slug = _KEY_RE.sub("_", text.lower()).strip("_")
    return slug or "operation"


def load_spec(source: str | dict[str, Any]) -> dict[str, Any]:
    """Parse an OpenAPI document from JSON text, YAML text, or dict."""
    if isinstance(source, dict):
        return source
    text = source.strip()
    if text.startswith("{"):
        return json.loads(text)
    import yaml

    return yaml.safe_load(text)


def detect_auth(spec: dict[str, Any]) -> ApiAuth:
    """First declared security scheme wins (components.securitySchemes)."""
    schemes = ((spec.get("components") or {}).get("securitySchemes") or {})
    for name, scheme in schemes.items():
        if not isinstance(scheme, dict):
            continue
        stype = str(scheme.get("type") or "").lower()
        if stype == "apikey":
            loc = str(scheme.get("in") or "").lower()
            if loc == "query":
                return ApiAuth(kind="api_key_query", name=str(scheme.get("name") or "api_key"))
            return ApiAuth(kind="api_key_header", name=str(scheme.get("name") or "X-API-Key"))
        if stype == "http":
            sub = str(scheme.get("scheme") or "").lower()
            if sub == "bearer":
                return ApiAuth(kind="bearer", name="Authorization")
            return ApiAuth(kind="basic", name="Authorization")
        if stype in ("oauth2", "openauth"):
            return ApiAuth(kind="oauth2", name=name)
    return ApiAuth(kind="none")


def _base_url(spec: dict[str, Any]) -> str:
    def _from_servers(servers: Any) -> str:
        if servers and isinstance(servers, list) and isinstance(servers[0], dict):
            url = str(servers[0].get("url") or "").rstrip("/")
            variables = servers[0].get("variables") or {}
            for var, meta in variables.items():
                default = (meta or {}).get("default", "") if isinstance(meta, dict) else ""
                url = url.replace("{" + var + "}", str(default))
            if url.startswith("http"):
                return url
        return ""

    url = _from_servers(spec.get("servers"))
    if url:
        return url
    # OpenAPI allows servers per path item / operation too.
    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        url = _from_servers(methods.get("servers"))
        if url:
            return url
        for operation in methods.values():
            if isinstance(operation, dict):
                url = _from_servers(operation.get("servers"))
                if url:
                    return url
    # Swagger 2.0: schemes + host + basePath.
    if spec.get("swagger"):
        schemes = spec.get("schemes") or ["https"]
        scheme = str(schemes[0]) if schemes[0] in ("http", "https") else "https"
        host = str(spec.get("host") or "").strip().rstrip("/")
        base = str(spec.get("basePath") or "").rstrip("/")
        if host:
            return f"{scheme}://{host}{base}"
    return ""


def extract_operations(spec: dict[str, Any], *, max_ops: int = _MAX_OPS) -> list[ApiOperation]:
    """Flatten paths+methods into stable operation keys (capped)."""
    ops: list[ApiOperation] = []
    paths = spec.get("paths") or {}
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            if not isinstance(operation, dict):
                continue
            raw_id = str(operation.get("operationId") or "")
            key = _slug(raw_id) if raw_id else _slug(f"{method}_{path}")
            summary = str(operation.get("summary") or operation.get("description") or "")[:200]
            path_params = re.findall(r"\{([^}/]+)\}", path)
            query_params: list[ApiParam] = []
            has_body = isinstance(operation.get("requestBody"), dict)
            for param in operation.get("parameters") or []:
                if not isinstance(param, dict):
                    continue
                location = str(param.get("in") or "")
                if location in ("body", "formData"):
                    has_body = True
                    continue
                if location != "query":
                    continue
                query_params.append(ApiParam(
                    name=str(param.get("name") or ""),
                    location="query",
                    required=bool(param.get("required")),
                ))
            ops.append(ApiOperation(
                operation_key=key, method=method.upper(), path=path, summary=summary,
                path_params=path_params, query_params=query_params, has_body=has_body,
            ))
            if len(ops) >= max_ops:
                return ops
    # Stable output regardless of document ordering quirks.
    ops.sort(key=lambda o: o.operation_key)
    return ops


def parse_spec(source: str | dict[str, Any]) -> ApiSpec:
    """Full pipeline: load → auth → base URL → operations."""
    spec = load_spec(source)
    info = spec.get("info") or {}
    return ApiSpec(
        title=str(info.get("title") or "Imported API"),
        base_url=_base_url(spec),
        operations=extract_operations(spec),
        auth=detect_auth(spec),
    )
