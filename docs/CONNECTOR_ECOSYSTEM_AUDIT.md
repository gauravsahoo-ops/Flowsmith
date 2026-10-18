# FlowSmith Connector & Node Ecosystem — Capability Inventory

**Date:** 2026-10-13
**Scope:** Read-only audit of `C:\n8n-master` (reference only) and `C:\Flowsmith` (implementation).
**Method:** Structural enumeration of both repositories plus an evidence-based stub/placeholder
audit of every FlowSmith connector, node and provider. Classification claims are backed by
`path:line` citations, not by reading file names.

> **Reference boundary.** `C:\n8n-master` is licensed under the **Sustainable Use License**
> (non-commercial/internal-use only) with `.ee.` files under a separate n8n Enterprise License.
> It is used here **only** to enumerate publicly observable capabilities. No n8n source code,
> icons, or documentation is transplanted into FlowSmith. See `CONNECTOR_LICENSE_RISK_REPORT.md`.

---

## 1. How the two platforms are structured

| | n8n | FlowSmith |
|---|---|---|
| Node definition | `*.node.ts` class + `.node.json` codex sidecar + SVG icon | `backend/app/nodes/*.py` class registered via `@register` into `NODE_REGISTRY` |
| Connector/integration | Node class carries `execute()` directly | Split: `connectors/<key>_definition.py` (metadata/ops) + `<key>_connector.py` (executor) + `providers/<vendor>.py` (HTTP client) |
| Parameter form | Hand-written `properties` array in each node class | JSON Schema → `ParameterSchemaBuilder` → `fields[]` → `DynamicNodeConfigPanel` |
| Credentials | `credentials/*.credentials.ts`, 451 total | `credentials/type_registry.py` + `CONNECTOR_AUTH_CATALOG` (90 entries) + 16 auth providers |
| Registration | `package.json → n8n.nodes[]` | `app/connectors/__init__.py::register_builtin_connectors()` |
| Node counts | 445 base + 126 langchain = **571** | **69** built-in node classes + **69** registered connectors |

---

## 2. FlowSmith inventory — actual state

### 2.1 Built-in node classes (69, `backend/app/nodes/`)

| Category | node_type values |
|---|---|
| **Triggers** (10) | `manual_trigger`, `schedule`, `webhook`, `form_trigger`, `chat_trigger`, `error_trigger`, `execute_workflow_trigger`, `salesforce_trigger`, `sftp_trigger`, `respond_to_webhook` |
| **Flow control** (9) | `if_condition`, `switch`, `router`, `merge`, `loop`, `loop_over_items`, `loop_while`, `filter`, `wait` |
| **Data shaping** (11) | `set_data`, `set_variable`, `aggregate`, `split`, `split_out`, `item_lists`, `compare_datasets`, `csv_json_transform`, `string_tools`, `date_time`, `noop` |
| **Code & transforms** (6) | `code`, `compression`, `crypto_tools`, `markdown_text`, `xml_ops`, `html_extract` |
| **Integration plumbing** (12) | `http_request`, `graphql`, `soap_request`, `websocket`, `rss_feed`, `elasticsearch`, `ftp`, `ssh`, `git`, `file_io`, `send_email`, `email_read` |
| **Databases** (1) | `database_query` (engine-agnostic; DSN-driven) |
| **AI / RAG** (9) | `ai`, `ai_agent`, `embeddings`, `memory`, `rag_pipeline`, `output_parser`, `reranker`, `text_splitter`, `token_manager` / `token_fetch` / `token_store` |
| **Workflow** (3) | `sub_workflow`, `data_table`, `pagination` |
| **Auth/helpers** (3) | `human_approval`, `auth_fetch`, `auth_store`, `slack`, `telegram` |

### 2.2 Registered connectors (69) — operation counts

| Connector | Ops | Pagination | | Connector | Ops | Pagination |
|---|---|---|---|---|---|---|
| salesforce | 12 | ✅ | | zendesk | 5 | ❌ |
| dynamics_crm | 8 | ❌ | | todoist | 6 | ❌ |
| netsuite | 7 | ❌ | | xero | 5 | ❌ |
| workday | 6 | ❌ | | zoom | 4 | ❌ |
| intercom | 6 | ✅ | | trello | 4 | ❌ |
| box | 6 | ❌ | | twilio | 3 | ❌ |
| pagerduty | 6 | ❌ | | typeform | 5 | ❌ |
| sap | 6 | ✅ | | whatsapp | 3 | ❌ |
| **hubspot** | **4** | **❌** | | supabase | 5 | ❌ |
| activecampaign | 5 | ✅ | | sentry | 3 | ❌ |
| airtable | 4 | ✅ | | resend | 3 | ❌ |
| asana | 5 | ❌ | | pinecone | 3 | ❌ |
| bigquery | 5 | ✅ | | s3 | 4 | ❌ |
| bitbucket | 5 | ❌ | | gmail | (1) | ❌ |
| brevo | 5 | ❌ | | discord | 2 | ❌ |
| calendly | 5 | ❌ | | outlook | 2 | ❌ |
| clickup | 5 | ❌ | | msteams | 3 | ❌ |
| coda | 5 | ❌ | | anthropic / gemini / openai | 2–3 | ❌ |
| github | 4 | ✅ | | mongodb | 4 | ❌ |
| gitlab | 5 | ❌ | | mssql / mysql / postgres / sqlite / snowflake | 4–5 | ❌ |
| google_* (6) | 3–5 | ✅(drive) | | redis | 5 | ❌ |
| freshdesk / freshsales | 5 | ❌ | | rabbitmq | 3 | ❌ |
| jira | 4 | ✅ | | http | (free-form) | ✅ |
| linear | 5 | ❌ | | schedule / webhook | echo | n/a |
| mailchimp | 5 | ❌ | | | | |
| microsoft_graph / monday | 3–5 | ❌ | | | | |
| notion | 3 | ✅ | | | | |
| pipedrive | 5 | ❌ | | | | |
| quickbooks | 6 | ❌ | | | | |
| sendgrid | 4 | ✅ | | | | |
| shopify | 4 | ✅ | | | | |
| slack | 2 | ✅ | | | | |
| stripe | 4 | ✅ | | | | |
| servicenow | 5 | ❌ | | | | |

**Pagination:** 15 of 69 connectors declare cursor/page parameters. 54 do not.

### 2.3 Auth methods (`credentials/auth_metadata.py::CONNECTOR_AUTH_CATALOG`, 90 entries)

| Auth method | Representative connectors |
|---|---|
| OAuth2 + refresh | salesforce, hubspot, zoho_crm, google_* |
| OAuth2 authorization code | slack, google, airtable, notional |
| Client credentials / S2S | dynamics_crm, netsuite |
| Bearer token | workday, openai, anthropic, sentry |
| API key | activecampaign, brevo, sendgrid, mailchimp, stripe, twilio |
| Basic auth | sap, servicenow, freshdesk, bitbucket |
| Service account / JWT | bigquery, gcp-native |
| AWS SigV4 | s3 (declared; **not implemented** — see §4) |
| Custom header / query | http (generic) |
| none | schedule, webhook, noop-style |

Generic reusable auth types in `credentials/type_registry.py`: `basic_auth`, `bearer_auth`,
`header_auth`, `query_auth`, `digest_auth`, `custom_auth`, `oauth1`, `oauth2`.

### 2.4 Configuration UI

| Component | Path | Status |
|---|---|---|
| Generic schema-driven panel | `frontend/src/components/parameters/DynamicNodeConfigPanel.jsx` (371 lines) | ✅ Renders credential picker, operation bar, fields, advanced settings, test/preview |
| JSON-Schema field renderer | `frontend/src/components/JsonForm.jsx` + `utils/jsonFormHelpers.js` | ✅ string/number/boolean/object/array/color/enum |
| Backend field enrichment | `backend/app/parameters/schema.py::ParameterSchemaBuilder` | 🟡 In progress — emits `fields[]` with `show_if`, `group`, `required` |
| Expression mapping | `MappingField.jsx`, `ExpressionHelper.jsx` | ✅ upstream-field suggestions + preview |
| Dedicated editors | 16 `*NodeEditor.jsx` (Salesforce, Dynamics, HTTP, Code, If, Filter, …) | ✅ routed by a 20-branch conditional in `NodeEditorModal.jsx:577-741` |

---

## 3. n8n reference inventory (observable capabilities only)

- **571** built-in nodes (445 `nodes-base` + 126 `nodes-langchain`), **451** credential types, **109** trigger classes.
- Sampled operation/auth/pagination facts for Salesforce, Dynamics, HubSpot, HTTP, Postgres, MySQL,
  MongoDB, OpenAI, Slack — see `CONNECTOR_ECOSYSTEM_PLAN.md` §2 for the point-by-point comparison.
- Core utility families: flow control, data shaping (`Transform/{Aggregate,Limit,RemoveDuplicates,Sort,SplitOut,Summarize}`),
  file/format, integration plumbing (HTTP/GraphQL/SSH/FTP/LDAP/AMQP/Kafka/MQTT), meta (`ExecuteWorkflow`, `Wait`, `StickyNote`).

---

## 4. Implementation-status audit (evidence-based)

Every `op_execute` / `run()` in the backend was screened for real I/O and for fake-success patterns.

### ✅ Real (perform genuine I/O) — 67 connectors, all audited nodes, 65 providers

Connectors reach vendor APIs through `BaseProviderClient.authorized_request` (`providers/base.py:191`)
→ `SafeHTTPClient` (SSRF-guarded httpx), or through real drivers (SQLAlchemy, PyMongo, `sqlite3`,
`aio_pika`, `paramiko`, `ftplib`, `redis`). Verified real vendor base URLs in 45 provider modules.

### ⚠️ Problems found

| # | Item | Severity | Evidence |
|---|---|---|---|
| 1 | **`mssql` fake success** | 🔴 High | `mssql_connector.py:132-137` returns `{"executed": True, "rows_affected": 1, "status":"success"}` when host is `localhost`/`mock`/`test`; `:165-171` returns `"Executed via MSSQL abstraction"` on driver ImportError. A real local SQL Server gets fabricated results. |
| 2 | **`rabbitmq` fake success** | 🔴 High | `rabbitmq_connector.py:96-127` simulated branch returns unflagged success for `consume`/`declare`; `:168-177` ImportError fallback returns `"status":"success"` unflagged. |
| 3 | **`s3` is a pure stub** | 🔴 High | `s3_connector.py:80-111` — zero AWS SDK/network. Returns `{"status":"success"}`, fabricated download URL, `"objects": []`, `"deleted": True`. Nothing is uploaded, listed or deleted. |
| 4 | **Config panel fake preview** | 🔴 High | `DynamicNodeConfigPanel.jsx:125-133` — when `onExecuteStep` is absent, "Test Step" returns a fabricated `status: "success", simulated: true` payload. This is exactly the fake-success pattern the spec forbids. |
| 5 | `schedule` / `webhook` echo | 🟢 Acceptable | `schedule_connector.py:75-85`, `webhook_connector.py:74-88` — trigger metadata pass-through; inbound handling lives in `app/api/webhooks.py`. Should be labelled as such rather than `"success": True`. |
| 6 | `BuiltinProvider` canned AI | 🟡 Documented | `app/ai/providers/builtin_provider.py` keyword-rule engine, aliased from `"mock"`/`"offline"`. Labelled "Zero-LLM Mode" — legitimate feature, but a workflow configured with provider `mock` silently gets pattern-matched text. |

### Explicitly verified as *legitimate* (not fake)

- `executor.py:626-654` **pinned node data** — opt-in bypass, emits `"Using pinned mock data"` in the trace.
- `execution_runtime.py:399-440` + `security/http_mocks.py` — workflow-test mode only, clearly labelled.
- `app/ai/simulator.py` — opt-in `POST /ai/simulate`, labelled.
- Canned `[{success: True}]` in `manual_trigger`/`error_trigger` — empty-input test runs only.
- **Zero** `TODO`/`FIXME` markers in shipped code (all 10 grep hits are `TODOIST_*` constants).

---

## 5. Gap summary (vs. the stated objectives)

| # | Gap | Impact |
|---|---|---|
| G1 | 3 dishonest/stub connectors (`mssql`, `rabbitmq`, `s3`) | Violates "no fake success responses" |
| G2 | Config-panel fabricated test preview | Violates "no fake success responses" |
| G3 | `ParameterSchemaBuilder` output (`fields`, `show_if`, `group`, `required`) is generated but **not consumed** by `DynamicNodeConfigPanel` | Conditional params, grouping, validation not working |
| G4 | No client-side required-field validation or output-schema preview | Objective 5 unmet |
| G5 | Pagination in only 15/69 connectors | Objective 6 partially unmet |
| G6 | 20-branch editor routing in `NodeEditorModal.jsx` instead of a registry | Consistency/maintainability risk |
| G7 | Missing core utilities: `jwt`, `totp`, `ldap`, `rename_keys`, `summarize`, PDF, image edit, `ai_transform`, `quickchart`, SSE trigger, AMQP/Kafka/MQTT | Objective 4 breadth |
| G8 | Backend `fields` never reaches `GET /nodes/{type}/parameters` for single-node fetch | Panel can go stale on direct fetch |

---

## 6. Verified baseline (this session)

| Check | Result |
|---|---|
| `frontend: npm run build` | ✅ passes in 4.8 s (chunk-size warnings only) |
| `backend: pytest -m "not timing"` | running at time of writing — see `CONNECTOR_FINAL_REPORT.md` for recorded results |
| n8n SVG byte-hash overlap with FlowSmith | **0 / 635** files identical |
| n8n identifiers in FlowSmith source | **0** hits across `n8n-nodes-base`, `INodeExecutionData`, `VersionedNodeType`, `n8n-workflow`, etc. |
| Uncommitted user work | present (`mssql`/`rabbitmq`/`sqlite` connectors, `parameters/` package, `compression` node) — **preserved, not reverted** |
