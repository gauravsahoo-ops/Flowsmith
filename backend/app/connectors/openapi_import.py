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
    tags: list[str] = field(default_factory=list)
    request_schema: dict[str, Any] = field(default_factory=dict)
    response_schema: dict[str, Any] = field(default_factory=dict)
    pagination: dict[str, Any] = field(default_factory=dict)
    rate_limits: dict[str, Any] = field(default_factory=dict)
    is_webhook: bool = False


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
    openapi_version: str = "3.0.0"
    webhooks: list[ApiOperation] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


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


def extract_operations(
    spec: dict[str, Any], *, max_ops: int = _MAX_OPS, include: str | None = None,
) -> list[ApiOperation]:
    """Flatten paths+methods into stable operation keys with schemas, pagination, and tags."""
    matcher = re.compile(include, re.IGNORECASE) if include else None
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
            tags = [str(t) for t in (operation.get("tags") or [])]
            path_params = re.findall(r"\{([^}/]+)\}", path)
            query_params: list[ApiParam] = []
            has_body = isinstance(operation.get("requestBody"), dict)

            # Request schema extraction
            request_schema: dict[str, Any] = {}
            if has_body:
                rb = operation.get("requestBody") or {}
                content = (rb.get("content") or {}) if isinstance(rb, dict) else {}
                app_json = content.get("application/json") or content.get("application/x-www-form-urlencoded") or {}
                if isinstance(app_json, dict) and "schema" in app_json:
                    request_schema = app_json["schema"]

            # Response schema extraction
            response_schema: dict[str, Any] = {}
            responses = operation.get("responses") or {}
            success_resp = responses.get("200") or responses.get("201") or responses.get("default") or {}
            if isinstance(success_resp, dict):
                rcontent = success_resp.get("content") or {}
                rapp_json = rcontent.get("application/json") or {}
                if isinstance(rapp_json, dict) and "schema" in rapp_json:
                    response_schema = rapp_json["schema"]

            # Pagination detection
            pagination_info: dict[str, Any] = {}
            for param in operation.get("parameters") or []:
                if not isinstance(param, dict):
                    continue
                location = str(param.get("in") or "")
                pname = str(param.get("name") or "")
                if location in ("body", "formData"):
                    has_body = True
                    continue
                if location != "query":
                    continue
                query_params.append(ApiParam(
                    name=pname,
                    location="query",
                    required=bool(param.get("required")),
                ))
                # Detect pagination patterns
                if pname.lower() in ("page", "page_number", "pagenumber", "offset", "cursor", "starting_after", "pagetoken"):
                    pagination_info["parameter"] = pname
                    pagination_info["type"] = "cursor" if "cursor" in pname.lower() or "after" in pname.lower() or "token" in pname.lower() else "page"
                elif pname.lower() in ("limit", "page_size", "pagesize", "per_page", "count"):
                    pagination_info["limit_parameter"] = pname

            ops.append(ApiOperation(
                operation_key=key, method=method.upper(), path=path, summary=summary,
                path_params=path_params, query_params=query_params, has_body=has_body,
                tags=tags, request_schema=request_schema, response_schema=response_schema,
                pagination=pagination_info,
            ))
            if not matcher and len(ops) >= max_ops:
                break
        if not matcher and len(ops) >= max_ops:
            break
    if matcher:
        ops = [o for o in ops
               if matcher.search(o.operation_key) or matcher.search(f"{o.method} {o.path}")][: _MAX_OPS * 4]
    # Stable output regardless of document ordering quirks.
    ops.sort(key=lambda o: o.operation_key)
    return ops


def extract_webhooks(spec: dict[str, Any]) -> list[ApiOperation]:
    """Extract declared webhooks in OpenAPI 3.1 `webhooks` section."""
    webhooks_dict = spec.get("webhooks") or {}
    results: list[ApiOperation] = []
    if not isinstance(webhooks_dict, dict):
        return results

    for hook_name, item in webhooks_dict.items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() not in ("post", "put", "get"):
                continue
            if not isinstance(operation, dict):
                continue
            key = _slug(f"webhook_{hook_name}_{method}")
            summary = str(operation.get("summary") or f"Webhook for {hook_name}")[:200]
            results.append(ApiOperation(
                operation_key=key,
                method=method.upper(),
                path=f"/webhook/{hook_name}",
                summary=summary,
                is_webhook=True,
            ))
    return results


def parse_spec(source: str | dict[str, Any], *, include: str | None = None) -> ApiSpec:
    """Full pipeline: load → auth → base URL → operations → webhooks."""
    spec = load_spec(source)
    info = spec.get("info") or {}
    openapi_ver = str(spec.get("openapi") or spec.get("swagger") or "3.0.0")
    
    # Collect unique tags
    all_tags = []
    for t in (spec.get("tags") or []):
        if isinstance(t, dict) and "name" in t:
            all_tags.append(str(t["name"]))

    return ApiSpec(
        title=str(info.get("title") or "Imported API"),
        base_url=_base_url(spec),
        operations=extract_operations(spec, include=include),
        auth=detect_auth(spec),
        openapi_version=openapi_ver,
        webhooks=extract_webhooks(spec),
        tags=all_tags,
    )

