# Phase 12 — AI Agent node (spec 20)

> **Milestone:** the "AI differentiator" grows a second node: an
> autonomous agent that loops (ReAct-style) over tools until it reaches
> a final answer, instead of the single-shot `ai` chat node.
> **Status:** done — `tests/test_nodes/test_ai_agent.py` (5 tests) green;
> full suite 229 passed.

## 1. What Phase 12 delivers

```text
[any upstream node] ──► AI Agent
                          │   instructions: "You are... use tools..."
                          │   input:        task (param or $json)
                          │   max_iterations (1..50, default 10)
                          ▼
              LLM ◄── tools loop ──► current_time
              │  ├── observe          http_request
              │  └── repeat           database_query (read-only guard)
              ▼
          {"action": "final", "answer": "..."}
                          │
                          ▼
                   output: { result: "<final answer>" }
```

- **`app/nodes/ai_agent.py`** — `ai_agent` node registered like any
  built-in. The agent loop:
  1. Builds the system prompt from the live tool registry
     (`app.ai.tools`), so new tools are advertised automatically.
  2. Asks the LLM (tool definitions sent as OpenAI function schemas).
  3. If `tool_calls` arrive → executes each via `run_tool(ctx, ...)`
     **inside the node's execution context**, appends the `tool` message,
     loops (bounded by `max_iterations`).
  4. If no tool call → looks for the `{"action": "final", "answer": …}`
     envelope **or** treats plain content as the final answer.
  5. No answer within the budget → `AI_MAX_ITERATIONS` error. LLM
     failures surface as `LLM_*` codes. Missing credential →
     `CREDENTIALS_REQUIRED` (needs an `llm` credential).
- **Tool errors don't kill the run** — a failing tool feeds its error
  text back to the model, so the agent can adapt (covered by a test that
  retries after a transient failure).
- Uses the shared `app.ai.client.chat_completion`; no new deps.

## 2. Why it took the shape it did

1. The final-answer contract is a JSON envelope the LLM must emit
   **inside a plain content string** (many small models can't do real
   tool-call-only responses); the node accepts either that envelope or
   plain text, so both OpenAI-class and local models work.
2. Bare-text fallback was required: models that never emit structured
   JSON must still be usable — the node treats any non-tool response as
   the answer.
3. Credential enforcement mirrors the `ai` node (`credential_types =
   ["llm", "http", "database"]`, though the loop only injects whatever
   `ctx.credentials` carries).

## 3. Files

```text
backend/app/
└── nodes/ai_agent.py        # AIAgentNode + AgentParams + agent loop
backend/tests/
└── test_nodes/test_ai_agent.py   # 5 tests (credential, tool loop,
                                  #   multi-tool, error-recovery, budget,
                                  #   direct answer)
```

## 4. Verification

- `pytest tests/test_nodes/test_ai_agent.py` — 5 passed.
- Full suite 229 passed (was 216), pyright clean, registry now lists
  `ai_agent` (11 built-in nodes).