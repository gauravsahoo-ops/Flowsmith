# Product Gap Analysis (Phase 35)

> **Method:** every capability area was graded against the actual code
> and its test evidence (not aspirations). Classification:
> **BETTER** = ahead of the common self-hosted baseline ·
> **EQUIVALENT** = at parity for v1 scope ·
> **PARTIAL** = usable, meaningful gaps remain ·
> **MISSING** = not implemented. No proprietary implementations were
> copied; differentiators are our own (safety-first posture, test-mode
> mocking, grounded AI).
>
> Companion evidence: `docs/SECURITY_AUDIT.md`, `docs/DISASTER_RECOVERY.md`,
> `docs/workflow-testing.md`, `docs/PHASE_15_AI_GENERATION.md`,
> `docs/PHASE_16_AI_ASSISTANT.md`, `docs/PHASE_18_PRODUCTION_RAG.md`.

## Scorecard

| Area | Class | Evidence / notes |
|---|---|---|
| Visual builder | **EQUIVALENT** | React Flow canvas, snapshot undo/redo, groups, sticky notes, multi-select, keyboard map, command palette, auto-layout, execution highlighting, connect-time cycle rejection (`frontend/src/components/`, `utils/history.js`, `editor.test.js`) |
| Connectors | **PARTIAL** | 21 connectors on a versioned SDK (definitions + ops discovery + taxonomy); Salesforce deep (10 ops incl. bulk + schema discovery); count is far below incumbent catalogs. Framework quality is the asset |
| Triggers | **EQUIVALENT** | Manual/webhook/schedule/Salesforce-outbound; entropy-gated secret paths; arm/disarm; per-path rate limits |
| HTTP node | **BETTER** | Universal client (auth schemes, path/query params, Link-header pagination, size caps) over SafeHTTPClient: SSRF policy, redirect re-validation, redacted logs; test-run mocks block production egress |
| Expressions | **PARTIAL** *(by design)* | Safe tokenizer engine (pipes/ternary/coalesce/arith), autocomplete endpoint, 20-test hostile battery; no arbitrary JS inside expressions — deliberate security stance |
| Mapping | **EQUIVALENT** | Typed upstream-field browser from last run, live preview, missing-field detection, AI mapping suggestions validated+linted (P16) |
| Branching | **EQUIVALENT** | IF (true/false handles) + Switch + merge modes (all/one/combine); parallel ready-set scheduler; branch-taken chips in debugger |
| Loops | **EQUIVALENT** | Loop + loop-while nodes, iteration context, bounded iterations |
| Code (custom functions) | **MISSING** | No sandboxed code/function node; only structured transforms (csv_json_transform). Biggest single builder-parity gap |
| Credentials | **BETTER** | Fernet at rest, key-rotation prefixes + re-encrypt tooling, metadata-only APIs, typed validation registry, DR drill proves key-bound recovery |
| OAuth | **EQUIVALENT** | Generic provider framework (state+PKCE+refresh-on-401), shared Google app scopes, SF/HubSpot/GDrive/GCal/GSheets/Gmail on one mechanism |
| Execution history | **BETTER** | Persisted trace w/ inputs/outputs trees, attempts/retries, timeline spans, comparison tab, status filters, retention pruning, dual-side redaction |
| Debugging | **BETTER** | Full replay, safe node-retry (upstream seeded, never re-runs side effects), execution diff, RAG retrieval debugger, workflow TEST MODE with mock responses + PASS/FAIL/DIFF reports (P14), AI failure explainer |
| Retries | **BETTER** | Idempotency-aware executor (never re-fires non-idempotent creates), provider Retry-After honored, capped backoff, structured attempt telemetry |
| Timeouts | **EQUIVALENT** | Per-node + workflow-level timeouts; cancellation-aware waits |
| Cancellation | **BETTER** | Durable cooperative cancel across processes (DB flag → worker event), cancel-while-waiting-approval, terminal-state consistency tested |
| Versioning | **EQUIVALENT** | Immutable snapshots, rollback endpoint + UI, executions pinned to exact version; stage promotion missing (see Environments) |
| Environments | **PARTIAL** | Encrypted workspace env vars + `$env.*`; NO dev→staging→prod promotion pipeline or environment-scoped credential bindings |
| AI (generation + assistant) | **BETTER** | Registry-grounded generation (validator + repair loop + approval gate, born-draft), six validated/non-destructive assistant surfaces (P15/16) — distinctive vs prompt-and-pray generators |
| Agents | **PARTIAL** | Agent node w/ iteration cap + tool loop; only 3 tools (time/http/db); missing per-tool permission grants, token/cost budgets, Salesforce/RAG/workflow-as-tool |
| RAG | **EQUIVALENT** | Tenant-scoped collections, idempotent ingestion, deletion/reindex, citations, retrieval debugging (P18); reranking "if justified" not needed yet; doc-level ACLs beyond collection scope absent |
| Human approval | **BETTER** | Durable pause/resume across restarts, approver allowlists, timeout auto-reject, decision stamps in inspector/history, resume replays outputs (no repeated side effects) |
| MCP | **EQUIVALENT** | Tools/resources/prompts over the platform's own RBAC + tenant scoping |
| Templates | **EQUIVALENT** | Library w/ install/save-as/duplicate/customize, seeded system templates, share semantics |
| Multi-tenancy | **EQUIVALENT** | Orgs/workspaces/memberships; tenant-scoped workflows, credentials, executions, RAG collections, templates; cross-tenant probes return 404 (tested) |
| RBAC | **EQUIVALENT** | Workspace roles (owner/admin/editor/viewer) + per-workflow shares (view/edit) + admin flag; fine-grained per-collection roles not yet |
| Monitoring | **PARTIAL** | Auth'd Prometheus metrics, health/readiness, structured request logging, execution counters/histograms; **alerting rules/notification pack not shipped** |
| Security | **BETTER** | Audited (23/38): auth sweep, tenant probes, SSRF sandbox, expression battery, entropy-gated triggers, docs off by default, metrics authed, shell-free ops, audit trail — all as automated tests |
| API | **PARTIAL** | Complete management REST API + webhook inbound + MCP; **workflow-as-API (POST execute with minted API keys, sync/async) missing** — UserAPIKey model mints/hashes keys but nothing consumes them yet |
| Deployment | **EQUIVALENT** | Dockerfile/compose, verified migration chain + parity check, health/readiness, prod config validator, single-port SPA serving; K8s manifests not shipped |
| Scaling | **PARTIAL** | DB/Redis queue backends, external stateless workers, stale-claim recovery, load-test harness with measured numbers; no autoscaling story, embedded consumer default single-instance |
| Commercialization | **EQUIVALENT** | Orgs/plans/subscriptions, Stripe checkout + signed webhooks, quota enforcement (402), usage tracking, billing UI |

**Tally:** BETTER 10 · EQUIVALENT 16 · PARTIAL 4 · MISSING 1

## Prioritized backlog

| Pri | Gap | Why now | Size |
|---|---|---|---|
| **P0** | Workflow-as-API: POST `/api/w/{id}/execute` authenticated by the already-minted `UserAPIKey` (sync result or 202+poll), rate-limited, payload-schema validated | Unlocks every external integration story; the key infrastructure exists unused | M |
| **P0** | Global error workflow (`onError` binding → run handler workflow with failure context) | Operational maturity; pairs with existing retry/cancel machinery | S |
| **P1** | Sandboxed code/function node (restricted Python-expression or QuickJS/WASM container, no network/fs by default, resource-capped) | Closes the only MISSING builder capability without sacrificing the security posture | L |
| **P1** | Agent hardening (P17 completion): per-tool permission grants, token/cost budgets, Salesforce/RAG/sub-workflow tools | Turns the demo agent into a governed one | M |
| **P1** | Environment promotion: draft/test/prod stages, env-scoped credential bindings, promote-with-diff UI | Completes P24 intent started by versioning | M |
| **P2** | Reranking hook (only when cross-collection retrieval justifies it) + document-level ACLs | RAG scale-out | S/M |
| **P2** | Alerting pack (failure-rate/queue-depth rules → webhook/email) | Closes monitoring PARTIAL | S |
| **P2** | Sub-workflow input/output schemas (typed contracts, validated at save) | Composability safety | S |
| **P3** | Connector catalog growth via the SDK (community path), data tables, SSO/OIDC | Market-driven | L |

## Deliberate non-gaps

- Arbitrary JS in expressions and unrestricted code execution are
  excluded **on purpose**; the sandboxed-code-node work above is the
  controlled answer.
- Vector store stays sqlite_vec (P18 verdict): no demonstrated need to
  migrate; chroma remains optional.
