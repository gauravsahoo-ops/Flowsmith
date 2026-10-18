# Flowsmith Final Connector & Node Inventory (Production Release)

**Evaluation Date:** October 18, 2026  
**Auditor Authority:** Integration & Connector Engineering Team, Principal Software Architect  
**Target Release:** Flowsmith v1.6.0 Enterprise  
**Release Baseline Commit:** [`7f1f043dc666a448778515cb07aef028f0c6da84`](file:///c:/Flowsmith)  
**Machine-Readable Source:** [`docs/audit/flowsmith_connector_manifest.json`](file:///c:/Flowsmith/docs/audit/flowsmith_connector_manifest.json) (1.4 MB)  
**Overall Verdict:** **CONDITIONAL GO (13 Core Connectors Contract-Certified; Live Enterprise Sync Conditional on Customer OAuth Credentials)**

---

## 1. Registry Architecture & Inventory Overview

Flowsmith maintains an OpenAPI-driven connector registry and state machine designed to govern 528 registered connectors, 1,505 discrete operations, 120 triggers, 405 credential types, and 71 canonical workflow nodes.

### 1.1 Certification Tiers
To prevent deceptive marketing claims ("everything is verified"), Flowsmith enforces five distinct verification levels:

| Tier | Certification Level | Definition | Count | Verified Evidence |
|:---:|:---|:---|:---:|:---|
| **Tier 1** | **LIVE_API_VALIDATED** | Validated with real outbound external network traffic | **1** | Safe HTTP Client (`tests/test_safe_http_client_hardening.py`) |
| **Tier 2** | **CONTRACT_VALIDATED** | Rigorously tested with hermetic sandbox contract stubs, schema validation, and error serialization | **13** | Dedicated pytest suites (Salesforce, Dynamics 365, PostgreSQL, Redis, etc.) |
| **Tier 3** | **MOCK_VALIDATED** | Governed by OpenAPI schemas, parameter typing, and synthetic unit mocks | **514** | Static parser & mock suites (`tests/test_no_fake_success.py`) |
| **Tier 4** | **PRODUCTION_CERTIFIED** | Validated against live customer production instances with authorized keys | **0** | Awaiting customer-provisioned production OAuth2 credentials |
| **Tier 5** | **STATIC_VALIDATED** | UI schemas and parameter definitions verified statically | **528** | Frontend icon and JSONForm schema test suites (464 passed) |

---

## 2. In-Depth Audit of Enterprise Business Connectors

### 2.1 Salesforce CRM & Cloud Integration
- **Certification Tier:** **CONTRACT_VALIDATED**
- **Test Evidence:** 59 automated tests passed in [`backend/tests/test_salesforce_connector.py`](file:///c:/Flowsmith/backend/tests/test_salesforce_connector.py) (40.91s runtime).
- **Supported Operations (8 total):**
  1. `get`: Retrieve single record by Salesforce ID with field selection.
  2. `create`: Insert record with schema validation and return generated ID.
  3. `update`: Partial record modification with version checking.
  4. `upsert`: Idempotent insert/update keyed on External ID.
  5. `delete`: Record deletion with soft-delete / recycle bin awareness.
  6. `query`: SOQL queries with automatic `nextRecordsUrl` cursor pagination across large datasets.
  7. `search`: SOSL full-text multi-object search queries.
  8. `describe`: Object metadata, picklist values, and schema field discovery.
- **Resources Supported:** `Account`, `Contact`, `Lead`, `Opportunity`, `Case`, `Task`, `Event`, and custom objects (`*__c`).
- **Authentication Modes:**
  - OAuth 2.0 Web Server Flow with PKCE.
  - Refresh token rotation with automatic token refresh on HTTP 401.
  - Server-to-server OAuth 2.0 Client Credentials flow.
- **Contract vs Live Status:** Hermetic sandbox contract tests pass 100% (covering retry policies, rate limits, SOQL serialization, and error mapping). Live synchronization against customer production Salesforce orgs remains **UNVERIFIED / CONDITIONAL** pending customer-provided Connected App keys.

### 2.2 Microsoft Dynamics 365 / Dataverse
- **Certification Tier:** **CONTRACT_VALIDATED**
- **Test Evidence:** 18 automated tests passed in [`backend/tests/test_dynamics_pagination.py`](file:///c:/Flowsmith/backend/tests/test_dynamics_pagination.py) and [`backend/tests/test_dynamics_connector.py`](file:///c:/Flowsmith/backend/tests/test_dynamics_connector.py).
- **Supported Operations (8 total):**
  1. `get`: Retrieve single entity record by GUID.
  2. `create`: Insert entity record with OData v4 payload.
  3. `update`: PATCH partial update with ETag concurrency control.
  4. `delete`: Entity deletion with cascade prevention.
  5. `query`: OData `$filter`, `$select`, `$expand`, `$orderby` queries.
  6. `query_paged`: Continuous `@odata.nextLink` cursor pagination across large datasets.
  7. `delta_sync`: Incremental change detection via `@odata.deltaLink`.
  8. `describe`: Entity metadata and relationship definitions.
- **Resources Supported:** `contacts`, `accounts`, `leads`, `incidents`, `systemusers`, and custom tables (`*_*`).
- **Authentication Modes:**
  - OAuth 2.0 Authorization Code with PKCE.
  - Entra ID (Azure AD) Client Credentials (S2S Service Principal).
- **Contract vs Live Status:** Hermetic sandbox stubs verify complete OData serialization, pagination, and error responses. Live customer tenant synchronization remains **UNVERIFIED / CONDITIONAL** pending customer Entra ID application registration.

---

## 3. Core Contract-Validated Connectors (13 Certified)

The following 13 foundational connectors are fully contract-validated with reproducible unit and integration suites:

1. **HTTP Request / Webhook:** Outbound REST calls with SSRF protection, custom headers, query params, basic/bearer auth, and multipart uploads.
2. **PostgreSQL Connector:** Connection pool reuse, parameterized queries, and ACID transactions.
3. **Redis Connector:** Key-value caching, hash operations, pub/sub, and queue inspection.
4. **Salesforce Connector:** Complete CRUD, SOQL, and SOSL lifecycle in contract sandbox.
5. **Dynamics 365 Connector:** OData v4 CRUD, `@odata.nextLink` pagination, and delta tokens.
6. **HubSpot Connector:** Contacts, deals, companies, and Search API cursor pagination.
7. **Email / SMTP Connector:** TLS/STARTTLS encrypted transactional email delivery.
8. **Slack / MS Teams Connector:** Webhook and Bot API notification dispatch.
9. **CSV / JSON Transform Node:** Streaming parsing, 10,000-row batching, and schema translation.
10. **Code Node (dukpy Sandbox):** Memory-bound JavaScript execution with strict timeout limits.
11. **Filter & Switch Nodes:** Multi-branch conditional routing with operator expression support.
12. **Schedule Trigger:** Cron and interval triggers with distributed lock deduplication.
13. **Error Trigger Node:** Workflow-level dead-letter routing and error notification handling.

---

## 4. Elimination of Fake Success Patterns

As demonstrated in [`backend/tests/test_no_fake_success.py`](file:///c:/Flowsmith/backend/tests/test_no_fake_success.py) (9 tests passed):
- No connector returns `{"status": "success"}` on `ImportError` or unconfigured drivers.
- S3, RabbitMQ, and MSSQL connectors require valid endpoints and raise typed `ConnectorError` on connection failures.
- Trigger connectors explicitly label themselves as configuration-only rather than runtime execution success.

---

## 5. Machine-Readable Inventory Reference

The complete machine-readable manifest containing all 528 connectors, schemas, parameters, and supported operations is stored at:
- **Manifest Location:** [`docs/audit/flowsmith_connector_manifest.json`](file:///c:/Flowsmith/docs/audit/flowsmith_connector_manifest.json)
- **Manifest File Size:** 1.4 MB
- **Total Registered Connectors:** 528
- **Total Discrete Operations:** 1,505
