# n8n Parity Gap Plan (clean-room, standalone)

> Method: inventoried `C:\n8n-master` (308 node dirs, 442 base impls + 136 langchain nodes, ~446 credentials) vs Flowsmith (was 35 nodes, 20 connectors; now 50 node types, 31 connectors). No n8n code, docs, icons, or templates were copied. Additions below are original implementations in Flowsmith patterns so the project stays MIT and standalone.

## 0. Legal guardrails

- n8n is fair-code (`LICENSE.md` Sustainable Use + `LICENSE_EE.md`), not MIT. Never paste its TS/Vue, node JSON, docs, or assets.
- Learn only facts (public API shapes, params). Write original `backend/app/nodes/*.py` + `providers/*.py` + `connectors/*_definition.py` + React editors.
- No `n8n` name/logo/trademark, no `nodemation` copy. Keep Flowsmith icons, names, and wording.
- Keep existing Flowsmith behavior stable; only additive nodes/connectors plus small corrections.

## 1. Keep same (already at parity, corrections only)

- Core: `code`, `http_request`, `graphql`, `webhook`, `schedule`, `manual_trigger`, `execute_workflow_trigger`, `sub_workflow`.
- Logic: `if_condition`, `switch`, `filter`, `merge`, `set_data`, `split`, `loop`, `loop_over_items`, `loop_while`, `pagination`, `aggregate`, `compare_datasets`, `csv_json_transform`.
- Data: `database_query`, `data_table`, `file_io`, `send_email`, `slack`, `telegram`, `websocket`.
- Control: `human_approval`, `wait`, `stop_and_error`.
- AI: `ai`, `ai_agent`, `rag_pipeline`.
- Triggers: `webhook`, `schedule`, `salesforce_trigger` via `app/triggers/registry.py`.
- Connectors (20): salesforce, hubspot, postgres, mysql, mongodb, redis, slack, msteams, outlook, gmail, google_drive, google_sheets, google_calendar, github, notion, jira, discord, stripe, airtable, shopify.

## 2. Gap batches (original code, Flowsmith UI)

### Batch A — Utility nodes ✅ SHIPPED
`date_time`, `item_lists`, `markdown_text`, `html_extract`, `crypto_tools`. Tests: `tests/test_nodes/test_batch_nodes.py`.
Pattern: `backend/app/nodes/<name>.py` + `@register` + Pydantic `Params` + `BaseNode.run()`; catalog via `registry.list_nodes()` → `GET /api/nodes` → `workflowStore.catalogIndex`; generic `JsonForm` editor, no new frontend package.

### Batch B — Popular SaaS connectors ✅ SHIPPED (8)
Trello, Asana, Linear, Calendly, GitLab, Zoom, Twilio, Bitbucket. Pattern: `providers/<name>.py` (OAuth2 + `get_safe_http_client()`, refresh-on-401, error taxonomy) + `connectors/<name>_definition.py` + `connectors/<name>_connector.py` + credential type + `register_builtin_connectors()`; per-op `idempotency/retryable`; editor follows `SalesforceNodeEditor` pattern with Flowsmith styling.

### Batch C — AI/RAG depth ✅ MOSTLY SHIPPED
Shipped: `text_splitter`, `output_parser`, `embeddings` (shared `rag.embed_texts`), `memory` (Redis sessions). Remaining: document-loader (covered by file_io + http_request + html_extract chain — skipping unless needed). Extend `ai.py`, `ai_agent.py` tools, `rag_pipeline.py`; keep tenant-scoped `rag_collections` and citations.

### Batch D — Triggers (Form ✅ SHIPPED, rest open)
Shipped: `form_trigger` node + `form/` namespace sync (no migration) + public definition/submit routes + `FormFillPage` (`/forms/:slug`) + `test_form_trigger.py`. Shipped: `chat_trigger` node + `chat/` namespace sync + sync-reply public routes (`GET/POST /api/webhooks/chat/{slug}`, 90s bounded wait, reply convention) + `ChatPage` (`/chat/:slug`, stateless history) + `test_chat_trigger.py`. Shipped: workflow-as-API — `POST /api/w/{id}/execute` on minted `UserAPIKey` (`X-API-Key`, async 202 + sync wait, owner/edit scope, per-key budget, `test_workflow_api.py`). Shipped: global error workflow — `settings.on_error_workflow_id` + runtime hook (`_maybe_run_error_workflow`, single-level, test-runs excluded) + `test_error_workflow.py` + ⋮ menu Workflow settings UI (timeout, parallelism, error workflow). Open: Interval (redundant — `schedule` already covers seconds→months), Chat-trigger, IMAP polling. RSS polling covered by `schedule` + `rss_feed` node. Extend `TRIGGER_NODE_TYPES`, `sync_webhooks()`, `schedule_triggers` tables; arm on Active toggle.

## 3. UI match checklist

- `toReactFlow()` / `toWorkflowJson()` contract unchanged (`src/mappers.js`).
- Sidebar/palette from `GET /api/nodes` catalog; `defaultsFromSchema()` for new types.
- `NodeEditorModal` + per-type editor, `CollapsibleSection`, `DataViewer`, `NodeIcons` (no n8n SVGs).
- Debugger `retrySafety()` uses new `idempotency` flags; docs stay in `docs/`.

## 4. Standalone checklist

- [x] No n8n file copied (verify via `git diff --stat` + license scan)
- [x] Original names/descriptions/icons
- [x] `GET /api/nodes` shows new types alongside existing (50 node types, 31 connectors)
- [x] `vitest` + `pytest` green, `vite build` chunk report reviewed
- [x] Docs updated here, not from n8n docs
