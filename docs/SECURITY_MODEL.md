# Flowsmith Enterprise Security Model & Threat Specifications

**Version:** 1.0.0 Enterprise  
**Target Compliance:** SOC2 Type II, HIPAA, GDPR, ISO 27001 Readiness  
**Core Principles:** Zero-Trust Ingress, Complete Data Sovereignty, Defense-in-Depth, Strict Subprocess Isolation

---

## 1. Threat Model & Attack Surface Overview

Flowsmith is engineered to operate safely within enterprise VPCs and private data centers. The platform isolates untrusted inputs across five distinct attack surfaces:

```
[Inbound Webhooks] ──> [HMAC & Replay Guard] ──> [Execution Engine]
[Outbound Requests] ──> [SSRF & DNS Guard]   ──> [External Network]
[User Scripting]   ──> [Process Sandbox]    ──> [Isolated Subprocess]
[Credentials]      ──> [AES-256/Fernet Vault]──> [Ephemeral Memory]
[AI Prompt Inputs] ──> [Schema AST Barrier]  ──> [Deterministic DAG]
```

---

## 2. Credential Vault & Encryption at Rest

### Encryption Specifications

- **Cipher Suites**: Multi-key envelope encryption utilizing **Fernet (AES-128-CBC with HMAC-SHA256 authentication)** and **AES-256-GCM**.
- **Key Derivation & Management**: Keys configured via `FLOWSMITH_SECRET_KEY` (or external KMS such as AWS KMS, HashiCorp Vault).
- **Zero Secret Exposure**:
  - Encrypted ciphertext stored in `credentials.encrypted_data`.
  - Plaintext values are **never logged**, **never included in execution traces**, and **never returned in API responses** (masked with `••••••••`).
  - Decryption occurs only in ephemeral worker memory milliseconds prior to external dispatch and is wiped upon request completion.
- **Key Rotation**:
  - Seamless key rotation supported via dual-key decryption fallback.
  - Re-encryption routines update existing database records without application downtime.

### Multi-Factor Authentication

- Optional TOTP MFA for local password accounts, with encrypted secrets at rest.
- Enrollment and disabling require the current password; login issues a 5-minute
  `purpose=mfa` challenge instead of a bearer JWT.
- Purpose-scoped challenge tokens are rejected by `decode_token` for all normal
  token consumers (API, WebSocket, files, sessions, SAML logout).
- Accepted TOTP counters are stored to reject replay; ten single-use recovery
  codes are stored only as SHA-256 hashes.
- Organizations can require MFA. A non-enrolled user receives a 10-minute,
  purpose-scoped enrollment token after password/LDAP verification; the token
  can only call the enrollment endpoints, and enrollment completion issues the
  normal login session.

### WebAuthn/passkeys

- Passkeys are verified with the browser's WebAuthn ceremony; private keys never
  leave the authenticator.
- Registration and login challenges are single-use, purpose-scoped JWTs and are
  rejected by every normal token consumer.
- RP ID, origin, challenge, user presence, and configured user verification are
  checked server-side.
- Challenge reuse is blocked by JWT revocation after success, and failure
  attempts are throttled per account/IP.

### LDAP

- LDAP passwords are used only for a directory bind and are never persisted.
- Service-account credentials are used only for search; user search values and
  DNs are escaped before filter construction.
- A deactivated Flowsmith user cannot be reactivated by LDAP, and directory
  outages fail closed.
- Production requires LDAPS or StartTLS with certificate verification; group
  mapping is limited to the global admin/member role.

---

## 3. Webhook Ingestion & Anti-Replay Defense

### Cryptographic Signature Verification (`app.api.webhooks`)

Inbound webhooks validate payload authenticity and integrity before queueing:

1. **HMAC-SHA256 & HMAC-SHA1**:
   - Compares signatures using constant-time string comparison (`hmac.compare_digest`) to prevent timing side-channel attacks.
   - Supports GitHub (`X-Hub-Signature-256`), generic webhooks (`X-Webhook-Signature`, `X-Signature`), and custom headers.
2. **Stripe Signature Protocol (`stripe-signature`)**:
   - Parses timestamped signatures: `t=timestamp,v1=signature`.
   - Computes expected HMAC over `t.payload`.
   - **Replay Protection**: Rejects payloads with timestamps older or newer than 300 seconds (configurable clock drift tolerance).
3. **Bearer Token & Query Authentication**:
   - Validates pre-shared secret tokens via `Authorization: Bearer <token>`, `X-Webhook-Token`, or URL parameters.
4. **Ingress Rate Limiting**:
   - Distributed sliding-window rate limiting backed by Redis prevents volumetric Denial-of-Service attacks.

---

## 4. SSRF (Server-Side Request Forgery) Prevention

All outgoing HTTP requests initiated by nodes (`http_request`, connectors, webhooks) pass through the security URL validator (`app.security.url_validator`):

### Enforced Network Boundaries

- **Private & Reserved Ranges Blocked**:
  - `10.0.0.0/8` (RFC 1918)
  - `172.16.0.0/12` (RFC 1918)
  - `192.168.0.0/16` (RFC 1918)
  - `127.0.0.0/8` (Loopback IPv4)
  - `::1` (Loopback IPv6)
  - `fc00::/7` (Unique Local Address)
  - `fe80::/10` (Link-Local IPv6)
- **Cloud Metadata Endpoints Blocked**:
  - `169.254.169.254` (AWS EC2, GCP, Azure, OpenStack instance metadata service)
- **DNS Rebinding Mitigation**:
  - DNS resolution occurs immediately prior to socket connection.
  - Outbound connections are bound to the verified resolved IP address rather than the raw hostname.

---

## 5. Sandboxed Code Execution Isolation

User-defined custom code steps (`python_code`, `javascript_code`) execute within an isolated subprocess sandbox (`app.nodes.code`):

| Control | Python Sandbox | JavaScript Sandbox |
| :--- | :--- | :--- |
| **Runtime** | Dedicated `python -S` subprocess | Dedicated `node` subprocess |
| **Memory Ceiling** | Enforced via OS limits (default: 256MB) | `--max-old-space-size=256` |
| **Execution Timeout**| Enforced SIGKILL (default: 15s) | Enforced SIGKILL (default: 15s) |
| **Forbidden Imports**| `os`, `sys`, `subprocess`, `socket`, `ctypes` | `fs`, `child_process`, `net`, `http` |
| **Filesystem Access**| Read-only sandbox directory; no write access | Read-only sandbox directory; no write access |
| **Process Privileges**| Dropped unprivileged UID/GID | Dropped unprivileged UID/GID |

---

## 6. Access Control, Workspaces & Multi-Tenancy

### Role-Based Access Control (RBAC)

Every workspace resource (Workflows, Credentials, Data Tables, Vector Collections) is governed by strict tenant boundaries:

- **Workspace Roles**:
  - `owner`: Complete administrative control, billing/license, workspace deletion.
  - `admin`: Member invitation, environment promotion, global credentials.
  - `editor`: Create, modify, test, and activate workflows.
  - `viewer`: Read-only access to canvas, execution history, and audit logs.
- **Workflow Sharing**:
  - Explicit per-workflow permission grants (`view`, `edit`, `execute`) across individual users or teams.

---

## 7. AI Safety & Prompt Injection Defenses

1. **System Prompt Fencing**:
   - Strict separation between system instructions and user-supplied data payloads.
   - User inputs are treated as inert strings, wrapped in delimiter blocks (`<<<DATA>>>`).
2. **Deterministic Schema AST Validation**:
   - LLMs are never permitted to generate arbitrary executable code directly into the workflow canvas.
   - The AI Copilot outputs a structured JSON DAG that is parsed, validated against the Pydantic `Workflow` AST schema, and verified against connector definition contracts.
   - Unknown node types or unmapped parameters are rejected at the compiler level.
3. **Deterministic Auto-Repair Boundaries**:
   - The Auto-Repair engine fixes parameter drift and syntax errors by introspecting upstream JSON schemas.
   - It cannot introduce new unapproved network connections or external endpoints.

---

## 8. Audit Logging & Compliance Controls

- **Audit Events Table (`audit_events`)**:
  - Every mutating action (create, edit, delete, activate, promote, credential read, login) produces an immutable structured audit log.
  - Captured fields: `id`, `user_id`, `action`, `target_type`, `target_id`, `ip_address`, `user_agent`, `payload_diff`, `created_at`.
- **Retention & Immutability**:
  - Logs cannot be modified or deleted via user-facing APIs.
  - Retention policies allow export to enterprise SIEM systems (Splunk, Datadog, Elastic).

---

## 9. Connector Pack Supply Chain

Connector packs are installed only by admins. The installer:

- fetches manifests and OpenAPI specs through the SSRF-safe HTTP client with
  timeouts and response-size caps;
- requires Ed25519 signatures for remote manifests and verifies trusted key IDs;
- rejects signing keys listed in `CONNECTOR_PACK_REVOKED_KEYS`;
- requires signed `spec_sha256` for URL specs and passes only the verified bytes
  to the importer;
- requires HTTPS for remote manifests, registry indexes, and signed/remote spec
  URLs;
- verifies signed registry indexes, enforces timezone-aware `issued_at` /
  `expires_at` freshness (30-day maximum lifetime), and surfaces registry-level
  revocation flags;
- enforces pack-level `requires` dependencies;
- requires generated modules to pass an AST shape check before they are written;
- graph-validates templates and strips credential/secret material;
- uses a PostgreSQL advisory transaction lock to prevent concurrent key
  collisions;
- stores generated sources in PostgreSQL for API/worker materialization;
- rolls back/restores files, registry entries, and pack-owned templates on
  failed upgrades; and
- blocks uninstall while an active workflow uses the connector, returning only
  the active-workflow count rather than cross-tenant names; and
- exposes install source URLs only to administrators.

**Current boundary:** signed manifests establish publisher-key integrity, and
signed-key/registry-entry revocation is enforced. There is still no
Flowsmith-hosted registry, moderation service, automatic revocation feed,
cryptographic provenance attestation beyond the signature/digest metadata,
Python dependency resolver, or public 50-pack catalog. Signing private keys must
be protected offline. See [`CONNECTOR_PACKS.md`](CONNECTOR_PACKS.md).
