"""XML node (original implementation).

Parse XML into JSON objects and build XML back from JSON, using
defusedxml (already a dependency) so hostile payloads can't trigger
entity-expansion attacks. Namespaces are stripped to plain local names.
"""

from __future__ import annotations

from typing import Any, Literal
from xml.etree.ElementTree import Element, SubElement, tostring

from defusedxml.ElementTree import fromstring as _safe_fromstring
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

MAX_XML_BYTES = 1_000_000


class XmlOpsParams(BaseModel):
    operation: Literal["parse", "build"] = Field(default="parse")
    xml: str = Field(default="", description="XML source for parse (empty = first input item xml/text).")
    data: dict[str, Any] | None = Field(default=None, description="Object for build (empty = first input item).")
    root: str = Field(default="root", description="Root tag for build.")
    field: str = Field(default="", description="Item field to read when xml/data is empty.")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _element_to_json(element: Element) -> Any:
    children = list(element)
    text = (element.text or "").strip()
    if not children:
        return text
    out: dict[str, Any] = {}
    for child in children:
        key = _local(child.tag)
        value = _element_to_json(child)
        if key in out:
            if not isinstance(out[key], list):
                out[key] = [out[key]]
            out[key].append(value)
        else:
            out[key] = value
    if text:
        out["#text"] = text
    return out


def _json_to_element(parent: Element, value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "#text":
                parent.text = str(item)
                continue
            if isinstance(item, list):
                for entry in item:
                    child = SubElement(parent, str(key))
                    _json_to_element(child, entry)
            else:
                child = SubElement(parent, str(key))
                _json_to_element(child, item)
    elif isinstance(value, list):
        for entry in value:
            child = SubElement(parent, "item")
            _json_to_element(child, entry)
    elif value is not None:
        parent.text = str(value)


def _read_xml(params: XmlOpsParams, items: list[dict[str, Any]]) -> str:
    if params.xml:
        return params.xml
    if not items:
        return ""
    first = items[0] if isinstance(items[0], dict) else {}
    if params.field:
        cur: Any = first
        for part in params.field.split("."):
            cur = cur.get(part, "") if isinstance(cur, dict) else ""
        return str(cur or "")
    for key in ("xml", "text", "content", "body"):
        if isinstance(first.get(key), str) and first[key]:
            return first[key]
    return ""


@register
class XmlOpsNode(BaseNode[XmlOpsParams]):
    node_type = "xml_ops"
    display_name = "XML"
    version = 1
    description = "Parse XML to JSON and build XML from JSON."
    category = "Transform"
    icon = "🧾"
    parameters_schema = XmlOpsParams

    async def run(
        self,
        ctx: NodeContext,
        params: XmlOpsParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if params.operation == "build":
            data = params.data
            if data is None and input_items and isinstance(input_items[0], dict):
                data = input_items[0]
            if not isinstance(data, dict):
                raise NodeExecutionError(
                    "build needs a JSON object.",
                    code="XML_BUILD_INPUT", node_id="xml_ops", retryable=False,
                )
            root = Element(params.root.strip() or "root")
            _json_to_element(root, data)
            return NodeResult(output_items=[{"xml": tostring(root, encoding="unicode")}])
        src = _read_xml(params, input_items or "")
        if not src.strip():
            raise NodeExecutionError(
                "parse needs XML input.",
                code="XML_EMPTY_INPUT", node_id="xml_ops", retryable=False,
            )
        try:
            root = _safe_fromstring(src.strip().encode()[:MAX_XML_BYTES])
        except Exception as exc:
            raise NodeExecutionError(
                "XML could not be parsed.",
                code="XML_PARSE_ERROR", node_id="xml_ops", retryable=False,
            ) from exc
        return NodeResult(output_items=[{_local(root.tag): _element_to_json(root)}])
