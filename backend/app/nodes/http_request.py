"""Universal HTTP Request node — n8n-grade HTTP client.

Covers: GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS · headers · query ·
{path} params · JSON (fields/raw) / form / multipart / raw bodies ·
Bearer / Basic / API-key / OAuth2 auth · timeouts · redirects ·
ignore SSL · response formats · response-size limits · Link-header
pagination · secret redaction.

All outbound traffic flows via ctx.http_client (backed by the shared
httpx.AsyncClient from the execution runtime). SSRF protection is
handled at the SafeHTTPClient layer for connector integrations;
the node validates URLs and applies secret redaction in logs.
"""

from __future__ import annotations

import base64
import json
import shlex
import time
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse, quote, unquote

import logging
import httpx
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

from app.engine.errors import NodeExecutionError
from app.engine.node_base import CONDITIONALLY_IDEMPOTENT, BaseNode, NodeContext, NodeResult, filter_client_kwargs
from app.nodes.registry import register
from app.engine import expressions
from app.credentials.http_auth_builder import get_http_auth_builder
from app.credentials.type_registry import get_credential_type_registry
from app.credentials.provider_registry import get_provider_registry


# ------------------------------------------------------------------
# Helpers — cURL import parser (also used by backend if frontend sends curl string)
# ------------------------------------------------------------------

def parse_curl(curl_str: str) -> dict[str, Any]:
    """Parse a cURL command into HTTPRequestParams-compatible dict.

    Returns a dict with keys like method, url, headers, query, body,
    body_format, auth_type etc.  Incomplete/invalid curl returns partial.
    """
    result: dict[str, Any] = {}
    if not curl_str or not curl_str.strip():
        return result
    # Normalize: strip leading/trailing whitespace, handle line continuations
    curl_str = curl_str.strip().replace("\\\n", " ").replace("\\\r\n", " ")
    try:
        tokens = shlex.split(curl_str)
    except ValueError:
        # fallback: simple split
        tokens = curl_str.split()
    if not tokens:
        return result
    # Remove leading 'curl' token if present
    if tokens[0].lower() == "curl":
        tokens = tokens[1:]
    headers: dict[str, str] = {}
    query: dict[str, str] = {}
    method = None
    url = None
    body = None
    body_format: str = "json"
    auth_type = "none"
    auth_token = ""
    auth_username = ""
    auth_password = ""
    api_key_name = "X-API-Key"
    api_key_in: str = "header"
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-X", "--request"):
            if i + 1 < len(tokens):
                method = tokens[i + 1].upper()
                i += 2
                continue
        elif tok in ("-H", "--header"):
            if i + 1 < len(tokens):
                hdr = tokens[i + 1]
                if ":" in hdr:
                    k, v = hdr.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    # Detect auth header
                    if k.lower() == "authorization" and v.lower().startswith("bearer "):
                        auth_type = "bearer"
                        auth_token = v[7:].strip()
                    elif k.lower() == "authorization" and v.lower().startswith("basic "):
                        try:
                            decoded = base64.b64decode(v[6:].strip()).decode()
                            if ":" in decoded:
                                auth_username, auth_password = decoded.split(":", 1)
                                auth_type = "basic"
                            else:
                                headers[k] = v
                        except Exception:
                            headers[k] = v
                    else:
                        headers[k] = v
                i += 2
                continue
        elif tok in ("-d", "--data", "--data-raw", "--data-binary", "--data-urlencode"):
            if i + 1 < len(tokens):
                data_val = tokens[i + 1]
                # --data-urlencode is form style: "name=value"
                if tok == "--data-urlencode":
                    body_format = "form"
                    if body is None:
                        body = {}
                    if isinstance(body, dict):
                        if "=" in data_val:
                            dk, dv = data_val.split("=", 1)
                            body[dk] = dv
                        else:
                            body[data_val] = ""
                    else:
                        body = {data_val: ""}
                else:
                    # Try to parse as JSON, otherwise raw
                    if body is None:
                        try:
                            parsed = json.loads(data_val)
                            body = parsed
                            body_format = "json"
                        except Exception:
                            body = data_val
                            body_format = "raw"
                    else:
                        body = data_val
                        body_format = "raw"
                # Implicit POST if no method set and data present
                if method is None:
                    method = "POST"
                i += 2
                continue
        elif tok == "--form" or tok == "-F":
            if i + 1 < len(tokens):
                form_val = tokens[i + 1]
                body_format = "multipart"
                if body is None:
                    body = {}
                if isinstance(body, dict) and "=" in form_val:
                    fk, fv = form_val.split("=", 1)
                    # Strip @ for file references
                    fv = fv.lstrip("@")
                    body[fk] = fv
                i += 2
                continue
        elif tok in ("-u", "--user"):
            if i + 1 < len(tokens):
                user_val = tokens[i + 1]
                if ":" in user_val:
                    auth_username, auth_password = user_val.split(":", 1)
                else:
                    auth_username = user_val
                auth_type = "basic"
                i += 2
                continue
        elif tok == "--url":
            if i + 1 < len(tokens):
                url = tokens[i + 1]
                i += 2
                continue
        elif tok in ("-G", "--get"):
            if method is None:
                method = "GET"
            i += 1
            continue
        elif tok.startswith("-"):
            # Unknown flag with optional arg — skip flag and possible value
            # Flags that take values: handled above; others are boolean
            i += 1
            continue
        else:
            # Positional — treat as URL if not yet set
            if url is None and (tok.startswith("http://") or tok.startswith("https://")):
                url = tok
            elif url is None and tok.startswith("'http") or tok.startswith('"http'):
                url = tok.strip("'\"")
            elif url is None and "." in tok:
                # Heuristic: might be URL without scheme
                url = tok.strip("'\"")
            i += 1
            continue

    # URL query string extraction
    if url:
        parsed = urlparse(url)
        if parsed.query:
            qs = parse_qs(parsed.query, keep_blank_values=True)
            for k, vs in qs.items():
                query[k] = vs[0] if len(vs) == 1 else vs[0]
            # Strip query from url for cleaner storage
            url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, "", parsed.fragment))
        result["url"] = url
        # Determine auth_type if headers contain api key style
        # (already handled above)

    if method:
        result["method"] = method
    if headers:
        result["headers"] = headers
        result["sendHeaders"] = True
    if query:
        result["query"] = query
        result["sendQuery"] = True
    if body is not None:
        result["body"] = body
        result["sendBody"] = True
        if body_format == "form":
            result["body_format"] = "form"
            result["bodyContentType"] = "form-urlencoded"
        elif body_format == "multipart":
            result["body_format"] = "multipart"
            result["bodyContentType"] = "multipart-form-data"
        elif body_format == "raw":
            result["body_format"] = "raw"
            result["bodyContentType"] = "raw"
        else:
            result["body_format"] = "json"
            result["bodyContentType"] = "json"
        # Detect JSON fields vs raw: if body is dict -> fields mode, else raw
        if isinstance(body, dict):
            result["jsonBodyMode"] = "fields"
        elif isinstance(body, str):
            result["jsonBodyMode"] = "raw"
            # For raw, store in raw body field behavior
            if body_format != "raw":
                try:
                    json.loads(body)
                    result["bodyContentType"] = "json"
                except Exception:
                    result["bodyContentType"] = "raw"
    if auth_type != "none":
        result["auth_type"] = auth_type
        if auth_token:
            result["auth_token"] = auth_token
        if auth_username:
            result["auth_username"] = auth_username
        if auth_password:
            result["auth_password"] = auth_password
        if api_key_name != "X-API-Key":
            result["api_key_name"] = api_key_name
        result["api_key_in"] = api_key_in

    return result


# ------------------------------------------------------------------
# Params
# ------------------------------------------------------------------

class BodyParam(BaseModel):
    name: str = Field(min_length=1)
    value: Any = Field(default="")


class QueryParamDef(BaseModel):
    name: str = Field(min_length=1)
    value: Any = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def _strip_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and "name" in data and isinstance(data["name"], str):
            data["name"] = data["name"].strip()
        return data


class HeaderParamDef(BaseModel):
    name: str = Field(min_length=1)
    value: Any = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def _strip_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and "name" in data and isinstance(data["name"], str):
            data["name"] = data["name"].strip()
        return data


class HTTPRequestParams(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    url: str = Field(min_length=1, description="Target URL; supports {placeholder} path params and {{ expressions }}.")

    # Toggles — n8n-style dynamic sections
    sendQuery: bool = Field(default=False, description="Whether to send query parameters.")
    sendHeaders: bool = Field(default=False, description="Whether to send custom headers.")
    sendBody: bool = Field(default=False, description="Whether to send a request body.")

    # Path params (legacy)
    path_params: dict[str, str] = Field(default_factory=dict, description="{placeholder} substitution values.")
    # Query and headers as dicts (canonical); UI edits as lists and syncs here
    query: dict[str, Any] = Field(default_factory=dict, description="Query string parameters.")
    headers: dict[str, str] = Field(default_factory=dict)

    # Body
    body: Any = Field(default=None, description="JSON payload / form mapping / raw string.")
    body_format: Literal["json", "form", "raw", "multipart"] = Field(default="json")
    # Extended content-type for UI
    bodyContentType: Literal["json", "form-urlencoded", "multipart-form-data", "raw"] | None = Field(default=None)
    # JSON mode: fields vs raw
    jsonBodyMode: Literal["fields", "raw"] = Field(default="fields")

    # For list-based editing (UI sync helpers) — optional, not canonical but persisted
    queryParameters: list[QueryParamDef] | None = Field(default=None, description="Query params as list for UI.")
    headerParameters: list[HeaderParamDef] | None = Field(default=None, description="Headers as list for UI.")
    bodyParameters: list[BodyParam] | None = Field(default=None, description="Body fields as list for UI (JSON fields mode).")
    # Raw body content when jsonBodyMode=raw or bodyContentType=raw
    rawBody: str | None = Field(default=None, description="Raw body content (JSON string, XML, text).")
    # Query parameters: fields vs JSON mode (n8n-like)
    queryMode: Literal["fields", "json"] = Field(default="fields", description="How query parameters are specified: fields or JSON.")
    queryJson: str | None = Field(default=None, description="JSON object for query parameters when queryMode==json.")
    # Headers: fields vs JSON mode (n8n-like)
    headerMode: Literal["fields", "json"] = Field(default="fields", description="How headers are specified: fields or JSON.")
    headerJson: str | None = Field(default=None, description="JSON object for headers when headerMode==json.")

    # Auth — new high-level mode + legacy for compat
    authentication: Literal["none", "predefined", "generic"] = Field(default="none", description="High-level auth mode (n8n-style).")
    predefinedType: str = Field(default="", description="Predefined credential type id when authentication==predefined (e.g., salesforce-oauth2).")
    # Auth — generic providers (8) plus legacy api_key for compat
    auth_type: Literal["none", "bearer", "basic", "api_key", "oauth2", "header", "query", "digest", "custom", "oauth1"] = "none"
    auth_token: str = Field(default="", description="Bearer token / API key value / OAuth2 token.")
    auth_username: str = Field(default="", description="Basic auth username.")
    auth_password: str = Field(default="", description="Basic auth password.")
    api_key_name: str = Field(default="X-API-Key", description="API key header/query name.")
    api_key_in: Literal["header", "query"] = "header"

    # Reliability / limits
    timeout_seconds: float = Field(default=30.0, ge=0.5, le=300, description="Request timeout seconds.")
    max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    follow_redirects: bool = True
    max_redirects: int = Field(default=5, ge=0, le=50)
    ignore_ssl_issues: bool = Field(default=False, description="Skip TLS verification (insecure).")
    response_format: Literal["json", "text", "auto"] = Field(default="auto")
    # Pagination (GET only): follow RFC 5988 Link rel="next"
    pagination_mode: Literal["none", "link_header"] = "none"
    max_pages: int = Field(default=1, ge=1, le=100)
    idempotency_key: str | None = Field(default=None)
    # Import cURL passthrough (if frontend sends raw curl, backend parses server-side)
    importCurl: str | None = Field(default=None, description="Raw cURL string to import (parsed on validate).")

    @model_validator(mode="before")
    @classmethod
    def _handle_legacy_and_lists(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # Handle new authentication mode (none/predefined/generic) with backward compat
        # Legacy workflows have only auth_type (e.g., "bearer") and no authentication field
        if "authentication" not in d or d["authentication"] not in ("none", "predefined", "generic"):
            old_auth = d.get("auth_type", "none")
            # If old authentication value was actually an auth_type string stored in 'authentication' (legacy bug), fix it
            if "authentication" in d and d["authentication"] in ("bearer","basic","api_key","oauth2","header","query","digest","custom","oauth1","none"):
                old_auth = d.pop("authentication")
                d["authentication"] = "generic" if old_auth != "none" else "none"
                d["auth_type"] = old_auth
            elif old_auth != "none" and old_auth in ("bearer","basic","header","query","digest","custom","oauth2","oauth1","api_key"):
                d["authentication"] = "generic"
            elif d.get("predefinedType"):
                d["authentication"] = "predefined"
            else:
                d["authentication"] = "none" if old_auth == "none" else "generic"
        # Normalize: if generic but auth_type is still none, keep none
        if d.get("authentication") == "generic" and not d.get("auth_type"):
            d["auth_type"] = "bearer"
        # Sanitize redacted secret values that leaked into auth_type/api_key_in fields
        _valid_auth_types = {"none", "bearer", "basic", "api_key", "oauth2", "header", "query", "digest", "custom", "oauth1"}
        if d.get("auth_type") and d["auth_type"] not in _valid_auth_types:
            d["auth_type"] = "none"
        if d.get("api_key_in") and d["api_key_in"] not in ("header", "query"):
            d["api_key_in"] = "header"
        if d.get("authentication") == "predefined" and not d.get("predefinedType"):
            # Try to infer from credential? keep empty for validation to catch
            pass
        # If cURL import string present, parse and merge (provided fields win over curl)
        curl = d.pop("importCurl", None)
        if curl and isinstance(curl, str) and curl.strip():
            parsed = parse_curl(curl)
            for k, v in parsed.items():
                if k not in d or d[k] in (None, "", {}, []):
                    d[k] = v
        # Sync list-based UI fields to dicts if present
        if d.get("queryParameters") is not None and isinstance(d["queryParameters"], list):
            q: dict[str, Any] = {}
            for item in d["queryParameters"]:
                if isinstance(item, dict) and item.get("name"):
                    q[str(item["name"]).strip()] = item.get("value", "")
            # Only override query if query is empty or list is non-empty
            if q or not d.get("query"):
                d["query"] = q
                if q:
                    d["sendQuery"] = True
        elif d.get("query") and isinstance(d["query"], dict):
            d["query"] = {str(k).strip(): v for k, v in d["query"].items() if str(k).strip()}
        # Query JSON mode: if queryMode is json and queryJson is present, parse and set query
        if d.get("queryMode") == "json" and d.get("queryJson") is not None:
            qj = d.get("queryJson")
            if isinstance(qj, str) and qj.strip():
                try:
                    parsed = json.loads(qj)
                    if isinstance(parsed, dict):
                        if d.get("sendQuery"):
                            d["query"] = {str(k): v for k, v in parsed.items()}
                except json.JSONDecodeError:
                    pass
            elif isinstance(qj, dict):
                if d.get("sendQuery"):
                    d["query"] = {str(k): v for k, v in qj.items()}
        if not d.get("queryMode"):
            d["queryMode"] = "fields"
        if d.get("headerParameters") is not None and isinstance(d["headerParameters"], list):
            h: dict[str, str] = {}
            for item in d["headerParameters"]:
                if isinstance(item, dict) and item.get("name"):
                    h[str(item["name"])] = str(item.get("value", ""))
            if h or not d.get("headers"):
                d["headers"] = h
                if h:
                    d["sendHeaders"] = True
        # Header JSON mode: if headerMode is json and headerJson is present, parse and set headers
        if d.get("headerMode") == "json" and d.get("headerJson") is not None:
            hj = d.get("headerJson")
            if isinstance(hj, str) and hj.strip():
                try:
                    parsed = json.loads(hj)
                    if isinstance(parsed, dict):
                        # Only set headers from JSON if sendHeaders is True
                        if d.get("sendHeaders"):
                            d["headers"] = {str(k): str(v) for k, v in parsed.items()}
                except json.JSONDecodeError:
                    # Let after validator handle the error
                    pass
            elif isinstance(hj, dict):
                if d.get("sendHeaders"):
                    d["headers"] = {str(k): str(v) for k, v in hj.items()}
        # Default headerMode if not set
        if not d.get("headerMode"):
            d["headerMode"] = "fields"
        if d.get("bodyParameters") is not None and isinstance(d["bodyParameters"], list):
            b: dict[str, Any] = {}
            for item in d["bodyParameters"]:
                if isinstance(item, dict) and item.get("name"):
                    b[str(item["name"])] = item.get("value", "")
            if b or not d.get("body"):
                # Only apply if json mode fields
                mode = d.get("jsonBodyMode", "fields")
                ct = d.get("bodyContentType", "json")
                if mode == "fields" and ct in (None, "json", "form-urlencoded", "multipart-form-data"):
                    if b:
                        d["body"] = b
                        d["sendBody"] = True
                        if ct is None:
                            d["bodyContentType"] = "json"
                            d["body_format"] = "json"
        # Raw body sync
        if d.get("rawBody") is not None and isinstance(d["rawBody"], str) and d["rawBody"] != "":
            if d.get("jsonBodyMode") == "raw" or d.get("bodyContentType") == "raw" or d.get("body_format") == "raw":
                d["body"] = d["rawBody"]
                if d["body"] not in (None, ""):
                    d["sendBody"] = True
        # Infer bodyContentType from body_format if not set
        if not d.get("bodyContentType") and d.get("body_format"):
            bf = d["body_format"]
            mapping = {"json": "json", "form": "form-urlencoded", "multipart": "multipart-form-data", "raw": "raw"}
            d["bodyContentType"] = mapping.get(bf, bf)
        if not d.get("body_format") and d.get("bodyContentType"):
            rev = {"json": "json", "form-urlencoded": "form", "multipart-form-data": "multipart", "raw": "raw"}
            d["body_format"] = rev.get(d["bodyContentType"], "json")
        # Infer toggles from content presence for backward compat (legacy workflows)
        # Note: do not override explicit False if data present — we set True for compat
        if d.get("query") and isinstance(d["query"], dict) and len(d["query"]) > 0:
            d.setdefault("sendQuery", True)
        if d.get("headers") and isinstance(d["headers"], dict) and len(d["headers"]) > 0:
            d.setdefault("sendHeaders", True)
        # Body: if body is non-None and not just empty, infer sendBody
        if d.get("body") is not None and d.get("body") != "" and d.get("body") != {}:
            # For GET/HEAD we don't send body regardless
            method = d.get("method", "GET")
            if method not in ("GET", "HEAD"):
                d.setdefault("sendBody", True)
        return d

    @model_validator(mode="after")
    def _validate_url_and_body(self) -> "HTTPRequestParams":
        # High-level authentication validation (n8n-style)
        if self.authentication == "predefined" and not self.predefinedType:
            raise ValueError("Predefined Credential Type is required when Authentication is 'Predefined Credential Type'.")
        if self.authentication == "generic" and self.auth_type in ("none", ""):
            # Downgrade to none — user selected Generic but didn't pick a sub-type
            self.authentication = "none"
            self.auth_type = "none"
        # URL validation: allow expressions like {{ $json.url }} — skip check if contains {{
        if self.url and "{{" in self.url:
            return self
        if self.url:
            parsed = urlparse(self.url)
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                raise ValueError(f"URL must start with http:// or https:// (got '{self.url}').")
            if not parsed.netloc:
                raise ValueError(f"URL is missing a host (got '{self.url}').")
        # Body: validate JSON when raw mode
        if self.sendBody and self.jsonBodyMode == "raw" and self.bodyContentType == "json":
            raw = self.rawBody if self.rawBody is not None else (self.body if isinstance(self.body, str) else None)
            if raw and "{{" not in raw:
                raw_stripped = raw.strip()
                if raw_stripped:
                    try:
                        json.loads(raw_stripped)
                    except json.JSONDecodeError as e:
                        raise ValueError(f"Invalid JSON body: {e.msg} at line {e.lineno}.")
        # Query JSON validation
        if self.sendQuery and self.queryMode == "json" and self.queryJson is not None:
            qj = self.queryJson.strip() if isinstance(self.queryJson, str) else ""
            if qj and "{{" not in qj:
                try:
                    parsed = json.loads(qj)
                    if not isinstance(parsed, dict):
                        raise ValueError("Query Parameters JSON must be an object, e.g., {\"updated_after\": \"2026-01-01\"}.")
                    for k in parsed.keys():
                        if not str(k).strip():
                            raise ValueError("Query parameter name must not be empty.")
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid Query Parameters JSON: {e.msg} at line {e.lineno}.")
        if self.sendQuery and self.queryMode == "fields":
            for k in self.query.keys():
                if not str(k).strip():
                    raise ValueError("Query parameter name must not be empty.")
        if self.sendHeaders and self.headerMode == "json" and self.headerJson is not None:
            hj = self.headerJson.strip() if isinstance(self.headerJson, str) else ""
            if hj and "{{" not in hj:
                try:
                    parsed = json.loads(hj)
                    if not isinstance(parsed, dict):
                        raise ValueError("Headers JSON must be an object, e.g., {\"Accept\": \"application/json\"}.")
                    for k in parsed.keys():
                        if not str(k).strip():
                            raise ValueError("Header name must not be empty.")
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid Headers JSON: {e.msg} at line {e.lineno}.")
        if self.sendHeaders and self.headerMode == "fields":
            for k in self.headers.keys():
                if not str(k).strip():
                    raise ValueError("Header name must not be empty.")
        return self


def _next_link_target(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        seg = part.strip()
        if 'rel="next"' in seg or seg.lower().endswith("rel=next"):
            target = seg.split(";", 1)[0].strip().lstrip("<").rstrip(">")
            return target or None
    return None


@register
class HTTPRequestNode(BaseNode[HTTPRequestParams]):
    node_type = "http_request"
    display_name = "HTTP Request"
    version = 3
    description = (
        "Universal REST client: any method, headers/query/path params, "
        "JSON/form/multipart/raw bodies, API-key/Bearer/Basic auth, timeouts, "
        "redirects, SSL options, Link-header pagination and response-size limits."
    )
    category = "Actions"
    icon = "🌐"
    parameters_schema = HTTPRequestParams
    credential_types = ["http", "basic_auth", "bearer_auth", "header_auth", "query_auth", "digest_auth", "custom_auth", "oauth2", "oauth1", "api_key", "pat", "jwt", "service_account", "aws_iam", "aws_assume_role", "salesforce", "hubspot", "google_calendar", "google_sheets", "gmail", "google_drive", "slack", "github", "notion", "jira", "discord", "stripe", "mongodb", "redis", "airtable", "shopify", "postgres", "mysql", "database", "smtp", "llm", "telegram", "microsoft_graph"]
    idempotency = CONDITIONALLY_IDEMPOTENT
    resolves_own_expressions = False  # Let executor handle per-item $json resolution

    @staticmethod
    def _validate_url_ssrf(url: str) -> None:
        """Block requests to internal/private IPs (S10: SSRF protection)."""
        import ipaddress
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = (parsed.hostname or "").strip("[]")
        if not host:
            return
        # Allow localhost in development mode
        from app.config import get_settings
        if get_settings().app_env != "production" and host in ("localhost", "127.0.0.1", "::1"):
            return
        # Check for IP addresses
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise NodeExecutionError(
                    f"SSRF blocked: '{host}' is a private/internal address.",
                    code="SSRF_BLOCKED", node_id="http_request", retryable=False,
                )
        except ValueError:
            pass  # Not an IP, check hostname patterns
        # Block common internal hostnames
        blocked = ("metadata.google.internal", "169.254.169.254", "localhost")
        if host.lower() in blocked:
            raise NodeExecutionError(
                f"SSRF blocked: '{host}' is not allowed.",
                code="SSRF_BLOCKED", node_id="http_request", retryable=False,
            )

    _filter_kwargs = staticmethod(filter_client_kwargs)

    async def _do_request(self, ctx, params, url, headers, query, json_body, data, files=None):
        # Build kwargs for client.request
        kwargs: dict[str, Any] = {
            "headers": headers or None,
            "params": query or None,
            "json": json_body,
            "data": data,
            "timeout": params.timeout_seconds,
            "follow_redirects": params.follow_redirects,
            "max_response_bytes": params.max_response_bytes,
        }
        if files is not None:
            kwargs["files"] = files
        # Handle SSL and redirect limits via client options if supported
        # The worker's httpx client is plain; we pass verify/max_redirects if filter allows
        if params.ignore_ssl_issues:
            kwargs["verify"] = False
        if not params.follow_redirects:
            kwargs["follow_redirects"] = False
        # max_redirects is mostly handled by client config; filter will drop if unsupported
        filtered = self._filter_kwargs(ctx.http_client, kwargs)
        # For plain httpx client, max_redirects is in client setup, not per-request.
        # We handle it by checking response history length after.
        return await ctx.http_client.request(params.method, url, **filtered)

    async def run(self, ctx: NodeContext, params: HTTPRequestParams, input_items: list[dict[str, Any]]) -> NodeResult:
        if not input_items:
            input_items = [{}]

        if len(input_items) == 1:
            item = input_items[0]
            per_ctx = dict(ctx.expression_context) if ctx.expression_context else {}
            per_ctx["$json"] = item
            raw = params.model_dump()
            resolved_raw = expressions.resolve(raw, per_ctx)
            try:
                per_params = self.build_params(resolved_raw)
            except Exception as exc:
                raise NodeExecutionError(f"Invalid parameters for item {item}: {exc}", code="BAD_REQUEST", node_id=self.node_type, retryable=False) from exc
            return await self._run_single(ctx, per_params, item)

        output_items: list[dict[str, Any]] = []
        for item in input_items:
            per_ctx = dict(ctx.expression_context) if ctx.expression_context else {}
            per_ctx["$json"] = item
            raw = params.model_dump()
            resolved_raw = expressions.resolve(raw, per_ctx)
            try:
                per_params = self.build_params(resolved_raw)
            except Exception as exc:
                raise NodeExecutionError(f"Invalid parameters for item {item}: {exc}", code="BAD_REQUEST", node_id=self.node_type, retryable=False) from exc
            try:
                result = await self._run_single(ctx, per_params, item)
                output_items.extend(result.output_items or [])
            except NodeExecutionError:
                raise
        return NodeResult(output_items=output_items)

    async def _run_single(self, ctx: NodeContext, params: HTTPRequestParams, single_item: dict[str, Any]) -> NodeResult:
        if params.idempotency_key and params.method in ("GET", "HEAD", "PUT", "DELETE"):
            cached = await ctx.storage.get(f"idem:{params.idempotency_key}")
            if cached is not None:
                return NodeResult(output_items=[cached])

        url = self._build_url(params)
        # S10: SSRF protection — block internal/private IPs
        if url and "{{" not in url:
            self._validate_url_ssrf(url)
        # Headers: handle sendHeaders toggle + headerMode (fields vs json)
        headers: dict[str, str] = {}
        if params.sendHeaders:
            if getattr(params, 'headerMode', 'fields') == "json" and getattr(params, 'headerJson', None) is not None:
                hj = params.headerJson.strip() if isinstance(params.headerJson, str) else ""
                if hj:
                    try:
                        parsed = json.loads(hj)
                        if not isinstance(parsed, dict):
                            raise NodeExecutionError("Headers JSON must be an object.", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
                        for k, v in parsed.items():
                            if not str(k).strip():
                                raise NodeExecutionError("Header name must not be empty.", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
                            headers[str(k).strip()] = str(v) if v is not None else ""
                    except json.JSONDecodeError as e:
                        raise NodeExecutionError(f"Invalid Headers JSON: {e.msg} at line {e.lineno}.", code="BAD_REQUEST", node_id=self.node_type, retryable=False) from e
                    except NodeExecutionError:
                        raise
                    except Exception as e:
                        raise NodeExecutionError(f"Invalid Headers JSON: {e}", code="BAD_REQUEST", node_id=self.node_type, retryable=False) from e
            else:
                for k in list(params.headers.keys()):
                    if not str(k).strip():
                        raise NodeExecutionError("Header name must not be empty.", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
                headers = {str(k).strip(): str(v) if v is not None else "" for k, v in (params.headers or {}).items() if str(k).strip()}
        else:
            # sendHeaders is False: do not send custom headers (strict n8n behavior)
            # But for backward compat, if headers is non-empty and sendHeaders was not explicitly set to False, allow
            if params.headers and "sendHeaders" not in params.model_fields_set:
                # Legacy: headers present but toggle not explicitly set, treat as enabled
                headers = {str(k).strip(): str(v) if v is not None else "" for k, v in params.headers.items() if str(k).strip()}
            else:
                headers = {}

        # Query parameters: handle sendQuery toggle + queryMode (fields vs json)
        query: dict[str, Any] = {}
        if params.sendQuery:
            if getattr(params, 'queryMode', 'fields') == "json" and getattr(params, 'queryJson', None) is not None:
                qj = params.queryJson.strip() if isinstance(params.queryJson, str) else ""
                if qj:
                    try:
                        parsed = json.loads(qj)
                        if not isinstance(parsed, dict):
                            raise NodeExecutionError("Query JSON must be an object.", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
                        for k, v in parsed.items():
                            if not str(k).strip():
                                raise NodeExecutionError("Query parameter name must not be empty.", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
                            query[str(k).strip()] = str(v) if v is not None else ""
                    except json.JSONDecodeError as e:
                        raise NodeExecutionError(f"Invalid Query JSON: {e.msg} at line {e.lineno}.", code="BAD_REQUEST", node_id=self.node_type, retryable=False) from e
                    except NodeExecutionError:
                        raise
                    except Exception as e:
                        raise NodeExecutionError(f"Invalid Query JSON: {e}", code="BAD_REQUEST", node_id=self.node_type, retryable=False) from e
            else:
                for k in list((params.query or {}).keys()):
                    if not str(k).strip():
                        raise NodeExecutionError("Query parameter name must not be empty.", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
                query = {str(k).strip(): str(v) if v is not None else "" for k, v in (params.query or {}).items() if str(k).strip()}
        else:
            if params.query and "sendQuery" not in params.model_fields_set:
                query = {str(k).strip(): str(v) if v is not None else "" for k, v in params.query.items() if str(k).strip()}
            else:
                query = {}

        # Handle credentials-based auth augmentation (OAuth2 etc) via ctx.credentials
        await self._apply_auth(params, headers, query, ctx)

        data = None
        json_body = None
        files = None
        wants_body = params.sendBody and params.body is not None and params.method not in ("GET", "HEAD")
        # Legacy compat: if body present but sendBody false due to old workflow, still send if method allows
        if not params.sendBody and params.body is not None and params.body != "" and params.body != {}:
            if params.method not in ("GET", "HEAD"):
                # If raw data has body field but toggle is default false (legacy), respect body presence
                if "sendBody" not in params.model_fields_set:
                    wants_body = True
        if wants_body:
            ct = params.bodyContentType or {"json": "json", "form": "form-urlencoded", "multipart": "multipart-form-data", "raw": "raw"}.get(params.body_format, "json")
            if ct == "json":
                if params.jsonBodyMode == "raw":
                    raw_str = params.rawBody if params.rawBody is not None else (params.body if isinstance(params.body, str) else json.dumps(params.body or {}))
                    if isinstance(raw_str, str):
                        # Evaluate if raw_str is JSON string with expressions already resolved
                        try:
                            json_body = json.loads(raw_str) if raw_str.strip() else {}
                        except json.JSONDecodeError as e:
                            raise NodeExecutionError(f"Invalid JSON body: {e.msg} at line {e.lineno}.", code="BAD_REQUEST", node_id=self.node_type, retryable=False) from e
                    else:
                        json_body = raw_str
                else:
                    # Fields mode: body is dict
                    json_body = params.body if isinstance(params.body, dict) else {}
                    # If bodyParameters present and body empty/different, handled in validator
            elif ct == "form-urlencoded":
                self._require_form_object(params)
                form: dict[str, Any] = {k: str(v) if not isinstance(v, str) else v for k, v in (params.body or {}).items()}
                data = urlencode(form)
                headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            elif ct == "multipart-form-data":
                # For multipart, use data dict and let httpx set boundary
                if isinstance(params.body, dict):
                    # httpx expects files for binary, data for fields
                    # We send as data + files split: if value looks like file content, treat as file
                    # Simplify: send as data with proper header; httpx will not auto-boundary for data string
                    # Use files dict for multipart
                    files = {}
                    data_dict: dict[str, Any] = {}
                    for k, v in params.body.items():
                        if isinstance(v, dict) and "filename" in v:
                            files[k] = (v.get("filename", k), v.get("content", ""), v.get("contentType", "application/octet-stream"))
                        else:
                            data_dict[k] = str(v) if not isinstance(v, str) else v
                    if files:
                        data = data_dict
                    else:
                        # No files, send as form but with multipart content-type suggestion (httpx handles)
                        # For multipart without files, still use urlencode but with boundary is not needed; send as data
                        data = data_dict
                        # Let httpx set multipart header if files present
                        if not headers.get("Content-Type"):
                            # httpx will set multipart boundary automatically when files is not None
                            pass
                else:
                    data = str(params.body) if params.body is not None else ""
            else:  # raw
                raw_content = params.rawBody if params.rawBody is not None else (params.body if isinstance(params.body, str) else str(params.body or ""))
                data = raw_content
                # Set content-type if not already set; default text/plain
                if "Content-Type" not in headers and "content-type" not in {k.lower(): v for k, v in headers.items()}:
                    # Infer from raw content
                    stripped = (raw_content or "").strip()
                    if stripped.startswith("<"):
                        headers.setdefault("Content-Type", "application/xml")
                    elif stripped.startswith("{") or stripped.startswith("["):
                        headers.setdefault("Content-Type", "application/json")
                    else:
                        headers.setdefault("Content-Type", "text/plain")

        started = time.monotonic()
        try:
            response = await self._do_request(ctx, params, url, headers, query, json_body, data, files)
        except httpx.TimeoutException as exc:
            raise NodeExecutionError(
                f"The external API did not respond within {params.timeout_seconds}s.",
                code="HTTP_TIMEOUT", node_id=self.node_type, retryable=True,
            ) from exc
        except NodeExecutionError:
            raise
        except httpx.RequestError as exc:
            # Check if it's SSL-related when ignore_ssl_issues might help hint
            msg = str(exc)
            if "SSL" in msg or "certificate" in msg.lower():
                raise NodeExecutionError(
                    f"HTTP request failed (SSL): {exc}. Try enabling 'Ignore SSL Issues' if appropriate.",
                    code="HTTP_REQUEST_FAILED", node_id=self.node_type, retryable=True,
                ) from exc
            raise NodeExecutionError(
                f"HTTP request failed: {exc}",
                code="HTTP_REQUEST_FAILED", node_id=self.node_type, retryable=True,
            ) from exc
        elapsed_ms = (time.monotonic() - started) * 1000

        # Check redirect limit manually if needed
        if not params.follow_redirects and response.history:
            # Should not happen as client should not follow, but ensure
            pass
        if params.follow_redirects and len(response.history) > params.max_redirects:
            raise NodeExecutionError(
                f"Too many redirects ({len(response.history)} > {params.max_redirects}).",
                code="HTTP_TOO_MANY_REDIRECTS", node_id=self.node_type, retryable=False,
            )

        # Pagination (GET + link_header)
        if (
            params.pagination_mode == "link_header"
            and params.method == "GET"
            and response.status_code < 400
        ):
            merged_result = await self._follow_link_pagination(ctx, params, response, url, headers, query)
            if merged_result is not None:
                return merged_result

        # On HTTP 401 or INVALID_SESSION_ID: attempt automatic token refresh & single retry
        is_auth_failure = response.status_code == 401 or (
            response.status_code >= 400 and "INVALID_SESSION_ID" in getattr(response, "text", "")
        )
        if is_auth_failure and ctx and ctx.credentials:
            sf_creds = ctx.credentials.get("salesforce")
            if isinstance(sf_creds, dict) and (sf_creds.get("refresh_token") or sf_creds.get("username")):
                try:
                    from app.providers.salesforce import SalesforceProviderClient
                    sf_client = SalesforceProviderClient()
                    sf_client._token = None
                    sf_client._token_expires_at = 0.0
                    sf_creds_copy = dict(sf_creds)
                    sf_creds_copy["access_token"] = ""
                    sf_creds_copy["expires_at"] = 0
                    fresh_token = await sf_client.authenticate(sf_creds_copy)
                    if fresh_token:
                        sf_creds["access_token"] = fresh_token
                        # Update all case-insensitive variations of Authorization header
                        for hk in list(headers.keys()):
                            if hk.lower() == "authorization":
                                del headers[hk]
                        headers["Authorization"] = f"Bearer {fresh_token}"
                        response = await self._do_request(ctx, params, url, headers, query, json_body, data, files)
                        elapsed_ms = (time.monotonic() - started) * 1000
                        logger.info(
                            "Auto-refreshed expired Salesforce session on 401 and retried HTTP request (new status: %s)",
                            response.status_code,
                        )
                        # Persist renewed token to credential in DB
                        if sf_creds.get("_credential_id"):
                            try:
                                import json as _json
                                from app.db import get_session
                                from app.models.credential import Credential
                                from app.security.crypto import encrypt_text, decrypt_text
                                with get_session() as db_sess:
                                    c_rec = db_sess.get(Credential, sf_creds["_credential_id"])
                                    if c_rec:
                                        c_dict = _json.loads(decrypt_text(c_rec.data))
                                        c_dict["access_token"] = fresh_token
                                        c_rec.data = encrypt_text(_json.dumps(c_dict))
                                        db_sess.commit()
                            except Exception:
                                pass
                except Exception as ex:
                    logger.warning("Auto-refresh for Salesforce in HTTPRequestNode failed: %s", ex)
                    if "invalid_grant" in str(ex).lower() or "expired access/refresh token" in str(ex).lower():
                        raise NodeExecutionError(
                            "Salesforce session expired and auto-refresh failed: The refresh token itself has expired on Salesforce (invalid_grant: expired access/refresh token). Please click 'Reconnect' on your Salesforce credential in Credentials page.",
                            code="AUTH_FAILED",
                            node_id=self.node_type,
                            retryable=False,
                            details={"original_error": str(ex)},
                        ) from ex
            elif "oauth2" in ctx.credentials and isinstance(ctx.credentials["oauth2"], dict):
                oauth_creds = ctx.credentials["oauth2"]
                if oauth_creds.get("refresh_token"):
                    try:
                        from app.credentials.oauth_manager import get_oauth_manager
                        mgr = get_oauth_manager()
                        refreshed = await mgr.refresh(oauth_creds)
                        fresh_token = refreshed.get("access_token")
                        if fresh_token:
                            oauth_creds["access_token"] = fresh_token
                            for hk in list(headers.keys()):
                                if hk.lower() == "authorization":
                                    del headers[hk]
                            headers["Authorization"] = f"Bearer {fresh_token}"
                            response = await self._do_request(ctx, params, url, headers, query, json_body, data, files)
                            elapsed_ms = (time.monotonic() - started) * 1000
                            logger.info(
                                "Auto-refreshed expired OAuth2 token on 401 and retried HTTP request (new status: %s)",
                                response.status_code,
                            )
                    except Exception as ex:
                        logger.warning("Auto-refresh for OAuth2 in HTTPRequestNode failed: %s", ex)

        item = await self._to_item(ctx, params, response, elapsed_ms, url, headers, query)
        # Handle HTTP error status codes — don't auto-succeed on 4xx/5xx
        if response.status_code >= 400:
            # Check continue_on_error from node settings (spec 8.3) — if allowed, emit error item but don't fail
            # The engine handles continue_on_error at executor level; here we just prepare error details
            # We still raise NodeExecutionError so engine can apply continue_on_error logic
            raise NodeExecutionError(
                f"HTTP {response.status_code} {response.reason_phrase or ''}: {item.get('body') if isinstance(item.get('body'), str) else json.dumps(item.get('body', ''))[:500]}",
                code=f"HTTP_{response.status_code}",
                node_id=self.node_type,
                retryable=response.status_code in (429, 500, 502, 503, 504),
                details={"statusCode": response.status_code, "headers": dict(response.headers), "body": item.get("body")},
            )

        return NodeResult(output_items=[item])

    # ------------------------------------------------------------------

    def _build_url(self, p: HTTPRequestParams) -> str:
        url = p.url
        for key, val in (p.path_params or {}).items():
            url = url.replace("{" + key + "}", str(val))
        if "{" in url and "}" in url:
            raise NodeExecutionError(
                "Unresolved {placeholder} in URL after path_params substitution.",
                code="BAD_REQUEST", node_id=self.node_type, retryable=False,
            )
        return url

    def _require_form_object(self, p: HTTPRequestParams) -> None:
        if not isinstance(p.body, dict):
            raise NodeExecutionError(
                "bodyContentType=form-urlencoded requires a JSON object body.",
                code="BAD_REQUEST", node_id=self.node_type, retryable=False,
            )

    async def _apply_auth(self, p: HTTPRequestParams, headers: dict[str, str], query: dict[str, Any], ctx: NodeContext | None = None) -> None:
        # New architecture: resolve via CredentialResolver → AuthProviderRegistry → HttpAuthBuilder
        # The worker already resolved credentials into ctx.credentials = {type: decrypted_data}
        # We delegate to provider if a credential is present; otherwise fallback to inline legacy.
        applied = False
        if ctx and ctx.credentials and isinstance(ctx.credentials, dict):
            type_reg = get_credential_type_registry()
            builder = get_http_auth_builder()
            prov_reg = get_provider_registry()
            for cred_type, cred_data in list(ctx.credentials.items()):
                if not isinstance(cred_data, dict):
                    continue
                # Determine provider_id
                provider_id: str | None = None
                entry = type_reg.get(cred_type)
                if entry:
                    provider_id = entry.get("provider")
                    # Check implemented flag — if not implemented, fail fast (spec CRITICAL RULE)
                    if not entry.get("implemented"):
                        raise NodeExecutionError(
                            f"Authentication provider '{provider_id}' for credential type '{cred_type}' is not implemented yet. Please choose a different credential type.",
                            code="CREDENTIAL_PROVIDER_NOT_IMPLEMENTED",
                            node_id=self.node_type,
                            retryable=False,
                        )
                else:
                    # Legacy http type or unknown — infer from params
                    if cred_type == "http":
                        if p.auth_type == "bearer":
                            provider_id = "bearer"
                        elif p.auth_type == "basic":
                            provider_id = "basic"
                        elif p.auth_type == "api_key":
                            provider_id = "header" if p.api_key_in == "header" else "query"
                        elif p.auth_type == "oauth2":
                            provider_id = "oauth2"
                        elif cred_data.get("api_key"):
                            provider_id = "bearer"
                        else:
                            continue
                    elif cred_type == "salesforce":
                        provider_id = "salesforce"
                    else:
                        continue
                if not provider_id:
                    continue
                # Salesforce: skip provider lookup (no auth-provider registered), handle directly below
                if provider_id == "salesforce":
                    pass
                else:
                    # Verify provider exists and is implemented
                    provider = prov_reg.get(provider_id) or prov_reg.get_by_auth_type(provider_id)
                    if provider is None:
                        raise NodeExecutionError(
                            f"Authentication provider '{provider_id}' for credential type '{cred_type}' is not implemented yet. Please choose a different credential type.",
                            code="CREDENTIAL_PROVIDER_NOT_IMPLEMENTED",
                            node_id=self.node_type,
                            retryable=False,
                        )
                    if not getattr(provider, "implemented", True):
                        raise NodeExecutionError(
                            f"Authentication provider '{provider_id}' for credential type '{cred_type}' is not implemented yet. Please choose a different credential type.",
                            code="CREDENTIAL_PROVIDER_NOT_IMPLEMENTED",
                            node_id=self.node_type,
                            retryable=False,
                        )
                # OAuth2 automatic refresh via reusable engine
                if provider_id in ("oauth2", "salesforce"):
                    try:
                        from app.credentials.oauth_manager import get_oauth_manager
                        mgr = get_oauth_manager()
                        # Salesforce uses login_url instead of token_url
                        if provider_id == "salesforce":
                            login_url = (cred_data.get("login_url") or cred_data.get("instance_url") or "").rstrip("/")
                            if login_url and not cred_data.get("token_url"):
                                cred_data = {**cred_data, "token_url": f"{login_url}/services/oauth2/token"}
                            # Fill missing client_id/client_secret from server config
                            if not cred_data.get("client_id") or not cred_data.get("client_secret"):
                                from app.config import get_settings
                                settings = get_settings()
                                cred_data = {
                                    **cred_data,
                                    "client_id": cred_data.get("client_id") or settings.salesforce_client_id,
                                    "client_secret": cred_data.get("client_secret") or settings.salesforce_client_secret,
                                }
                        # Check if refresh needed
                        need_refresh = False
                        if not cred_data.get("access_token"):
                            need_refresh = bool(cred_data.get("refresh_token"))
                        elif mgr.is_expired(cred_data):
                            need_refresh = True
                        if need_refresh and cred_data.get("refresh_token") and cred_data.get("token_url"):
                            orig_client = getattr(mgr, 'http_client', None)
                            try:
                                mgr.http_client = getattr(ctx, 'http_client', None)
                                refreshed = await mgr.refresh(cred_data)
                                if refreshed:
                                    cred_data = refreshed
                                    if refreshed.get("refresh_token") and cred_data.get("_credential_id"):
                                        try:
                                            import json
                                            from app.db import get_session
                                            from app.models.credential import Credential
                                            from app.security.crypto import encrypt_text, decrypt_text
                                            with get_session() as db_sess:
                                                c_rec = db_sess.get(Credential, cred_data["_credential_id"])
                                                if c_rec:
                                                    c_dict = json.loads(decrypt_text(c_rec.data))
                                                    c_dict["refresh_token"] = refreshed["refresh_token"]
                                                    c_rec.data = encrypt_text(json.dumps(c_dict))
                                                    db_sess.commit()
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                            finally:
                                mgr.http_client = orig_client
                    except Exception:
                        pass
                # Salesforce OAuth: apply Bearer token directly or report auth failure
                if provider_id == "salesforce":
                    if cred_data.get("access_token"):
                        headers["Authorization"] = f"Bearer {cred_data['access_token']}"
                        applied = True
                        break
                    raise NodeExecutionError(
                        "Salesforce authentication failed: access token expired or invalid. Please reconnect your Salesforce account in the Credentials page.",
                        code="AUTH_FAILED",
                        node_id=self.node_type,
                        retryable=False,
                    )
                # Build request dict and delegate
                req: dict[str, Any] = {
                    "method": p.method,
                    "url": self._build_url(p) if p.url and "{{" not in p.url else p.url,
                    "headers": headers,
                    "query": query,
                    "body": p.body,
                }
                try:
                    updated = builder.build(req, provider_id, cred_data)
                except ValueError as e:
                    # Provider not implemented or validation failed — block execution before queue
                    msg = str(e)
                    if "not implemented" in msg.lower():
                        raise NodeExecutionError(f"{msg} (credential type '{cred_type}').", code="CREDENTIAL_PROVIDER_NOT_IMPLEMENTED", node_id=self.node_type, retryable=False) from e
                    raise NodeExecutionError(str(e), code="AUTH_FAILED", node_id=self.node_type, retryable=False) from e
                # Copy back mutated headers/query
                headers.clear()
                headers.update(updated.get("headers") or {})
                query.clear()
                query.update(updated.get("query") or {})
                applied = True
            if applied:
                return
        # Fallback: inline auth (legacy) — when no credential or credential type is generic http with inline fields
        # This preserves backward compat for workflows that store token directly in params without a credential.
        cred_fallback: dict[str, Any] | None = None
        if ctx and ctx.credentials and isinstance(ctx.credentials, dict):
            cred_fallback = ctx.credentials.get("http") if isinstance(ctx.credentials.get("http"), dict) else None
        if p.auth_type == "bearer":
            token = p.auth_token.strip()
            if not token and cred_fallback and cred_fallback.get("api_key"):
                token = str(cred_fallback.get("api_key", "")).strip()
            if not token:
                raise NodeExecutionError("auth_type=bearer requires auth_token (or HTTP credential).", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
            headers.setdefault("Authorization", f"Bearer {token}")
        elif p.auth_type == "basic":
            username = p.auth_username
            password = p.auth_password
            if not username and cred_fallback:
                username = str(cred_fallback.get("username", ""))
                password = str(cred_fallback.get("password", ""))
            if not username:
                raise NodeExecutionError("auth_type=basic requires auth_username (or HTTP credential).", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
            raw = f"{username}:{password}".encode()
            headers.setdefault("Authorization", "Basic " + base64.b64encode(raw).decode())
        elif p.auth_type == "api_key":
            name = p.api_key_name.strip() or "X-API-Key"
            token = p.auth_token.strip()
            if not token and cred_fallback and cred_fallback.get("api_key"):
                token = str(cred_fallback.get("api_key", "")).strip()
            if not token:
                raise NodeExecutionError("auth_type=api_key requires auth_token (or HTTP credential).", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
            if p.api_key_in == "query":
                query.setdefault(name, token)
            else:
                headers.setdefault(name, token)
        elif p.auth_type == "header":
            name = p.api_key_name.strip() or "X-API-Key"
            token = p.auth_token.strip()
            if not token:
                raise NodeExecutionError("auth_type=header requires auth_token (header value).", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
            headers.setdefault(name, token)
        elif p.auth_type == "query":
            name = p.api_key_name.strip() or "api_key"
            token = p.auth_token.strip()
            if not token:
                raise NodeExecutionError("auth_type=query requires auth_token (query value).", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
            query.setdefault(name, token)
        elif p.auth_type == "digest":
            # Digest inline uses username/password via provider for header generation
            prov = get_provider_registry().get("digest")
            if prov is None or not getattr(prov, "implemented", True):
                raise NodeExecutionError("Digest Auth provider for credential type 'digest' is not implemented yet. Please choose a different authentication type.", code="CREDENTIAL_PROVIDER_NOT_IMPLEMENTED", node_id=self.node_type, retryable=False)
            cred = {"username": p.auth_username, "password": p.auth_password}
            try:
                req = {"method": p.method, "url": self._build_url(p) if p.url and "{{" not in p.url else p.url, "headers": headers, "query": query, "body": p.body}
                updated = prov.prepareRequest(req, cred)
                headers.clear(); headers.update(updated.get("headers") or {})
                query.clear(); query.update(updated.get("query") or {})
            except ValueError as e:
                raise NodeExecutionError(str(e), code="BAD_REQUEST", node_id=self.node_type, retryable=False) from e
        elif p.auth_type == "custom":
            raise NodeExecutionError("auth_type=custom requires a Custom Auth credential.", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
        elif p.auth_type == "oauth1":
            raise NodeExecutionError("auth_type=oauth1 requires an OAuth1 credential.", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
        elif p.auth_type == "oauth2":
            token = p.auth_token.strip()
            if not token and cred_fallback and cred_fallback.get("api_key"):
                token = str(cred_fallback.get("api_key", "")).strip()
            if not token:
                raise NodeExecutionError("auth_type=oauth2 requires auth_token (or HTTP credential).", code="BAD_REQUEST", node_id=self.node_type, retryable=False)
            headers.setdefault("Authorization", f"Bearer {token}")
        elif p.auth_type == "none" and cred_fallback and cred_fallback.get("api_key"):
            pass

    async def _follow_link_pagination(self, ctx, params, first_response, url, headers, query):
        pages = [first_response]
        seen = {str(first_response.url)}
        while len(pages) < params.max_pages:
            nxt = _next_link_target(pages[-1].headers.get("Link"))
            if not nxt:
                break
            try:
                page = await ctx.http_client.request(
                    "GET", nxt, headers=headers or None, params=query or None,
                    timeout=params.timeout_seconds,
                    follow_redirects=params.follow_redirects,
                    max_response_bytes=params.max_response_bytes,
                )
            except httpx.TimeoutException as exc:
                raise NodeExecutionError("Pagination request timed out.", code="HTTP_TIMEOUT", node_id=self.node_type, retryable=True) from exc
            except httpx.RequestError as exc:
                raise NodeExecutionError(f"Pagination request failed: {exc}", code="HTTP_REQUEST_FAILED", node_id=self.node_type, retryable=True) from exc
            if page.status_code >= 400:
                break
            if str(page.url) in seen:
                break
            seen.add(str(page.url))
            pages.append(page)

        if len(pages) <= 1:
            return None

        merged: list[Any] = []
        for pg in pages:
            try:
                body_json = pg.json()
            except ValueError:
                return None
            if not isinstance(body_json, list):
                return None
            merged.extend(body_json)

        item = {
            "status": pages[-1].status_code,
            "statusCode": pages[-1].status_code,
            "pages": len(pages),
            "count": len(merged),
            "items": merged,
            "headers": dict(pages[-1].headers),
            "body": merged,
        }
        if params.idempotency_key:
            await ctx.storage.set(f"idem:{params.idempotency_key}", item, ttl=86400)
        return NodeResult(output_items=[item])

    @staticmethod
    def _next_link_target(link_header: str | None) -> str | None:
        if not link_header:
            return None
        for part in link_header.split(","):
            seg = part.strip()
            if 'rel="next"' in seg or seg.lower().endswith("rel=next"):
                target = seg.split(";", 1)[0].strip().lstrip("<").rstrip(">")
                return target or None
        return None

    async def _to_item(self, ctx: NodeContext, params: HTTPRequestParams, response: httpx.Response, elapsed_ms: float, url: str, req_headers: dict[str, str], req_query: dict[str, Any]) -> dict[str, Any]:
        # Determine response format handling
        content_type = response.headers.get("content-type", "") or response.headers.get("Content-Type", "")
        fmt = params.response_format
        body: Any
        if fmt == "json":
            try:
                body = response.json()
            except ValueError:
                body = response.text
        elif fmt == "text":
            body = response.text
        else:  # auto
            # Try JSON if content-type suggests, else text
            if "application/json" in content_type.lower() or content_type.lower().startswith("application/"):
                try:
                    body = response.json()
                    # If JSON succeeded but content-type is not json-like, still use json
                except ValueError:
                    body = response.text if response.text else response.content.decode(errors="replace") if response.content else ""
            else:
                # For binary content, base64-encode so downstream nodes can use the data
                if "image/" in content_type or "octet-stream" in content_type or "pdf" in content_type or "audio/" in content_type or "video/" in content_type:
                    body = base64.b64encode(response.content).decode("ascii")
                else:
                    body = response.text if response.text else ""

        # n8n-compatible: response data at top level, metadata alongside
        # If body is a dict, merge it at top level so {{ $json.field }} works directly
        _META_KEYS = {"status", "statusCode", "statusMessage", "headers", "responseTime", "request", "responseTimeMs"}
        if isinstance(body, dict):
            item: dict[str, Any] = {
                **{k: v for k, v in body.items() if k not in _META_KEYS},
                "status": response.status_code,
                "statusCode": response.status_code,
                "statusMessage": response.reason_phrase or ("OK" if 200 <= response.status_code < 300 else "Error"),
                "headers": dict(response.headers),
                "responseTime": round(elapsed_ms, 1),
                "request": {
                    "method": params.method,
                    "url": url,
                    "headers": _redact_headers(req_headers),
                    "query": req_query,
                } if params.method else None,
            }
            if "body" not in item:
                item["body"] = body
        else:
            # Non-dict body (string, list, etc.) — wrap under body key
            item = {
                "body": body,
                "status": response.status_code,
                "statusCode": response.status_code,
                "statusMessage": response.reason_phrase or ("OK" if 200 <= response.status_code < 300 else "Error"),
                "headers": dict(response.headers),
                "responseTime": round(elapsed_ms, 1),
                "request": {
                    "method": params.method,
                    "url": url,
                    "headers": _redact_headers(req_headers),
                    "query": req_query,
                } if params.method else None,
            }
        # Also include elapsed
        item["responseTimeMs"] = round(elapsed_ms, 1)

        # Idempotency cache
        if params.idempotency_key and params.method in ("GET", "HEAD", "PUT", "DELETE"):
            await ctx.storage.set(f"idem:{params.idempotency_key}", item, ttl=86400)
        return item


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact sensitive headers for request metadata."""
    sensitive = ("authorization", "cookie", "x-api-key", "x-auth-token", "proxy-authorization")
    out: dict[str, str] = {}
    for k, v in headers.items():
        kl = k.lower()
        if any(s in kl for s in sensitive) or "token" in kl or "secret" in kl or "key" in kl:
            out[k] = "***REDACTED***"
        else:
            out[k] = v
    return out
