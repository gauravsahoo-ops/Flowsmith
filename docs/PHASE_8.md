# Phase 8 — AI: chat node, error assistant, NL generation (M10)

> **Milestone:** the AI differentiator (spec 20) — an `ai` chat node
> with tool calling, an AI "explain this failure" assistant, and
> natural-language workflow generation.
> **Status:** done; full docs in `docs/ai.md`.

## 1. What Phase 8 delivers

```text
{{ prompt }} ─▶ ai node ─▶ OpenAI-compatible endpoint (llm credential)
                             │  optional tool-calling loop
                             ▼
                          NodeResult.output_items
   failed execution ─▶ POST /api/ai/explain ─▶ ✨ human-readable diagnosis
   "poll the weather…" ─▶ POST /api/ai/generate-workflow ─▶ saved canvas
```

- **AI node** (`nodes/ai.py`): chat node, parameters `prompt`, `model`
  (optional), `max_tokens`; holds the conversation per input item and
  returns the assistant message in `output_items`. Runs an optional
  tool-calling loop (`tools: run_workflow`, `list_nodes`, … defined in
  `ai/tools.py`) with a bounded number of iterations.
- **API** (`api/ai.py`, all behind the `llm` credential):
  - `GET /api/ai/status` — whether an LLM credential is configured;
  - `POST /api/ai/explain` — takes a failed execution id, hands the
    trace + error to the LLM, returns a plain-language diagnosis;
  - `POST /api/ai/generate-workflow` — prompt → JSON workflow
    (validated through the same `Workflow` schema as the canvas) → saved;
  - every call is audit-logged (`ai.generate`) and the secret is only
    ever read from the encrypted credentials store at call time.
- **Frontend**: "✨ Explain error" button in `ExecutionInspector` on
  failed runs (response shown inline), and an "✨ AI assistant" box in
  the sidebar that generates a workflow and opens it on the canvas
  (`workflowStore.generateWorkflow`).

## 2. Why it took the shape it did

1. **`llm` credential type** — the AI features are just another node
  family, so the provider key rides the existing encrypted credentials
  system (`credential_types = ["llm"]` on the AI node), zero new secret
  handling.
2. **Tool results are JSON-shaped** — the tool-calling loop feeds the
  model raw structured output, not prose, so multi-step prompts
  ("find the workflow, then run it") stay reliable.

## 3. Files

```text
backend/app/
├── ai/
│   ├── client.py      # OpenAI-compatible chat calls, tool loop driver
│   └── tools.py       # workflow tools + result shaping
├── api/ai.py          # /api/ai/status, /explain, /generate-workflow
├── nodes/ai.py        # the chat node (node_type "ai")
├── credentials/registry.py  # "llm" credential type
└── audit.py           # AI_GENERATE event

backend/tests/test_api/test_ai.py     # endpoints, validation, audit
backend/tests/test_nodes/test_ai.py   # node prompt/tool-loop behavior

frontend/src/
├── components/ExecutionInspector.jsx # ✨ Explain error
├── components/Sidebar.jsx            # 🤖 Generate workflow
├── stores/workflowStore.js           # generateWorkflow()
└── api.js                            # aiStatus/explain/generateWorkflow

docs/ai.md                            # parameters, tools, API, security
```

## 4. Verification

- `pytest tests/test_api/test_ai.py tests/test_nodes/test_ai.py` —
  endpoints reject without an `llm` credential; generation returns a
  schema-valid workflow; the node loops on tool calls and stops at the
  iteration cap.
- Live E2E: with a configured `llm` credential, "generate a workflow
  that HTTP-GETs a public API and logs the JSON" produced a valid,
  executable workflow on the canvas; a deliberately failed run produced
  a sensible ✨ explain output.