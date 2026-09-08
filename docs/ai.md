# AI features (Phase 8)

Everything integrates with the platform's OpenAI-compatible endpoint; no
model runs locally. Requires an `llm` credential (see Credentials).

## The AI node

`type: "ai"` — a chat node with an optional tool-calling loop.

Parameters:

| Field            | Default | Notes                                             |
| ---------------- | ------- | ------------------------------------------------- |
| `prompt`         | —       | user prompt; `{{ }}` expressions resolve per item |
| `system_message` | `""`    | optional system prompt (expressions too)          |
| `temperature`    | `0.2`   | 0–2                                               |
| `response_format`| `text`  | `text` or `json` (json output is parsed)          |
| `max_turns`      | `8`     | model⇄tool round trips, max 20                    |
| `tools`          | `[]`    | see tools below                                   |

Requires an `llm` credential on the node, else `CREDENTIALS_REQUIRED`.
Hitting `max_turns` without a final answer fails with `AI_MAX_TURNS`.

Output item: `{response, model, turns, tool_calls}`.

### Tools

- `current_time` — UTC timestamp, no arguments.
- `http_request` — mirrors the http_request node; uses the node's `http`
  credential when attached (Bearer/Basic auth).
- `database_query` — runs SQL through the node's `database` credential.
  **Read-only guard:** the statement must start with `SELECT`, `EXPLAIN`,
  `PRAGMA`, or `WITH` — everything else is rejected.

Model responses and tool results are capped (tool results truncated to
4000 chars). Tool failures are handed back to the model as JSON errors
instead of failing the run.

## API

All endpoints require auth; both use the caller's first `llm` credential
(or an explicit `credential_id`).

- `GET /api/ai/status` → `{configured: bool}`.
- `POST /api/ai/explain` `{execution_id}` → plain-language explanation of
  the failing step. 404 unknown/inaccessible execution, 409 if nothing
  failed, 422 no llm credential, 502 provider error.
- `POST /api/ai/generate-workflow` `{prompt}` → a **validated, unsaved**
  workflow JSON (fresh `wf_` id) the client can POST to `/api/workflows`.
  Generation is audited as `ai.generate`. 422 on invalid model output.

## Frontend

- **Sidebar → "AI assistant"**: type a description, the generated workflow
  is saved and opened on the canvas.
- **Execution inspector**: failed runs get an "✨ Explain error" button.

## Securing the provider key

The `api_key` is encrypted with the credentials keyring like every other
secret (see `docs/security.md`). The model/HTTP calls are made by the
backend; browser code never sees the key. No prompt or generated workflow
is stored server-side.