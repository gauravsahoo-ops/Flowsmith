"""Phase 15 — deterministic evaluation of the generation pipeline.

No network, no credentials: `chat` is a scripted fake. Each case pins
(prompt, model output) -> expected pipeline verdict, and repeated runs
must be byte-identical. This is the regression harness for "the AI must
not invent unavailable connectors, nodes or operations": even when the
model hallucinates, the pipeline either repairs it or refuses.
"""

from __future__ import annotations

import json

import pytest

from app.ai.generation import MAX_ATTEMPTS, GenerationError, generate_workflow_spec
from app.connectors import get_registry, register_builtin_connectors


@pytest.fixture(scope="module", autouse=True)
def _connectors():
    registry = get_registry()
    if not registry.is_initialized():
        registry.initialize()
    register_builtin_connectors()


class ScriptedChat:
    """Returns queued canned responses; records every prompt it saw."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    async def __call__(self, llm, messages, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append(messages)
        return {"content": self.responses.pop(0)}


SALESFORCE_LEAD_PLAN = {
    "name": "Lead dedupe + Teams alert",
    "nodes": [
        {"id": "lead", "type": "salesforce_trigger",
         "parameters": {"path": "sf-outbound/lead-create-eval1", "object_name": "Lead"}},
        {"id": "find", "type": "salesforce",
         "parameters": {"operation": "query",
                        "soql": "SELECT Id FROM Lead WHERE Email = '{{ $json.Email }}' LIMIT 1"},
         "credentials": {"salesforce": "$user"}},
        {"id": "check", "type": "if_condition",
         "parameters": {"condition": {"left": "{{ $json.totalSize }}",
                                      "operator": "equals", "right": 0}}},
        {"id": "create", "type": "salesforce",
         "parameters": {"operation": "create", "object_name": "Lead", "record": {"LastName": "New"}},
         "credentials": {"salesforce": "$user"}},
        {"id": "notify", "type": "http_request",
         "parameters": {"method": "POST", "url": "https://outlook.office.com/webhook/xx",
                        "body": {"text": "New lead created"}}},
    ],
    "connections": [
        {"source": "lead", "target": "find"},
        {"source": "find", "target": "check"},
        {"source": "check", "sourceHandle": "true", "target": "create"},
        {"source": "create", "target": "notify"},
    ],
    "settings": {},
}

HALLUCINATED_PLAN = {
    "name": "bad",
    "nodes": [
        {"id": "t", "type": "manual_trigger", "parameters": {}},
        {"id": "x", "type": "quantum_db", "parameters": {"sql": "SELECT 1"}},
    ],
    "connections": [{"source": "t", "target": "x"}],
    "settings": {},
}

REPAIRED_PLAN = {
    "name": "fixed",
    "nodes": [
        {"id": "t", "type": "manual_trigger", "parameters": {}},
        {"id": "x", "type": "database_query", "parameters": {"sql": "SELECT 1"}},
    ],
    "connections": [{"source": "t", "target": "x"}],
    "settings": {},
}


async def test_eval_valid_plan_passes_first_attempt():
    chat = ScriptedChat(json.dumps(SALESFORCE_LEAD_PLAN))
    result = await generate_workflow_spec(
        "When a Salesforce lead arrives check postgres, create if missing, notify Teams.",
        available_credentials={"salesforce"}, chat=chat, llm={},
    )
    assert result["attempts"] == 1
    assert result["validation"]["ok"] is True
    assert result["workflow"]["status"] == "draft"  # never born active
    # Grounding proof: the system prompt shown to the model lists salesforce ops.
    system = chat.calls[0][0]["content"]
    assert '"connector": "salesforce"' in system


async def test_eval_repairs_a_hallucinated_node_within_budget():
    chat = ScriptedChat(json.dumps(HALLUCINATED_PLAN), json.dumps(REPAIRED_PLAN))
    result = await generate_workflow_spec(
        "run a sql query", available_credentials=set(), chat=chat, llm={},
    )
    assert result["attempts"] == 2
    assert result["validation"]["ok"] is True
    # The repair feedback named the exact rejection.
    feedback = chat.calls[1][-1]["content"]
    assert "UNKNOWN_NODE_TYPE" in feedback


async def test_eval_refuses_when_hallucination_persists():
    chat = ScriptedChat(json.dumps(HALLUCINATED_PLAN), json.dumps(HALLUCINATED_PLAN))
    with pytest.raises(GenerationError) as excinfo:
        await generate_workflow_spec("quantum db please", available_credentials=set(),
                                     chat=chat, llm={})
    assert excinfo.value.validation["ok"] is False
    assert any(e["code"] == "UNKNOWN_NODE_TYPE" for e in excinfo.value.validation["errors"])


async def test_eval_refuses_non_json_output():
    chat = ScriptedChat("I would build a workflow about leads!", "still prose")
    with pytest.raises(GenerationError) as excinfo:
        await generate_workflow_spec("leads", available_credentials=set(), chat=chat, llm={})
    assert any(e["code"] == "NOT_JSON" for e in excinfo.value.validation["errors"])


async def test_eval_tolerates_markdown_fences():
    fenced = "```json\n" + json.dumps(REPAIRED_PLAN) + "\n```"
    chat = ScriptedChat(fenced)
    result = await generate_workflow_spec("sql", available_credentials=set(), chat=chat, llm={})
    assert result["validation"]["ok"] is True


async def test_eval_is_deterministic_across_runs():
    async def run() -> dict:
        chat = ScriptedChat(json.dumps(SALESFORCE_LEAD_PLAN))
        result = await generate_workflow_spec("sf lead flow", available_credentials={"salesforce"},
                                              chat=chat, llm={})
        return result["validation"]

    first, second = await run(), await run()
    assert first == second


EVAL_CASES = [
    # (label, model JSON, available creds, expect_ok, expected codes present)
    ("grounded sf+teams plan", SALESFORCE_LEAD_PLAN, {"salesforce"}, True, set()),
    ("hallucinated node", HALLUCINATED_PLAN, set(), False, {"UNKNOWN_NODE_TYPE"}),
    ("bad op", {**REPAIRED_PLAN, "nodes": REPAIRED_PLAN["nodes"][:-1] + [
        {"id": "x", "type": "salesforce", "parameters": {"operation": "mind_meld"}}]},
     {"salesforce"}, False, {"INVALID_OPERATION"}),
    ("unsafe expression", {**REPAIRED_PLAN, "nodes": [
        {"id": "t", "type": "manual_trigger", "parameters": {}},
        {"id": "x", "type": "set_data",
         "parameters": {"fields": {"a": "{{ $json.__globals__ }}"}}}]},
     set(), False, {"UNSAFE_EXPRESSION"}),
]


@pytest.mark.parametrize("label,candidate,creds,expect_ok,codes", EVAL_CASES)
async def test_eval_matrix(label, candidate, creds, expect_ok, codes):
    """The evaluation matrix: every entry deterministic, every code real."""
    # Expected failures consume both attempts (original + repair round).
    chat = ScriptedChat(*([json.dumps(candidate)] * (1 if expect_ok else MAX_ATTEMPTS)))
    try:
        result = await generate_workflow_spec(label, available_credentials=creds,
                                              chat=chat, llm={})
    except GenerationError as exc:
        report = exc.validation
    else:
        report = result["validation"]
    assert report["ok"] is expect_ok, f"{label}: {report}"
    assert codes <= {e["code"] for e in report["errors"]}
