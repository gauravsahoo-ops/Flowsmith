# FLOWSMITH — 30-CATEGORY STRATEGIC GAP ANALYSIS

> **Analysis Date:** October 2026  
> **Benchmark Competitors:** n8n, Zapier, Make (Integromat), Workato, Tray.ai, Retool Workflows, Temporal, LangGraph  
> **Product Under Evaluation:** Flowsmith v0.3.1  

---

## 1. Overview Matrix

Flowsmith combines the graphical workflow simplicity of **Zapier/Make**, the deep developer control of **n8n**, the mission-critical resilience of **Temporal**, and the sovereign AI intelligence of **LangGraph**. Below is the exhaustive gap analysis across all 30 core dimensions.

---

## 2. Category-by-Category Deep Evaluation

### 1. Workflow Builder
- **Existing Capability:** Full visual canvas with drag-and-drop node placement, wiring, zooming, panning, minimap, multi-select, sticky notes, visual grouping, and auto-layout.
- **Current Implementation:** `@xyflow/react` v12.11.2 in `frontend/src/components/Canvas.jsx` and `WorkflowEditorPage.jsx`.
- **Problems:** Large graphs (>150 nodes) experience slight layout recalculation overhead; sub-flows cannot be expanded in-place on canvas.
- **Missing Capabilities:** In-place nested sub-flow expansion; multi-user live cursor presence; edge routing mode toggle (orthogonal vs smooth step vs bezier).
- **Recommended Architecture:** Implement custom edge routers with obstacle avoidance, virtualized viewport node rendering, and multi-canvas tabs for sub-workflows.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** React Flow 12, Zustand `workflowStore`
- **Testing Requirements:** Vitest canvas interaction tests, Playwright drag-and-drop test.

### 2. Workflow Execution
- **Existing Capability:** Asynchronous DAG topological execution with parallel branch grouping, item batching, cancellation, and pause/resume.
- **Current Implementation:** `backend/app/engine/executor.py` and `backend/app/execution_runtime.py`.
- **Problems:** Sub-workflow executions execute in-process rather than dishing out isolated child jobs to the distributed queue.
- **Missing Capabilities:** Checkpoint recovery from arbitrary intermediate nodes after server reboot; dynamic worker auto-scaling signals.
- **Recommended Architecture:** Persistent step checkpointing in PostgreSQL with idempotency token verification per node execution.
- **Priority:** High (P1)
- **Complexity:** High
- **Dependencies:** `SQLAlchemy`, `QueueWorker`, `execution_events`
- **Testing Requirements:** Recovery tests, crash simulation tests during long-running steps.

### 3. Triggers
- **Existing Capability:** Webhooks, cron/interval schedules, manual canvas runs, Salesforce Outbound Messages, Sub-workflow triggers, error triggers.
- **Current Implementation:** `backend/app/triggers/`, `backend/app/nodes/webhook.py`, `backend/app/nodes/schedule.py`.
- **Problems:** Polling triggers for SaaS tools (e.g. Google Drive new files, Slack new messages) require manual cron configuration rather than pre-packaged interval pollers with cursor state.
- **Missing Capabilities:** Dedicated polling trigger SDK with automatic delta state storage (`last_polled_cursor`).
- **Recommended Architecture:** `PollingTriggerManager` with durable deduplication state store in PostgreSQL/Redis.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** Database `workflow_state`, Scheduler
- **Testing Requirements:** Cursor advancement tests, duplicate event suppression tests.

### 4. Actions
- **Existing Capability:** 450+ declared operations across CRM, databases, messaging, file storage, AI, and developer tools.
- **Current Implementation:** `backend/app/connectors/`, `backend/app/engine/node_base.py`.
- **Problems:** Custom headers/query params on standardized connector actions are sometimes restricted to fixed inputs.
- **Missing Capabilities:** Universal "Override Parameters" accordion on every action card allowing raw HTTP header and query param injection.
- **Recommended Architecture:** Standardized input envelope mixing declared schema fields with a generic `_advanced_overrides` bag.
- **Priority:** Medium (P2)
- **Complexity:** Low
- **Dependencies:** Node editors, `SafeHTTPClient`
- **Testing Requirements:** Parameter precedence unit tests.

### 5. Connectors
- **Existing Capability:** 88+ connectors (69 native, 17 OpenAPI-generated, 2 deep enterprise CRM drivers). Dynamic schema discovery for Salesforce and Microsoft Dynamics.
- **Current Implementation:** `backend/app/connectors/registry.py`, `frontend/src/pages/IntegrationsPage.jsx`.
- **Problems:** Only Salesforce has full automated live sandbox certification; other connectors rely on verified mock contracts.
- **Missing Capabilities:** Community Connector SDK with 1-click publishing and versioned hot-reloading without restarting backend.
- **Recommended Architecture:** Dynamic plugin loader for third-party connector wheels with sandboxed manifest validation.
- **Priority:** Medium (P2)
- **Complexity:** Medium
- **Dependencies:** `ConnectorRegistry`, Python module loader
- **Testing Requirements:** Connector manifest schema tests, dynamic registration tests.

### 6. Credentials
- **Existing Capability:** AES-256-GCM v2 envelope encryption, multi-key rotation keyring, secret masking, connection testing.
- **Current Implementation:** `backend/app/credentials/`, `backend/app/security/crypto.py`.
- **Problems:** Organization-wide credential sharing policies are coarse-grained (workspace level only).
- **Missing Capabilities:** Role-based credential delegation (e.g. "Can Use in Workflows" vs "Can View/Edit Details").
- **Recommended Architecture:** Granular credential ACL matrix with RBAC permission flags (`USE`, `EDIT`, `SHARE`, `ADMIN`).
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `models/credential.py`, `app/api/access.py`
- **Testing Requirements:** Cross-role credential execution tests.

### 7. OAuth
- **Existing Capability:** 1-Click OAuth2 PKCE for Salesforce, Microsoft Dynamics CRM, Google (Gmail, Drive, Sheets, Calendar), Slack, HubSpot. Automatic token refresh.
- **Current Implementation:** `backend/app/oauth_providers.py`, `backend/app/api/oauth.py`.
- **Problems:** Adding a new custom OAuth2 provider requires Python code changes.
- **Missing Capabilities:** Generic Custom OAuth2 wizard in UI (Authorization URL, Token URL, Scopes, Client ID, Client Secret, Refresh handling).
- **Recommended Architecture:** Generic configurable OAuth2 state machine persisted in database with token rotation hooks.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `oauth_providers.py`, `QuickAddCredentialModal.jsx`
- **Testing Requirements:** End-to-end authorization code exchange tests with mock OAuth server.

### 8. AI Workflows
- **Existing Capability:** NL to workflow generator (`/ai`), task-based model router, 6-stage validation pipeline, bounded repair loop, non-destructive simulator.
- **Current Implementation:** `backend/app/ai/`, `frontend/src/components/AIBuilderConsole.jsx`.
- **Problems:** AI-generated workflows currently require the user to open the AI page; canvas does not have an in-line AI modification prompt bar.
- **Missing Capabilities:** In-canvas floating AI Copilot ("Add a Slack alert if budget > $5,000 to the selected node").
- **Recommended Architecture:** Direct canvas AI Copilot bar that performs surgical graph diffing (`WorkflowModifier`) directly in the editor.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `AIBuilderConsole`, `CanvasToolbar.jsx`, `workflowStore`
- **Testing Requirements:** In-canvas surgical diff application tests.

### 9. AI Agents
- **Existing Capability:** Autonomous ReAct reasoning agent (`AIAgentNode`), tool calling, built-in sovereign zero-LLM local intelligence fallback.
- **Current Implementation:** `backend/app/nodes/ai_agent.py`, `backend/app/ai/providers/builtin_provider.py`.
- **Problems:** Multi-agent interaction is limited to chained single-agent nodes.
- **Missing Capabilities:** Multi-agent collaboration frameworks (Supervisor, Debate, Consensus, Worker Swarms).
- **Recommended Architecture:** `MultiAgentSupervisorNode` coordinating parallel worker agents with shared blackboard memory.
- **Priority:** High (P1)
- **Complexity:** High
- **Dependencies:** `CompleteMemory`, `llm_router.py`
- **Testing Requirements:** Multi-agent dialogue convergence tests, tool budget enforcement tests.

### 10. RAG (Retrieval-Augmented Generation)
- **Existing Capability:** Production PostgreSQL `pgvector` store, document ingestion, chunking, semantic cosine search, citations generation.
- **Current Implementation:** `backend/app/rag/`, `backend/app/vectorstores/pgvector.py`.
- **Problems:** Document ingestion supports plain text, JSON, and markdown; PDF/DOCX parsing requires client-side extraction.
- **Missing Capabilities:** Native server-side PDF, Word, and Excel parser integration; hybrid search (dense pgvector embeddings + sparse full-text search / BM25).
- **Recommended Architecture:** PostgreSQL `pgvector` + `to_tsvector` hybrid reciprocal rank fusion (RRF) retriever.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** PostgreSQL full-text search, `SentenceTransformer`
- **Testing Requirements:** RRF ranking accuracy tests, citation integrity tests.

### 11. Memory
- **Existing Capability:** 6-tier cognitive architecture: Working, Summary Buffer, Episodic (pgvector + BM25), Structured Entity Graph, Scratchpad, Full Buffer.
- **Current Implementation:** `backend/app/ai/memory.py`.
- **Problems:** Entity memory extraction relies on regex heuristics when using the zero-LLM local engine.
- **Missing Capabilities:** Graphical Entity Memory visualizer in UI (`/knowledge` tab) allowing users to inspect and edit extracted agent knowledge facts.
- **Recommended Architecture:** Interactive Force-Directed Knowledge Graph in `KnowledgePage.jsx`.
- **Priority:** Medium (P2)
- **Complexity:** Medium
- **Dependencies:** `frontend/src/pages/KnowledgePage.jsx`, D3/ForceGraph
- **Testing Requirements:** Knowledge graph node/edge rendering tests.

### 12. Human Approval
- **Existing Capability:** Pause/resume execution state machine, email/webhook notification triggers, approval timeout auto-rejection, approver identity verification.
- **Current Implementation:** `backend/app/nodes/approval.py`, `frontend/src/pages/ApprovalsPage.jsx`.
- **Problems:** One-click approval from email requires navigating into the app.
- **Missing Capabilities:** Signed one-click HMAC approval action URLs sent directly inside Slack/Email messages.
- **Recommended Architecture:** Ephemeral signed JWT tokens for direct GET/POST webhook decision URLs with CSRF protection.
- **Priority:** Medium (P2)
- **Complexity:** Low
- **Dependencies:** `jwt.py`, `webhooks.py`
- **Testing Requirements:** Signed token expiration tests, single-use nonce validation tests.

### 13. Error Handling
- **Existing Capability:** Hierarchical error workflow dispatch (Node level $\rightarrow$ Workflow level $\rightarrow$ Workspace default error workflow).
- **Current Implementation:** `backend/app/execution_runtime.py`, `backend/app/nodes/error_trigger.py`.
- **Problems:** Error messages from external APIs can be raw JSON payloads.
- **Missing Capabilities:** AI-assisted error explanation and 1-click auto-repair suggestion in the execution log panel.
- **Recommended Architecture:** Integrated `WorkflowRepairer` button in `ExecutionInspector.jsx` translating raw HTTP errors into human solutions.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `ExecutionInspector.jsx`, `backend/app/ai/repair.py`
- **Testing Requirements:** Error categorization tests, diagnostic response schema tests.

### 14. Retries
- **Existing Capability:** Configurable exponential backoff, jitter, maximum retry count, status tracking, retry-after header parsing.
- **Current Implementation:** `backend/app/engine/executor.py`.
- **Problems:** Workflows cannot be configured with custom retry strategies per specific error code.
- **Missing Capabilities:** Granular retry rule matrix (e.g. "Retry on 429 and 503, fail fast on 401 and 404").
- **Recommended Architecture:** Declarative retry policy configuration in node settings (`retry_conditions: [{"status": [429, 503], "strategy": "exponential"}]`).
- **Priority:** Medium (P2)
- **Complexity:** Low
- **Dependencies:** `executor.py`, `HttpRequestNodeEditor.jsx`
- **Testing Requirements:** HTTP status-selective retry tests.

### 15. Scheduling
- **Existing Capability:** Cron expressions, interval math, timezone support, scheduler lock for multi-instance deployments.
- **Current Implementation:** `backend/app/scheduler.py`, `backend/app/nodes/schedule.py`.
- **Problems:** Timezone selection relies on IANA string inputs.
- **Missing Capabilities:** Human-friendly schedule builder in UI (e.g. "Every Monday at 9:00 AM New York time") with visual preview of upcoming 5 run times.
- **Recommended Architecture:** Interactive recurrence rule picker component with client-side next-run projection.
- **Priority:** Medium (P2)
- **Complexity:** Low
- **Dependencies:** `ScheduleTriggerEditor.jsx`
- **Testing Requirements:** Schedule projection calculation tests.

### 16. Webhooks
- **Existing Capability:** Instant trigger endpoints, custom paths, HMAC-SHA256 signature verification (GitHub, Stripe, custom), replay protection.
- **Current Implementation:** `backend/app/api/webhooks.py`.
- **Problems:** Inspecting incoming webhook test payloads requires triggering live webhooks.
- **Missing Capabilities:** In-browser Webhook Test Tunnel / Webhook Debugger capturing live payloads in real-time.
- **Recommended Architecture:** WebSocket-based webhook test listener that displays captured payloads directly inside `WebhookNodeEditor.jsx`.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `ws.py`, `WebhookNodeEditor.jsx`
- **Testing Requirements:** Payload capture stream tests.

### 17. Data Transformation
- **Existing Capability:** Safe expression engine (`{{ $json.field | upper }}`), Filter, Switch, Split, Merge, Compare Datasets, Set Variable.
- **Current Implementation:** `backend/app/engine/expressions.py`, `backend/app/nodes/`.
- **Problems:** Visual mapping between deeply nested JSON objects requires writing manual expressions.
- **Missing Capabilities:** Drag-and-drop visual schema mapper connecting upstream output fields to target fields with wires.
- **Recommended Architecture:** Visual Mapper panel with source tree on left, target tree on right, and interactive SVG mapping bezier connectors.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `MappingField.jsx`, `ExpressionHelper.jsx`
- **Testing Requirements:** Visual mapping state serialization tests.

### 18. Code Execution
- **Existing Capability:** Python and JavaScript sandboxed code nodes. AST security analyzer disallowing imports, builtins, and dunder traversal.
- **Current Implementation:** `backend/app/nodes/code.py`.
- **Problems:** JavaScript execution in Python uses embedded Duktape (`dukpy`), which lacks modern ES2022+ features (optional chaining, async/await).
- **Missing Capabilities:** Isolated Node.js / V8 sandboxed runner container option for full modern JavaScript/TypeScript compatibility.
- **Recommended Architecture:** Optional lightweight sidecar runner container using Node.js `vm` or `isolated-vm`.
- **Priority:** Medium (P2)
- **Complexity:** High
- **Dependencies:** Docker compose, worker execution runtime
- **Testing Requirements:** ES2022 syntax execution tests, sandbox breakout prevention tests.

### 19. Debugging
- **Existing Capability:** Execution timeline, step-by-step inputs/outputs JSON inspector, replay execution, safe node retry, flamegraphs.
- **Current Implementation:** `frontend/src/components/ExecutionInspector.jsx`, `LogsPanel.jsx`.
- **Problems:** Debugging a failed run requires inspecting historical execution detail views.
- **Missing Capabilities:** Visual execution replay directly on the workflow canvas, highlighting nodes with simulated progress timers.
- **Recommended Architecture:** Canvas Execution Replay mode scrubbing through the timeline with a slider.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `Canvas.jsx`, `executionStore`
- **Testing Requirements:** Canvas step replay scrubber tests.

### 20. Observability
- **Existing Capability:** OpenTelemetry W3C trace context, node-level latency metrics, Prometheus `/api/metrics`, structured logs.
- **Current Implementation:** `backend/app/telemetry/`, `backend/app/metrics.py`.
- **Problems:** Prometheus metrics endpoint requires external scraper (Grafana/Datadog) to view charts.
- **Missing Capabilities:** Built-in Monitoring dashboard with charts for workflow success rates, queue latency, token costs, and connector health.
- **Recommended Architecture:** Native Recharts dashboard in `MonitoringPage.jsx` visualizing 24h/7d system throughput and error rates.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `MonitoringPage.jsx`, backend `/api/monitoring`
- **Testing Requirements:** Time-series aggregation unit tests.

### 21. Collaboration
- **Existing Capability:** Workspaces, organizations, multi-tenancy, sharing workflows via JSON export/import.
- **Current Implementation:** `backend/app/models/organization.py`, `workspaces.py`.
- **Problems:** If two users edit the same workflow simultaneously, last write wins.
- **Missing Capabilities:** Workflow soft-locking with active collaborator presence indicators ("User X is currently editing").
- **Recommended Architecture:** WebSocket presence heartbeat locking active workflow edit sessions with 30s lease renewal.
- **Priority:** Medium (P2)
- **Complexity:** Medium
- **Dependencies:** `ws.py`, `workflowStore`
- **Testing Requirements:** Concurrent session lock contention tests.

### 22. Versioning
- **Existing Capability:** Workflow version history drawer, snapshot recovery, immutable rollback.
- **Current Implementation:** `frontend/src/components/WorkflowHistoryDrawer.jsx`, `backend/app/models/workflow.py`.
- **Problems:** Versions are created on every save without custom user commit messages.
- **Missing Capabilities:** Named versions / release tags (`v1.0.0-prod`) and visual JSON diff comparison between two versions.
- **Recommended Architecture:** Visual Side-by-Side Workflow Diff viewer displaying added, removed, and modified nodes between releases.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `WorkflowHistoryDrawer.jsx`, Monaco Diff Editor
- **Testing Requirements:** Workflow graph diff algorithm tests.

### 23. Deployment
- **Existing Capability:** Multi-environment support (development, testing, staging, production), environment variable encryption, 1-click promotion API.
- **Current Implementation:** `backend/app/environments.py`, `backend/app/api/environments.py`.
- **Problems:** Promoting a workflow requires matching credential names across environments manually.
- **Missing Capabilities:** Environment Credential Mapping Matrix ensuring target environment credentials exist before promotion is permitted.
- **Recommended Architecture:** Pre-promotion validation checklist verifying all required credentials and variables are bound in target environment.
- **Priority:** High (P1)
- **Complexity:** Low
- **Dependencies:** `environments.py`, `WorkflowsPage.jsx`
- **Testing Requirements:** Promotion gate negative verification tests.

### 24. Security
- **Existing Capability:** AES-256-GCM v2, SSRF blocking, CSRF validation, password hashing (Argon2/bcrypt), rate limiting, security headers.
- **Current Implementation:** `backend/app/security/`.
- **Problems:** API keys created for external webhook triggers lack granular IP CIDR allowlists.
- **Missing Capabilities:** CIDR IP restriction per API key / Webhook endpoint.
- **Recommended Architecture:** IP filter middleware evaluating client IP against configured CIDR masks.
- **Priority:** Medium (P2)
- **Complexity:** Low
- **Dependencies:** `safe_http_client.py`, `webhooks.py`
- **Testing Requirements:** CIDR match/reject unit tests.

### 25. Enterprise Administration
- **Existing Capability:** Multi-tenancy, workspace management, user roles (`admin`, `editor`, `viewer`), audit logs.
- **Current Implementation:** `backend/app/api/admin.py`, `audit.py`.
- **Problems:** Audit logs can only be viewed by administrators via raw list endpoint.
- **Missing Capabilities:** Audit Log explorer in UI with filtering by user, action, resource, IP address, and date range, with CSV export.
- **Recommended Architecture:** Dedicated Audit Log viewer page with searchable data table.
- **Priority:** Medium (P2)
- **Complexity:** Low
- **Dependencies:** `SettingsPage.jsx`, `backend/app/api/audit.py`
- **Testing Requirements:** Audit filter query tests.

### 26. Performance
- **Existing Capability:** 60 FPS canvas execution, `requestAnimationFrame` event batching, sub-millisecond database queries, cached schemas.
- **Current Implementation:** `frontend/src/stores/executionStore.js`, `backend/app/db.py`.
- **Problems:** Loading very large workflows (>200 nodes) renders all nodes in the DOM simultaneously.
- **Missing Capabilities:** Viewport virtualization (`onlyRenderVisibleElements`) enabled by default across all custom node types.
- **Recommended Architecture:** Pure memoized custom node wrappers with shallow prop comparisons.
- **Priority:** Medium (P2)
- **Complexity:** Low
- **Dependencies:** `CustomNode.jsx`, React Flow
- **Testing Requirements:** 500-node canvas zoom/pan benchmark.

### 27. Accessibility
- **Existing Capability:** Keyboard shortcuts for canvas actions (Ctrl+K, Delete, Ctrl+S, Ctrl+Z, Ctrl+B).
- **Current Implementation:** `frontend/src/layout/AppShell.jsx`, `CanvasToolbar.jsx`.
- **Problems:** Some icon-only buttons lack explicit `aria-label` or tooltips. Contrast ratio in dark mode is not fully audited against WCAG 2.2 AA.
- **Missing Capabilities:** Complete WCAG 2.2 AA compliant contrast palette, full keyboard tab-stop order, and screen reader announcements on execution state changes.
- **Recommended Architecture:** Automated accessibility audit suite with `@axe-core/playwright`.
- **Priority:** High (P1)
- **Complexity:** Medium
- **Dependencies:** `variables.css`, all icon buttons
- **Testing Requirements:** Axe-core accessibility test suite.

### 28. Mobile / Responsive UX
- **Existing Capability:** Responsive sidebar collapsing to mobile drawer, touch zoom on canvas, responsive topbar.
- **Current Implementation:** `frontend/src/styles/mobile.css`, `AppShell.jsx`.
- **Problems:** Canvas editing on small mobile screens is cramped.
- **Missing Capabilities:** Mobile-optimized "Read-Only Operations Mode" allowing technicians to view status, trigger manual runs, and approve decisions from phones.
- **Recommended Architecture:** Dedicated mobile view mode that defaults to list/timeline view on viewports <768px.
- **Priority:** Medium (P2)
- **Complexity:** Medium
- **Dependencies:** `mobile.css`, `WorkflowEditorPage.jsx`
- **Testing Requirements:** Viewport mobile emulation tests.

### 29. Developer Experience
- **Existing Capability:** Hot reload, Vitest, Pytest, `.runtime/` launcher scripts, clear error logs.
- **Current Implementation:** `package.json`, `pytest.ini`, `.runtime/`.
- **Problems:** Setting up a brand-new local developer environment requires manual python venv creation and postgres setup.
- **Missing Capabilities:** 1-command startup script (`npm run dev:all`) that checks dependencies, starts PostgreSQL/Redis via Docker, and runs dev servers.
- **Recommended Architecture:** Unified cross-platform CLI tool (`flowsmith dev`).
- **Priority:** High (P1)
- **Complexity:** Low
- **Dependencies:** `start.bat`, `package.json`
- **Testing Requirements:** Fresh environment bootstrap test.

### 30. Documentation
- **Existing Capability:** Master User Manual (`USER_MANUAL.md`), Changelog (`CHANGELOG.md`), Deployment requirements (`DEPLOYMENT_REQUIREMENTS.md`).
- **Current Implementation:** Project root documentation files.
- **Problems:** API documentation is disabled by default in production; SDK code examples are scattered.
- **Missing Capabilities:** In-app Documentation modal and interactive node documentation drawer accessible directly from any node configuration modal.
- **Recommended Architecture:** Integrated documentation drawer reading directly from connector markdown definitions.
- **Priority:** Medium (P2)
- **Complexity:** Low
- **Dependencies:** `NodeEditorModal.jsx`, `USER_MANUAL.md`
- **Testing Requirements:** Node documentation rendering tests.

---

## 3. Summary of Prioritized Gaps

1. **P1 (Immediate Architectural Focus):**
   - Universal Light / Dark / System Theming & Design System standardization.
   - Elimination of ad-hoc CSS and unification into modular design tokens.
   - Interactive In-Canvas AI Copilot & Surgical Diff visualization.
   - Unified Webhook testing & debugging capture tool.
   - Visual schema mapper with drag-and-drop connections.
   - WCAG 2.2 AA accessibility remediation across all interactive controls.
   - 1-Command dev experience & interactive documentation viewer.

2. **P2 (Strategic Scalability & Polish):**
   - Multi-agent collaboration frameworks (Supervisor/Blackboard).
   - Hybrid vector search (pgvector + sparse full-text search).
   - In-app Monitoring charts (latency, cost, throughput).
   - Named versions & visual side-by-side workflow diffing.
