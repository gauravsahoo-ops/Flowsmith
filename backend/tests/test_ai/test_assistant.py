"""Phase 16 — AI automation assistant (unit level).

Every surface is exercised with a scripted chat function: suggestions
must be validated against real schemas/engine, carry explanations, and
the deterministic analyzers must be exact.
"""

from __future__ import annotations

import json

import pytest

from app.ai.assistant import (
    AssistantError,
    analyze_workflow,
    document_workflow,
    explain_workflow,
    suggest_expression,
    suggest_field_mapping,
    suggest_node_config,
)
from app.connectors import get_registry, register_builtin_connectors


@pytest.fixture(scope="module", autouse=True)
def _connectors():
    registry = get_registry()
    if not registry.is_initialized():
        registry.initialize()
    register_builtin_connectors()


class ScriptedChat:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, llm, messages, **kwargs):
        self.calls.append(messages)
        content = self.responses.pop(0)
        # Raw strings pass through (explain/document surfaces); dicts are JSON-encoded.
        return {"content": json.dumps(content) if not isinstance(content, str) else content}


# ----------------------------------------------------------------------
# field mapping
# ----------------------------------------------------------------------

SOURCE_FIELDS = [
    {"path": "name", "type": "str", "sample": "ada"},
    {"path": "email", "type": "str", "sample": "a@b.com"},
    {"path": "company.size", "type": "int", "sample": 50},
]


async def test_mapping_valid_suggestions_pass_and_explain():
    chat = ScriptedChat({
        "mapping": {"greeting": "{{ $json.name | upper }}", "contact": "{{ $json.email }}"},
        "explanation": "Maps name and email from the trigger payload.",
    })
    result = await suggest_field_mapping(
        target_node_type="set_data", target_fields=["greeting", "contact"],
        source_fields=SOURCE_FIELDS, chat=chat, llm={},
    )
    assert result["ok"] is True
    assert result["mapping"]["greeting"] == "{{ $json.name | upper }}"
    assert "explanation" in result


async def test_mapping_dunder_expression_is_rejected():
    chat = ScriptedChat({"mapping": {"evil": "{{ $json.__class__ }}"}})
    result = await suggest_field_mapping(
        target_node_type="set_data", target_fields=["evil"],
        source_fields=SOURCE_FIELDS, chat=chat, llm={},
    )
    assert result["ok"] is False
    assert any(i["severity"] == "error" and i["code"] == "UNSAFE_EXPRESSION"
               for i in result["issues"])


async def test_mapping_unknown_source_reference_warns_not_fails():
    chat = ScriptedChat({"mapping": {"phone": "{{ $json.phone }}"}})
    result = await suggest_field_mapping(
        target_node_type="set_data", target_fields=["phone"],
        source_fields=SOURCE_FIELDS, chat=chat, llm={},
    )
    assert result["ok"] is True  # warnings never block
    assert any(i["code"] == "UNKNOWN_SOURCE_FIELD" for i in result["issues"])


async def test_mapping_garbage_output_raises():
    chat = ScriptedChat("not json")
    with pytest.raises(AssistantError):
        await suggest_field_mapping(
            target_node_type="set_data", target_fields=["x"],
            source_fields=SOURCE_FIELDS, chat=chat, llm={},
        )


# ----------------------------------------------------------------------
# expression generation
# ----------------------------------------------------------------------

async def test_expression_is_preview_evaluated_against_the_sample():
    chat = ScriptedChat({"expression": "{{ $json.name | upper }}",
                         "explanation": "Upper-cases the name."})
    result = await suggest_expression(description="upper case the name",
                                      sample_item={"name": "ada"},
                                      chat=chat, llm={})
    assert result["ok"] is True
    assert result["preview_value"] == "ADA"


async def test_expression_unsafe_output_flagged_without_preview():
    chat = ScriptedChat({"expression": "{{ $json.__globals__ }}"})
    result = await suggest_expression(description="do bad", sample_item={},
                                      chat=chat, llm={})
    assert result["ok"] is False
    assert result["preview_value"] is None


async def test_expression_missing_output_raises():
    chat = ScriptedChat({"explanation": "nothing"})
    with pytest.raises(AssistantError):
        await suggest_expression(description="x", chat=chat, llm={})


# ----------------------------------------------------------------------
# node configuration
# ----------------------------------------------------------------------

async def test_node_config_valid_parameters_pass_schema_check():
    chat = ScriptedChat({"parameters": {"fields": {"a": "{{ $json.b }}"}},
                         "explanation": "copies b to a"})
    result = await suggest_node_config(node_type="set_data", operation=None,
                                       intent="copy field b to a",
                                       available_credentials=set(),
                                       chat=chat, llm={})
    assert result["ok"] is True
    assert result["parameters"] == {"fields": {"a": "{{ $json.b }}"}}


async def test_node_config_hallucinated_parameter_rejected():
    # http_request has a strict schema: unknown method value is rejected.
    chat = ScriptedChat({"parameters": {"method": "TELEPORT", "url": "https://x"}})
    result = await suggest_node_config(node_type="http_request", operation=None,
                                       intent="teleport data",
                                       available_credentials=set(),
                                       chat=chat, llm={})
    assert result["ok"] is False
    assert any(i["code"] == "INVALID_PARAMETER" for i in result["issues"])


async def test_node_config_connector_operation_pinned_and_validated():
    # The model tries a different op; the caller's pin wins, then validation runs.
    chat = ScriptedChat({"parameters": {"operation": "delete", "object_name": "Lead",
                                        "record_id": "001xx000003DGbmAAG"}})
    result = await suggest_node_config(node_type="salesforce", operation="get",
                                       intent="fetch a lead by id",
                                       available_credentials={"salesforce"},
                                       chat=chat, llm={})
    assert result["parameters"]["operation"] == "get"
    assert any(i["code"] == "MISSING_REQUIRED_FIELD" and i["field"].endswith("record_id")
               for i in result["issues"]) is False
    # get requires record_id which IS present -> clean.
    assert result["ok"] is True


async def test_node_config_unknown_type_refused():
    with pytest.raises(AssistantError):
        await suggest_node_config(node_type="quantum_node", operation=None,
                                  intent="?", available_credentials=set(),
                                  chat=ScriptedChat({}), llm={})


# ----------------------------------------------------------------------
# deterministic workflow analysis
# ----------------------------------------------------------------------

def _wf(nodes, connections):
    return {"nodes": nodes, "connections": connections}


def test_analyzer_flags_unreachable_no_timeout_no_retry():
    wf = _wf(
        [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "h", "type": "http_request",
             "parameters": {"method": "GET", "url": "https://x.example.com"}},
            {"id": "orphan", "type": "set_data", "parameters": {"fields": {}}},
        ],
        [{"source": "t", "target": "h"}],
    )
    codes = {(f["code"], f["node_id"]) for f in analyze_workflow(wf)}
    assert ("NO_TIMEOUT", "h") in codes
    assert ("NO_RETRY_ON_IDEMPOTENT", "h") in codes
    assert ("UNREACHABLE_NODE", "orphan") in codes


def test_analyzer_clean_when_settings_present():
    wf = _wf(
        [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "h", "type": "http_request",
             "parameters": {"method": "GET", "url": "https://x.example.com"},
             "settings": {"timeout_seconds": 10, "retry_max_attempts": 3}},
        ],
        [{"source": "t", "target": "h"}],
    )
    assert analyze_workflow(wf) == []


def test_analyzer_never_uses_llm_and_is_stable():
    wf = _wf([{"id": "t", "type": "manual_trigger", "parameters": {}}], [])
    assert analyze_workflow(wf) == analyze_workflow(wf)


# ----------------------------------------------------------------------
# explain / document
# ----------------------------------------------------------------------

WF = _wf(
    [
        {"id": "t", "type": "webhook", "parameters": {}},
        {"id": "sf", "type": "salesforce",
         "parameters": {"operation": "create", "object_name": "Lead"}},
    ],
    [{"source": "t", "target": "sf"}],
)


async def test_document_works_without_any_llm():
    result = await document_workflow(WF, chat=None, llm={})
    assert "# " in result["markdown"]
    assert "`sf`" in result["markdown"]
    assert result["overview"] == ""


async def test_document_adds_llm_overview_when_available():
    chat = ScriptedChat("This workflow captures leads from webhooks into Salesforce.")
    result = await document_workflow(WF, chat=chat, llm={})
    assert "Salesforce" in result["overview"]
    assert result["markdown"].startswith("#")


async def test_explain_returns_grounded_text():
    chat = ScriptedChat("A webhook receives leads; Salesforce creates them.")
    result = await explain_workflow(WF, chat=chat, llm={})
    assert "leads" in result["explanation"]
    # Ground truth was handed to the model.
    payload = json.dumps(chat.calls[0])
    assert "salesforce" in payload
