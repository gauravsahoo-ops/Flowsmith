# FLOWSMITH SECURITY AUDIT & HARDENING REPORT (PHASE 2)

**Report Version:** 2.0.0  
**Audit Date:** 2026-10-18  
**Audit Lead:** Principal Application Security Engineer  
**Target Application:** Flowsmith Workflow Automation Platform  
**Repository Root:** [Flowsmith Root](file:///c:/Flowsmith)  
**Security Baseline Status:** Phase 2 Hardened & Empirically Verified  

---

## 1. Executive Summary & Security Posture

Flowsmith is an enterprise workflow automation engine providing visual canvas orchestration, 528 registered external connectors, multi-tenant execution queues, credential management, AI Builder/RAG capabilities, and custom JavaScript/Python execution.

During Phase 1, the platform's architectural topology, component boundaries, and security attack surfaces were comprehensively cataloged. In Phase 2, confirmed security defects, schema drifts, authorization gaps, sandboxing boundaries, and injection vectors were systematically hardened and regression-tested.

### Key Hardening Achievements
1. **Schema Drift Remediation & Data Integrity**:
   - Resolved critical PostgreSQL column truncation risk by expanding [`executions.status`](file:///c:/Flowsmith/backend/app/models/execution.py) from `VARCHAR(16)` to `VARCHAR(32)` via Alembic migration [`b1d598391ba2_security_and_schema_drift_alignment.py`](file:///c:/Flowsmith/backend/alembic/versions/b1d598391ba2_security_and_schema_drift_alignment.py).
   - Expanded [`oauth_states.client_secret`](file:///c:/Flowsmith/backend/app/models/oauth.py) from `VARCHAR(255)` to `VARCHAR(512)` to safely store KMS/HSM keys.
   - Expanded [`staged_contacts.row_number`](file:///c:/Flowsmith/backend/app/models/staged_record.py) from `INTEGER` to `BIGINT`.
   - Created 12 missing multi-tenant security and performance indexes across `executions`, `auth_sessions`, and `staged_contacts`.
2. **Frontend Test Suite 100% Pass**:
   - Fixed Vitest test failures in [`ExecutionDetailPage.test.jsx`](file:///c:/Flowsmith/frontend/src/pages/ExecutionDetailPage.test.jsx) and [`SmithDrawerLogo.test.jsx`](file:///c:/Flowsmith/frontend/src/components/SmithDrawerLogo.test.jsx).
   - All 48 test files (464 unit and component tests) now pass with 0 errors.
3. **Comprehensive Negative Security Regression Suite**:
   - Implemented [`backend/tests/test_security/test_security_hardening.py`](file:///c:/Flowsmith/backend/tests/test_security/test_security_hardening.py) covering 18 negative test scenarios across authentication, IDOR, SSRF, sandboxing, secret redaction, and startup guards.
4. **Zero Tolerated Critical Exploitable Vulnerabilities**:
   - All 9 mandatory security domains specified in Phase 2 have been inspected, hardened, and verified with zero unaddressed critical vulnerabilities.

---

## 2. Mandatory Scope: Verification & Hardening Analysis

### Scope 1: Authentication, Session Expiry, Token Rotation, Password Reset & PKCE
- **JWT Lifecyle & Revocation**:
  - Implemented in [`backend/app/security/jwt.py`](file:///c:/Flowsmith/backend/app/security/jwt.py).
  - Tokens contain cryptographically secure `jti` nonces, issued at (`iat`), expiry (`exp`), and subject (`sub`).
  - Single-session logout and explicit token invalidation are backed by Redis-distributed blacklist with in-memory fallback via [`revoke_token()`](file:///c:/Flowsmith/backend/app/security/jwt.py).
  - Token freshness enforcement: [`token_is_stale()`](file:///c:/Flowsmith/backend/app/api/auth.py) invalidates all outstanding bearer tokens issued before a user's [`tokens_valid_from`](file:///c:/Flowsmith/backend/app/models/user.py) cutoff (e.g. upon password reset or administrative session termination).
- **Password Reset Security**:
  - Implemented in [`backend/app/api/auth.py`](file:///c:/Flowsmith/backend/app/api/auth.py).
  - Reset tokens are generated via `secrets.token_urlsafe(32)` and stored exclusively as SHA-256 hashes (`PasswordResetToken.token_hash`).
  - Tokens are single-use (`used_at` timestamp recorded upon consumption) and expire after a configurable TTL (default 1800s).
  - Upon successful password reset, all concurrent reset tokens for that user are revoked, and `user.tokens_valid_from` is bumped to `datetime.now(UTC)`, killing all active user sessions across all devices.
  - Host header injection defense: reset URLs derive strictly from [`PUBLIC_URL`](file:///c:/Flowsmith/backend/app/config.py) in production, never from attacker-controllable `Host` or `X-Forwarded-Host` headers.
- **Timing Attack Mitigation**:
  - [`login()`](file:///c:/Flowsmith/backend/app/api/auth.py) executes a constant-work path (`verify_password(body.password, DUMMY_PASSWORD_HASH)`) when an email does not exist, preventing timing-based user enumeration.
- **OAuth & PKCE**:
  - Defined in [`backend/app/oauth_providers.py`](file:///c:/Flowsmith/backend/app/oauth_providers.py) and [`backend/app/api/oauth.py`](file:///c:/Flowsmith/backend/app/api/oauth.py).
  - OAuth 2.0 authorization code flows utilize PKCE `code_challenge` (S256 method) with high-entropy `code_verifier`.
  - State tokens (`OAuthState`) are stored with cryptographic hashes, strict TTL (600s), and validated upon callback.

---

### Scope 2 & 9: Authorization, Tenant Boundaries, RBAC & IDOR Elimination
- **Backend-Enforced Authorization**:
  - Every protected API endpoint depends on [`get_current_user`](file:///c:/Flowsmith/backend/app/api/auth.py).
  - Access control logic is centralized in [`backend/app/api/access.py`](file:///c:/Flowsmith/backend/app/api/access.py).
- **Workflow Isolation**:
  - Workflows require ownership (`rec.user_id == user.id`) or explicit [`WorkflowShare`](file:///c:/Flowsmith/backend/app/models/workflow.py) grants (`view` or `edit`).
  - Unauthorized requests to `/api/workflows/{id}` return HTTP 404 (existence hidden) rather than HTTP 403, preventing resource enumeration across tenants.
- **Execution History & Log Isolation**:
  - Implemented in [`backend/app/api/executions.py`](file:///c:/Flowsmith/backend/app/api/executions.py).
  - Execution list and search queries restrict records via `Execution.workflow_id.in_(accessible_ids(db, user))`.
  - Single execution access is governed by `_can_view_execution()` and `_can_edit_execution()`, checking parent workflow permissions.
- **Credential Ownership**:
  - Implemented in [`backend/app/api/credentials.py`](file:///c:/Flowsmith/backend/app/api/credentials.py).
  - Listing, updating, and deleting credentials query strictly by `Credential.user_id == user.id`.
  - Organization-shared connected app configurations filter strictly by `User.organization_id == user.organization_id`.
- **Data Tables & Files Isolation**:
  - Data tables ([`backend/app/api/data_tables.py`](file:///c:/Flowsmith/backend/app/api/data_tables.py)) enforce `_require_table_access()`, checking workspace membership and edit permissions.
  - File storage ([`backend/app/api/files.py`](file:///c:/Flowsmith/backend/app/api/files.py)) enforces workspace permissions via `_can_access_workspace()`.

---

### Scope 3: Credential Encryption at Rest, Key Rotation & Secret Redaction
- **Multi-Cipher Encryption at Rest**:
  - Implemented in [`backend/app/security/crypto.py`](file:///c:/Flowsmith/backend/app/security/crypto.py).
  - Supports AES-256-GCM v2 authenticated encryption (`cipher_encrypt_v2`) using a 96-bit random nonce (`os.urandom(12)`) and 128-bit authentication tag.
  - Maintains backwards-compatible decryption for Fernet v1 tokens (`k0:...`).
- **Key Rotation**:
  - Supports comma-separated keys in `CREDENTIALS_ENCRYPTION_KEY`.
  - `_current_key()` encrypts all new records using Key 0; `decrypt_text()` iterates through all configured keys, allowing seamless zero-downtime key rotation.
- **Safe Credential Editing & Exposure Prevention**:
  - Credential GET endpoints (`/api/credentials`, `/api/credentials/oauth-config/{provider}`) NEVER return plaintext secret keys or tokens.
  - Only metadata (`id`, `name`, `type`, `created_at`), masked previews (`client_id_preview`), and boolean indicators (`has_secret: True`) are returned to clients.
- **Execution Trace Redaction**:
  - Implemented in [`backend/app/engine/redact.py`](file:///c:/Flowsmith/backend/app/engine/redact.py).
  - `redact_sensitive()` inspects all dictionary keys in node inputs, outputs, and execution traces against sensitive markers (`password`, `secret`, `token`, `api_key`, `auth`, `cookie`, `credential`, `private_key`).
  - Values under sensitive keys are recursively replaced with `••••••••`.

---

### Scope 4: SSRF Protection & Network Boundary Controls
- **Shared SSRF Guard Architecture**:
  - Implemented in [`backend/app/security/ssrf.py`](file:///c:/Flowsmith/backend/app/security/ssrf.py) and [`backend/app/security/safe_http_client.py`](file:///c:/Flowsmith/backend/app/security/safe_http_client.py).
  - Applied across HTTP Request nodes, Webhook triggers, RSS feeds, SOAP requests, and Connector probes.
- **Defense in Depth Checks**:
  1. **Scheme Validation**: Whitelists strictly `http`, `https`, `ws`, `wss`. Blocks `file://`, `gopher://`, `ftp://`, `dict://`.
  2. **IPv4 Loopback & Private Address Blocking**:
     - Loopback (`127.0.0.0/8`, `0.0.0.0`).
     - RFC 1918 Private Ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
     - Carrier-Grade NAT (`100.64.0.0/10`).
  3. **Cloud Metadata Endpoint Blocking**:
     - AWS, GCP, Azure metadata: `169.254.169.254`.
     - AWS ECS task metadata: `169.254.170.2`.
     - IPv6 Link-Local (`fe80::/10`).
  4. **Alternative IP Encoding Defense**:
     - `_parse_literal_ip()` decodes decimal representations (e.g. `2130706433` for `127.0.0.1`) and hexadecimal representations (e.g. `0x7f000001`), ensuring encoded bypasses are rejected.
  5. **Asynchronous DNS Pre-Resolution**:
     - `_resolve_ips()` resolves hostnames prior to outbound dispatch to defeat split-horizon DNS and DNS rebinding attacks. In production, unresolvable hostnames fail closed (`SSRF_BLOCKED`).
  6. **Production Escape Hatch Guard**:
     - [`validate_production_settings()`](file:///c:/Flowsmith/backend/app/config.py) rejects server startup if `SAFE_HTTP_ALLOWED_HOSTS` or `SAFE_HTTP_ALLOWED_PORTS` is set in production without `ALLOW_SSRF_BYPASS=true`.

---

### Scope 5: Secure Execution of JavaScript & Python Code
- **Python AST Visitor Sandbox**:
  - Implemented in [`backend/app/nodes/code.py`](file:///c:/Flowsmith/backend/app/nodes/code.py) via [`PythonSecurityAnalyzer(ast.NodeVisitor)`](file:///c:/Flowsmith/backend/app/nodes/code.py).
  - Prohibits all `import` and `from ... import` statements.
  - Prohibits all dunder attributes (`__class__`, `__bases__`, `__subclasses__`, `__globals__`, `__code__`, `__builtins__`, `__dict__`, etc.) to block object-graph traversal and CPython sandbox breakouts.
  - Prohibits dangerous built-in functions: `eval`, `exec`, `compile`, `open`, `input`, `getattr`, `setattr`, `delattr`, `vars`, `dir`, `globals`, `locals`.
  - Execution runs in an isolated namespace containing strictly whitelisted builtins (`_SAFE_BUILTINS`).
- **Python Execution Watchdog & Hard Timeout**:
  - Enforced via `_exec_with_timeout()`.
  - Installs a thread trace hook (`sys.settrace(_deadline_watch)`) inside the worker thread that raises `TimeoutError` on line events once the monotonic deadline is exceeded.
- **JavaScript Sandboxing via Duktape Daemon**:
  - JavaScript code is executed in an isolated child subprocess running Duktape (`dukpy.JSInterpreter()`).
  - Duktape is an embedded pure-ECMAScript interpreter with no access to Node.js APIs (`process`, `fs`, `child_process`, `net`, `require`).
  - Memory caps are configured via process arguments (`max_memory_mb`), and the daemon process is terminated (`proc.kill()`) and cleanly respawned if execution exceeds the timeout budget.

---

### Scope 6: Injection, Traversal, Deserialization & File Security
- **SQL Injection Prevention**:
  - Flowsmith relies strictly on SQLAlchemy ORM parameterized queries with bind variables across all 41 tables. Raw SQL string concatenation is prohibited.
- **Path Traversal & Malicious File Uploads**:
  - Implemented in [`backend/app/api/files.py`](file:///c:/Flowsmith/backend/app/api/files.py).
  - Filenames are sanitized with `filename.split("/")[-1].split("\\")[-1][:180]`, dropping all directory navigation characters (`..`, `/`, `\`).
  - Objects are stored under random UUID keys (`{uuid.uuid4().hex}_{safe_name}`).
  - Upload file streams enforce a strict 50 MB limit, terminating oversized streams before buffering.
- **Stored XSS Prevention on Downloads**:
  - Content serving strictly white-lists safe MIME types (`_INLINE_SAFE_MIME_PREFIXES`).
  - Active web content and SVG vectors (`image/svg+xml`) are never inlined same-origin.
  - `X-Content-Type-Options: nosniff` and RFC 5987 encoded `Content-Disposition` headers are attached to all file responses.
- **CSV Formula Injection (Spreadsheet Macro Injection)**:
  - Implemented in [`sanitize_csv_cell()`](file:///c:/Flowsmith/backend/app/engine/redact.py).
  - All CSV export endpoints prefix cells starting with formula triggers (`=`, `+`, `-`, `@`, `\t`, `\r`) with a single quote (`'`), neutralizing executable Excel/Sheets payloads.

---

### Scope 7: Security Headers, CORS, Rate Limiting & Audit Trails
- **CORS Configuration**:
  - Configured in [`backend/app/main.py`](file:///c:/Flowsmith/backend/app/main.py).
  - Wildcard CORS (`*`) combined with credentials is explicitly blocked by [`validate_production_settings()`](file:///c:/Flowsmith/backend/app/config.py) in production mode.
- **Rate Limiting & Brute-Force Throttling**:
  - Implemented via [`SlidingWindowLimiter`](file:///c:/Flowsmith/backend/app/security/ratelimit.py) and [`get_login_throttle()`](file:///c:/Flowsmith/backend/app/security/ratelimit.py).
  - Tracks failed attempts by email and client IP with exponential backoff and lockouts (`_raise_locked()`).
  - Registration is limited to 100 req/min/IP; password reset is limited to 20 req/min/IP.
- **Audit Logging**:
  - Implemented in [`backend/app/audit.py`](file:///c:/Flowsmith/backend/app/audit.py).
  - All critical security actions (`auth.register`, `auth.login`, `auth.login_failed`, `auth.password_reset`, `workflow.create`, `workflow.delete`, `credential.create`, `credential.delete`, `execution.run`) persist structured records in the PostgreSQL `audit_events` table with actor user ID, target ID, action timestamp, and client IP.

---

### Scope 8: Production Startup Guards & Elimination of Insecure Defaults
- **Fail-Fast Startup Validation**:
  - Enforced in [`validate_production_settings()`](file:///c:/Flowsmith/backend/app/config.py).
  - When `APP_ENV=production`, Flowsmith will refuse to boot if:
    1. `CREDENTIALS_ENCRYPTION_KEY` is empty.
    2. `JWT_SECRET` is missing or set to the default `"dev-only-secret-change-me"`.
    3. `DATABASE_URL` references SQLite.
    4. `CORS_ORIGINS` contains wildcard `"*"`.
    5. `SAFE_HTTP_ALLOWED_HOSTS` or `SAFE_HTTP_ALLOWED_PORTS` is configured without `ALLOW_SSRF_BYPASS=true`.

---

## 3. Database Schema Drift Alignment

During Phase 1, differences between SQLAlchemy ORM models and PostgreSQL physical tables were discovered. In Phase 2, these were aligned via migration [`b1d598391ba2_security_and_schema_drift_alignment.py`](file:///c:/Flowsmith/backend/alembic/versions/b1d598391ba2_security_and_schema_drift_alignment.py) and applied to `automate`:

| Table | Column / Index | Previous State | Target State | Hardening Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `executions` | `status` | `VARCHAR(16)` | `VARCHAR(32)` | Prevents `DataError: value too long` when writing `waiting_for_approval` |
| `oauth_states` | `client_secret` | `VARCHAR(255)` | `VARCHAR(512)` | Accommodates long KMS tokens and encrypted secrets |
| `staged_contacts` | `row_number` | `INTEGER` | `BIGINT` | Prevents integer overflow during large CSV imports |
| `auth_sessions` | `ix_auth_sessions_user_id` | Missing | Indexed | Accelerates session lookup and user logout sweeps |
| `executions` | `ix_executions_workspace_id` | Missing | Indexed | Enforces fast tenant-scoped execution queries |
| `executions` | `ix_executions_organization_id` | Missing | Indexed | Enforces multi-tenant organizational isolation |
| `executions` | `ix_executions_correlation_id` | Missing | Indexed | Distributed tracing and telemetry correlation |
| `staged_contacts` | `ix_staged_contacts_exec_row` | Missing | Indexed | Fast idempotent contact staging and deduplication |

Verification: `alembic current` confirms `b1d598391ba2 (head)`.

---

## 4. Empirical Test Verification Matrix

### Negative Security Test Suite (`backend/tests/test_security/test_security_hardening.py`)

| Test Identifier | Domain | Description | Expected Result | Verified Status |
| :--- | :--- | :--- | :--- | :--- |
| `test_unauthenticated_requests_fail` | Auth | Unauthenticated requests to protected endpoints | HTTP 401 Unauthorized | **PASS** |
| `test_expired_token_rejected` | Auth | Request with expired JWT timestamp | HTTP 401 Unauthorized | **PASS** |
| `test_tampered_token_signature_rejected` | Auth | Request with modified cryptographic signature | HTTP 401 Unauthorized | **PASS** |
| `test_revoked_token_rejected_immediately` | Auth | Token used after explicit JTI revocation | HTTP 401 Unauthorized | **PASS** |
| `test_stale_token_after_password_reset` | Auth | Bearer token issued before `tokens_valid_from` | Detected as Stale (`True`) | **PASS** |
| `test_user_b_cannot_access_user_a_workflow` | IDOR | Cross-tenant GET, PUT, DELETE, RUN on workflow | HTTP 404 / 403 Forbidden | **PASS** |
| `test_user_b_cannot_access_user_a_credentials` | IDOR | Cross-tenant credential access or modification | HTTP 404 Not Found | **PASS** |
| `test_ssrf_rejects_literal_loopback_and_metadata` | SSRF | Outbound HTTP to 127.0.0.1 and 169.254.169.254 | `SSRF_BLOCKED` Error | **PASS** |
| `test_ssrf_rejects_rfc1918_private_ranges` | SSRF | Outbound HTTP to 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 | `SSRF_BLOCKED` Error | **PASS** |
| `test_ssrf_parses_hex_and_decimal_representations` | SSRF | Outbound HTTP to decimal (`2130706433`) and hex (`0x7f000001`) | Blocked (`True`) | **PASS** |
| `test_ssrf_blocks_non_http_schemes` | SSRF | Outbound requests with `file://`, `gopher://`, `ftp://` | `SSRF_BLOCKED` Error | **PASS** |
| `test_python_blocks_all_import_statements` | Sandbox | Python code with `import os`, `import sys`, `from ...` | `SANDBOX_VIOLATION` Error | **PASS** |
| `test_python_blocks_dunder_attribute_traversal` | Sandbox | Breakout attempts via `().__class__.__bases__` | `SANDBOX_VIOLATION` Error | **PASS** |
| `test_python_blocks_dangerous_builtins` | Sandbox | Attempts to call `eval`, `exec`, `open`, `getattr` | `SANDBOX_VIOLATION` Error | **PASS** |
| `test_python_infinite_loop_timeout_protection` | Sandbox | Python code with infinite `while True: pass` loop | Hard Timeout Enforced | **PASS** |
| `test_redact_sensitive_masks_sensitive_keys` | Redaction | Masking sensitive keys (`password`, `token`, `secret`) | Replaced with `••••••••` | **PASS** |
| `test_sanitize_csv_cell_escapes_formulas` | Injection | Cells beginning with `=`, `+`, `-`, `@`, `\t`, `\r` | Escaped with single quote | **PASS** |
| `test_production_startup_validation` | Config | Production startup with weak secrets, SQLite, wildcard CORS | `ConfigError` Raised | **PASS** |

### Frontend Unit & Component Suite
- **Command**: `npx vitest run`
- **Result**: 48 test files passed (100%), 464 tests passed, 0 failures.

---

## 5. Security Limitations & Documented Residual Risks

In accordance with enterprise audit standards, the following architectural boundaries and accepted residual risks are documented:

1. **Host-Level POSIX Resource Limits**:
   - `resource.setrlimit(resource.RLIMIT_AS)` is POSIX-only. On Windows development hosts, memory limiting is silently skipped. In production Linux containers (Docker / Kubernetes), POSIX resource limits and container cgroup memory limits (`deploy.resources.limits.memory`) enforce hard memory boundaries.
   - *Compensating Control*: Hard execution time limits are enforced platform-agnostically via thread trace watchdogs (`sys.settrace`), and JavaScript execution is isolated in an external subprocess daemon.
2. **Multi-Replica Token Revocation Dependency**:
   - Immediate JTI revocation across multiple backend pods relies on Redis (`REDIS_URL`). If Redis is unavailable or unconfigured, revocation falls back to the in-memory `_token_blacklist`.
   - *Compensating Control*: Production deployments must configure `REDIS_URL` as defined in `docker-compose.yml`. Database-level `user.tokens_valid_from` cutoff ensures that password resets and account suspensions invalidate sessions across all pods regardless of Redis state.
3. **In-Process Python Sandbox vs High-Risk Workloads**:
   - Python code execution runs within the backend Python runtime, protected by AST analysis and restricted builtins. While comprehensive against script-level escapes, it does not provide kernel-level virtualization.
   - *Recommendation for Untrusted Multi-Tenant SaaS*: For public untrusted code execution, deploy workers with gVisor / Firecracker microVMs or external isolated container runners.

---

## 6. Audit Conclusion & Next Steps

All items in the **PHASE 2 — FLOWSMITH SECURITY HARDENING** mandatory scope have been inspected, implemented, and verified with empirical evidence.

- Schema drift between SQLAlchemy models and PostgreSQL tables has been resolved.
- Frontend test suite is 100% green (464/464 passing).
- Backend security hardening negative regression suite is in place and verified.
- Production startup fail-fast security validation is enforced.
- No known unresolved critical vulnerabilities remain in Flowsmith.
