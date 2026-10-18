# Flowsmith Gap Register & Defect Log

**Audit Date**: October 18, 2026  
**Auditor Persona**: Principal Software Architect, Senior Full-Stack Engineer, QA Lead, Production-Readiness Auditor  
**Audit Scope**: Complete Flowsmith codebase  
**Classification Rules**: Findings are evidence-based, derived from active code analysis and empirical test execution. Confirmed defects are strictly segregated from architectural risks and unverified assumptions.

---

## 1. Summary of Identified Gaps

| Severity | Defect Count | Risk Count | Discrepancy Count | Total |
|:---|:---:|:---:|:---:|:---:|
| **Critical** | 0 | 0 | 0 | **0** |
| **High** | 2 | 1 | 0 | **3** |
| **Medium** | 2 | 2 | 1 | **5** |
| **Low** | 1 | 1 | 1 | **3** |
| **Total** | **5** | **4** | **2** | **11** |

---

## 2. Confirmed Defects Register

### GAP-001: PostgreSQL Schema Drift — `executions.status` Column Length Overflow
- **Severity**: High
- **Category**: Database / Schema Integrity
- **Affected Files**:
  - `backend/app/models/execution.py` (Line 42)
  - `backend/alembic/versions/` (Database migration state)
- **Reproduction Steps**:
  1. Inspect column type in database: `\d executions` shows `status character varying(16)`.
  2. Inspect SQLAlchemy model in `backend/app/models/execution.py`: defines `status = Column(String(32), nullable=False, default="queued")`.
  3. Run `alembic check` in `backend`: fails with:
     ```
     [('modify_type', None, 'executions', 'status', {'existing_nullable': False, ...}, VARCHAR(length=16), String(length=32))]
     ```
  4. Attempt to insert or transition an execution into an extended state exceeding 16 characters (e.g., `waiting_for_approval` or `conditionally_skipped`).
  5. PostgreSQL raises: `psycopg2.errors.StringDataRightTruncation: value too long for type character varying(16)`.
- **Business Impact**: Workflow executions fail catastrophically during state updates if new statuses or approval-wait statuses exceed 16 characters, corrupting execution history and leaving executions permanently stuck in `running` or `queued`.
- **Proposed Fix**: Create an Alembic migration altering `executions.status` from `VARCHAR(16)` to `VARCHAR(32)` (or `VARCHAR(64)` for future expansion).
- **Acceptance Criteria**:
  - `alembic upgrade head` succeeds.
  - `alembic check` confirms zero drift for table `executions`.
  - Executions with statuses up to 32 characters persist without error.

---

### GAP-002: PostgreSQL Schema Drift — `oauth_states.client_secret` and `staged_contacts.row_number`
- **Severity**: High
- **Category**: Database / Schema Integrity
- **Affected Files**:
  - `backend/app/models/oauth_state.py` (Line 31)
  - `backend/app/models/staged_record.py` (Line 23)
  - `backend/alembic/versions/`
- **Reproduction Steps**:
  1. Run `alembic check`.
  2. Output confirms:
     ```
     [('modify_type', None, 'oauth_states', 'client_secret', ..., VARCHAR(length=255), String(length=512))]
     [('modify_type', None, 'staged_contacts', 'row_number', ..., INTEGER(), BigInteger())]
     ```
  3. Initiating an OAuth2 flow with an enterprise IdP (e.g., Azure AD or Okta) whose client secret or private key assertion exceeds 255 characters causes `DataError` on `oauth_states` creation.
  4. Staging large contact datasets where row counter exceeds `2,147,483,647` fails due to 32-bit signed integer limits.
- **Business Impact**: Blocks enterprise single-sign-on and OAuth connections for providers requiring long cryptographic secrets; limits bulk data ingestions.
- **Proposed Fix**: Add Alembic migration altering `oauth_states.client_secret` to `VARCHAR(512)` and `staged_contacts.row_number` to `BIGINT`.
- **Acceptance Criteria**:
  - Column modifications applied cleanly via Alembic.
  - `alembic check` passes without type modification alerts for these columns.

---

### GAP-003: Frontend Vitest Test Failure — `ExecutionDetailPage.test.jsx` Missing Router Mock
- **Severity**: Medium
- **Category**: Frontend Testing / CI
- **Affected Files**:
  - `frontend/src/pages/ExecutionDetailPage.test.jsx` (Lines 8–18)
  - `frontend/src/pages/ExecutionDetailPage.jsx` (Line 37)
- **Reproduction Steps**:
  1. Open terminal in `frontend/`.
  2. Run: `npx vitest run src/pages/ExecutionDetailPage.test.jsx`.
  3. Execution fails:
     ```
     FAIL src/pages/ExecutionDetailPage.test.jsx > ExecutionDetailPage Suite > renders loading state initially
     FAIL src/pages/ExecutionDetailPage.test.jsx > ExecutionDetailPage Suite > renders execution details and handles steps tab without ReferenceError
     Error: [vitest] No "useSearchParams" export is defined on the "react-router-dom" mock.
     ```
- **Business Impact**: Frontend automated unit test suite fails; broken navigation or regressions in execution step/timeline tab switching go undetected in CI.
- **Proposed Fix**: Update `vi.mock('react-router-dom', ...)` in `ExecutionDetailPage.test.jsx` to export `useSearchParams: () => [new URLSearchParams(), vi.fn()]`.
- **Acceptance Criteria**:
  - `npx vitest run src/pages/ExecutionDetailPage.test.jsx` passes with 2/2 tests passing.

---

### GAP-004: Frontend Vitest Test Failure — `SmithDrawerLogo.test.jsx` Missing Router Context
- **Severity**: Medium
- **Category**: Frontend Testing / CI
- **Affected Files**:
  - `frontend/src/components/SmithDrawerLogo.test.jsx` (Lines 22–34)
  - `frontend/src/components/TopBar.jsx` (Line 39)
- **Reproduction Steps**:
  1. Run: `npx vitest run src/components/SmithDrawerLogo.test.jsx`.
  2. Test fails:
     ```
     FAIL src/components/SmithDrawerLogo.test.jsx > SmithDrawer Logo Suite > renders default Flowsmith brand mark in the TopBar Smith button and removes ⚡
     Error: useNavigate() may be used only in the context of a <Router> component.
     ```
- **Business Impact**: CI test suite breaks whenever brand mark or TopBar navigation tests run.
- **Proposed Fix**: Wrap `<TopBar />` inside a `<MemoryRouter>` component in the unit test.
- **Acceptance Criteria**:
  - `npx vitest run src/components/SmithDrawerLogo.test.jsx` passes with 2/2 tests passing.

---

### GAP-005: Frontend Lint Cleanliness — 33 `oxlint` Unused Variables and Hook Dependency Warnings
- **Severity**: Low
- **Category**: Code Hygiene / Quality
- **Affected Files**:
  - `frontend/src/components/AIBuilderConsole.jsx` (`currentStep`)
  - `frontend/src/components/LogsPanel.jsx` (`nodeNamesKey` unnecessary dependency)
  - `frontend/src/components/LLMCredentialModal.jsx` (missing dependencies in `useEffect`)
  - `frontend/src/components/CanvasToolbar.jsx` (unnecessary dependencies in `useMemo`)
  - `frontend/src/pages/MonitoringPage.jsx` (`loadingCluster`)
- **Reproduction Steps**:
  1. Run: `npm run lint` in `frontend/`.
  2. Oxlint outputs 33 warnings across 220 files.
- **Business Impact**: Risk of subtle React stale-closure bugs in `LLMCredentialModal` and unnecessary canvas re-renders in `CanvasToolbar`.
- **Proposed Fix**: Resolve missing/unnecessary dependencies and prefix unused variables with `_`.
- **Acceptance Criteria**:
  - `npm run lint` completes with 0 errors and 0 warnings.

---

## 3. Architecture & Operational Risks

### GAP-006: Inactive Memory Limiting on Windows for Code Node
- **Severity**: Medium
- **Category**: Platform Architecture / Sandbox Limitation
- **Affected Files**:
  - `backend/app/nodes/code.py` (Lines 385–403)
- **Technical Analysis**:
  `CodeParams.max_memory_mb` is enforced in the child daemon via `import resource; resource.setrlimit(resource.RLIMIT_AS, (limit, limit))`. The Python standard library `resource` module is POSIX-only. On Windows operating systems, the import fails and is caught silently by `except Exception: pass`.
- **Risk Assessment**:
  When running on Windows developer machines or Windows container hosts, a malicious or poorly written user JavaScript script allocating gigabytes of memory cannot be constrained by `max_memory_mb`, leading to host memory exhaustion. Timeout enforcement remains functional via thread/process termination.
- **Mitigation / Proposed Fix**:
  Document Windows sandbox behavior. On Windows, integrate Windows Job Objects via `win32job.CreateJobObject()` and `win32job.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ...)` to enforce hard memory limits.
- **Acceptance Criteria**:
  - Memory bounds verified on POSIX systems; documented limitation on Windows hosts.

---

### GAP-007: Distributed JWT Revocation & Rate Limiting Relies on In-Memory Fallback when Redis is Absent
- **Severity**: Medium
- **Category**: Security / Multi-Tenancy
- **Affected Files**:
  - `backend/app/security/jwt.py` (Lines 139–158)
  - `backend/app/middleware/rate_limit.py`
  - `backend/app/config.py`
- **Technical Analysis**:
  When `REDIS_URL` is omitted, `revoke_token()` stores blacklisted JTIs in an in-memory dictionary `_token_blacklist`. If Flowsmith is deployed with multiple API workers or replicas behind a load balancer without Redis, a user logging out or an admin revoking a compromised token on Replica A will not invalidate the token on Replica B.
- **Risk Assessment**:
  A compromised token could continue to access resources on other cluster replicas until its natural expiration (default 24 hours).
- **Mitigation / Proposed Fix**:
  Update `validate_production_settings()` in `config.py` to require `REDIS_URL` whenever `APP_ENV=production` and multiple processes are detected, or store revoked JTIs in PostgreSQL `auth_sessions`.
- **Acceptance Criteria**:
  - Multi-instance deployments must enforce shared revocation state via Redis or DB.

---

### GAP-008: Catalog Identifier Mismatch (`slack_api` vs `slack`)
- **Severity**: Low
- **Category**: Connector Naming Parity
- **Affected Files**:
  - `frontend/src/all_catalog_items.json`
  - `backend/app/connectors/slack_connector.py`
  - `backend/app/nodes/registry.py`
- **Technical Analysis**:
  The static frontend catalog item list in `all_catalog_items.json` includes `slack_api`, whereas the backend connector is registered under `slack`.
- **Risk Assessment**:
  Workflows created via raw JSON imports specifying `slack_api` could fail graph validation unless aliased.
- **Mitigation / Proposed Fix**:
  Register an alias `'slack_api': 'slack'` in `app.connectors.registry._ALIASES` or normalize `all_catalog_items.json`.

---

## 4. Implemented vs. Partially Implemented vs. Mocked Functionality Matrix

| Platform Subsystem | Status | Implemented Components | Partially Implemented / Stubs | Missing / Defective |
|:---|:---:|:---|:---|:---|
| **Core Workflow Engine** | Implemented | Directed graph construction, cycle handling, topological sorting, parallel execution, expressions, timeout watchdog | None | None |
| **Node Registry** | Implemented | 71 canonical nodes, Pydantic parameter validation, dynamic operations | None | `flowsmith.data_load` missing in frontend static catalog |
| **Connector Ecosystem** | Implemented | 528 connectors registered, auto-discovery, lifecycle management | None | 1 naming discrepancy (`slack_api`) |
| **Credential Storage** | Implemented | Fernet + AES-256-GCM v2, multi-key rotation, redaction | None | None |
| **OAuth2 Engine** | Implemented | PKCE (S256), state TTL, popup postMessage listener, auto-refresh | None | DDL string length constraint on client_secret (GAP-002) |
| **Custom Code Execution** | Implemented | Python AST sandbox, Duktape JS subprocess daemon | Memory limit POSIX-only | No Windows memory limit enforcement |
| **AI Builder & RAG** | Implemented | 188 LLM providers, pgvector store, multi-tier memory (working, episodic, entity) | None | Sentence-transformers dev fallback if extras uninstalled |
| **Monitoring & Telemetry** | Implemented | OpenTelemetry W3C headers, Prometheus `/api/metrics`, dead-letter queue, live WS | None | None |
| **Disaster Recovery** | Implemented | PostgreSQL advisory locks, backup scripts, retention sweep | None | None |
