"""SOAP Request node (Phase 7 API).

Sends a SOAP 1.1/1.2 envelope via POST and parses the XML response
back to JSON using defusedxml. Complements the Universal HTTP node
for legacy enterprise SOAP services (SAP, Oracle, Dynamics on-prem,
NetSuite SuiteTalk).

- URL + SOAPAction header + raw envelope (or action/body builder).
- Response parsed with the same safe parser as xml_ops.
- Size limits enforced; faults surfaced as structured errors.
"""

from __future__ import annotations

from typing import Any, Literal
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import fromstring as _safe_fromstring
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult, filter_client_kwargs
from app.nodes.registry import register
from app.nodes.xml_ops import MAX_XML_BYTES, _element_to_json, _local

MAX_SOAP_BYTES = 2_000_000


class SoapRequestParams(BaseModel):
    url: str = Field(default="", description="SOAP endpoint URL.")
    soap_action: str = Field(default="", description="SOAPAction header value.")
    envelope: str = Field(default="", description="Full SOAP envelope XML (empty = build from action/body).")
    action: str = Field(default="", description="Operation element name when building envelope.")
    body: dict[str, Any] | None = Field(default=None, description="Body fields when building envelope.")
    soap_version: Literal["1.1", "1.2"] = Field(default="1.1")
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    max_response_bytes: int = Field(default=MAX_SOAP_BYTES, ge=1024, le=10_000_000)


def _build_envelope(action: str, body: dict[str, Any] | None, version: str) -> str:
    ns = "http://schemas.xmlsoap.org/soap/envelope/" if version == "1.1" else "http://www.w3.org/2003/05/soap-envelope"
    inner = ""
    if body:
        parts = "".join(f"<{k}>{v}</{k}>" for k, v in body.items())
        inner = f"<{action}>{parts}</{action}>" if action else parts
    elif action:
        inner = f"<{action}/>"
    return f'<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="{ns}"><soap:Body>{inner}</soap:Body></soap:Envelope>'


@register
class SoapRequestNode(BaseNode[SoapRequestParams]):
    node_type = "soap_request"
    display_name = "SOAP Request"
    version = 1
    description = "Call a SOAP 1.1/1.2 operation and parse the XML response."
    category = "Actions"
    icon = "soap_request"
    parameters_schema = SoapRequestParams
    credential_types = ["http"]
    idempotency = "conditionally_idempotent"

    async def run(self, ctx: NodeContext, params: SoapRequestParams, input_items: list[dict[str, Any]]) -> NodeResult:
        if not params.url.strip():
            raise NodeExecutionError("soap_request needs a url.", code="SOAP_MISSING_URL", node_id=ctx.node_id, retryable=False)
        # S10: SSRF protection - block internal/private targets (incl. DNS).
        if "{{" not in params.url:
            from app.security.ssrf import assert_public_url

            await assert_public_url(params.url.strip(), node_id="soap_request")
        envelope = params.envelope.strip()
        if not envelope:
            if not params.action.strip() and not params.body:
                raise NodeExecutionError(
                    "soap_request needs an envelope or an action/body.",
                    code="SOAP_MISSING_ENVELOPE", node_id=ctx.node_id, retryable=False,
                )
            envelope = _build_envelope(params.action.strip(), params.body, params.soap_version)
        content_type = "text/xml; charset=utf-8" if params.soap_version == "1.1" else "application/soap+xml; charset=utf-8"
        headers = {"Content-Type": content_type, **(params.headers or {})}
        if params.soap_action:
            headers["SOAPAction"] = params.soap_action
        try:
            resp = await ctx.http_client.post(
                params.url,
                **filter_client_kwargs(ctx.http_client, {
                    "content": envelope.encode("utf-8"),
                    "headers": headers,
                    "timeout": params.timeout_seconds,
                }),
            )
        except Exception as exc:
            raise NodeExecutionError(f"SOAP request failed: {exc}", code="SOAP_NETWORK", node_id=ctx.node_id, retryable=True) from exc
        raw = resp.text or ""
        if len(raw.encode("utf-8")) > params.max_response_bytes:
            raise NodeExecutionError("SOAP response exceeded max_response_bytes.", code="SOAP_TOO_LARGE", node_id=ctx.node_id, retryable=False)
        if resp.status_code >= 400:
            raise NodeExecutionError(
                f"SOAP endpoint returned HTTP {resp.status_code}.",
                code="SOAP_HTTP_ERROR", node_id=ctx.node_id, retryable=resp.status_code >= 500,
                details={"status_code": resp.status_code, "body": raw[:2000]},
            )
        try:
            root: Element = _safe_fromstring(raw.strip().encode()[:MAX_XML_BYTES])
        except Exception as exc:
            raise NodeExecutionError("SOAP response was not valid XML.", code="SOAP_PARSE_ERROR", node_id=ctx.node_id, retryable=False) from exc
        parsed = {_local(root.tag): _element_to_json(root)}
        # Surface SOAP Fault explicitly.
        fault = str(raw).lower().find("soap:fault") != -1 or "faultcode" in str(parsed).lower()
        return NodeResult(output_items=[{
            "status_code": resp.status_code,
            "soap_fault": bool(fault),
            "data": parsed,
            "raw": raw[:10000],
        }])
