# Flowsmith Enterprise Roadmap & Future Horizons

**Platform Version:** 1.0.0 Enterprise  
**Target Horizon:** 2026 – 2027  
**Guiding Vision:** Unrivaled Enterprise Self-Hosted Automation, Absolute Data Sovereignty, Next-Gen Autonomous AI Orchestration

---

## 1. Roadmap Horizon Overview

Following the completion of Phases 0-45 (including the Complete Multi-Tier Cognitive Memory System, Autonomous Zero-LLM Local Engine, Enterprise AI Builder, and 76 native + 17 generated connectors), this roadmap outlines key engineering initiatives scheduled for upcoming releases. Catalog-only reference entries are tracked separately in [`CONNECTOR_STATUS.md`](CONNECTOR_STATUS.md).

```
┌────────────────────────────────────────────────────────┐
│             Flowsmith Enterprise Roadmap               │
├────────────────────────────────────────────────────────┤
│ Q4 2026: Multi-Region High-Availability & OpenTelemetry│
│ Q1 2027: Enterprise Auth Hardening                     │
│ Q2 2027: Multiplayer Canvas & Visual Co-Authoring      │
│ Q3 2027: Community & Private Connector Plugin Store   │
│ Q4 2027: Air-Gapped Appliance & Hardware ISO Edition   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Strategic Initiatives

### Initiative A: Multi-Region High-Availability & Geo-Clustering (Q4 2026)
- **Objective**: Provide sub-second cross-region failover and active-active workflow execution for multinational enterprises.
- **Key Deliverables**:
  - PostgreSQL multi-region replication topology with automated split-brain prevention.
  - Geo-distributed Redis broker mesh for low-latency webhook ingestion across US, EU, and APAC.
  - Geo-DNS routing directing external webhooks to the nearest edge gateway.

### Initiative B: Enterprise Auth Hardening (Q1 2027)
- **Objective**: Complete zero-touch user and group lifecycle management for Fortune 500 IT departments.
- **Delivered 2026-10-23:**
  - SCIM 2.0 user provisioning at `/scim/v2/Users` with filtering, create/read/replace/patch/deactivate, optional default organization/workspace assignment, and a dedicated bearer token. See [`SCIM.md`](SCIM.md).
  - SCIM 2.0 Groups at `/scim/v2/Groups`, mapped to private workspaces with synchronized membership, nested child groups, optional organization-role mapping, and safe soft deletion.
  - Native SAML 2.0 Web SSO with IdP metadata ingestion, XMLDSig assertion/response validation, encrypted assertions, SP request signing, audience/recipient/time checks, replay protection, JIT user provisioning, Single Logout, and group-claim-to-role mapping. See [`SAML.md`](SAML.md).
  - TOTP multi-factor authentication with encrypted secrets, replay-resistant codes, single-use recovery codes, and a login challenge flow. See [`MFA.md`](MFA.md).
  - Organization-wide MFA policy with forced in-login enrollment for password and LDAP users.
  - LDAP/Active Directory authentication with username login, service-account search, user bind, JIT provisioning, group-to-role mapping, group-to-workspace memberships, group-to-organization memberships, and optional background refresh. See [`LDAP.md`](LDAP.md).
  - WebAuthn/passkey registration and login with RP-ID/origin validation, single-use challenges, and TOTP fallback. See [`WEBAUTHN.md`](WEBAUTHN.md).
- **Remaining**:
  - Just-In-Time workspace assignment based on IdP SAML attributes and group membership.

### Initiative C: OpenTelemetry (OTel) Distributed Tracing (Q4 2026)
- **Objective**: Full end-to-end observability across the entire execution lifecycle.
- **Key Deliverables**:
  - OpenTelemetry context propagation across API gateways, Redis task queues, execution worker threads, and external HTTP connector requests.
  - One-click OTel export to Datadog, Dynatrace, Honeycomb, New Relic, and Grafana Tempo.
  - Per-step latency, memory consumption, and network I/O flame graphs rendered directly inside the trace console.

### Initiative D: Real-Time Multiplayer Visual Canvas (Q2 2027)
- **Objective**: Collaborative workflow building for cross-functional teams.
- **Key Deliverables**:
  - WebSocket-powered multiplayer cursor presence and live node selection highlights (Figma-style collaboration).
  - Fine-grained optimistic conflict resolution and node-level editing locks.
  - Canvas comment threads attached to specific nodes or branches with team @mentions.

### Initiative E: Signed Connector Plugin Marketplace (Q3 2027)
- **Objective**: Allow internal enterprise developer teams and community authors to build, package, and distribute custom connectors.
- **Delivered 2026-10-24:** Admin-only connector-pack installer with OpenAPI spec + template manifests, SSRF-safe URL fetching, AST-validated generated code, graph-validated/sanitized templates, PostgreSQL-backed generated sources for API/worker materialization, a local install UI, Ed25519 remote-manifest signing with trusted/revoked keys, signed URL-spec digests, signed registry-index discovery, pack-level dependencies, upgrade/uninstall, rollback handling, and a 10-second cross-process reconciler for install/upgrade/uninstall propagation. See [`CONNECTOR_PACKS.md`](CONNECTOR_PACKS.md).
- **Key Deliverables remaining**:
  - `flowsmith-cli` scaffolding/publishing workflow.
  - A Flowsmith-hosted registry service, moderation console, automatic revocation feed, and at least 50 externally authored packs.
  - Cryptographic provenance attestations beyond signature/digest metadata.
  - Python package dependency resolution.

### Initiative F: Turnkey Air-Gapped Appliance Edition (Q4 2027)
- **Objective**: Deliver a zero-dependency, single-boot image for defense, intelligence, and highly regulated healthcare environments.
- **Key Deliverables**:
  - Pre-packaged OVA / AMI / ISO containing hardened Linux, PostgreSQL, Redis, Flowsmith engine, and pre-warmed Ollama LLM models.
  - Zero external internet access requirements.
  - Automated STIG compliance hardening and automated CIS benchmark verification.
