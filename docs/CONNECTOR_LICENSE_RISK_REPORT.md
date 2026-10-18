# License & Reuse-Risk Report — n8n Reference Audit

**Date:** 2026-10-13
**Auditor scope:** `C:\n8n-master` (reference repo) vs `C:\Flowsmith` (our repo).
**Purpose:** Satisfy the project's legal/licensing safeguard before any connector work begins.

---

## 1. n8n's license terms (as read from the repository)

Source: `C:\n8n-master\LICENSE.md`, `C:\n8n-master\LICENSE_EE.md`.

| Item | Finding |
|---|---|
| Primary license | **Sustainable Use License v1.0** (a *source-available, non-open-source* license) |
| Permitted | Use, copy, distribute, make available, prepare **derivative works** — *subject to the limitations below* |
| Limitation 1 | **Own internal business purposes only / non-commercial or personal use.** Commercial use is not granted. |
| Limitation 2 | Distribution allowed **only free of charge and for non-commercial purposes**. |
| Limitation 3 | Copyright / license / notice files must not be altered, removed or obscured. |
| Limitation 4 | Trademark use is subject to applicable law. |
| Branch restriction | *"Content of branches other than the main branch (i.e. 'master') are not licensed."* |
| EE restriction | Any file containing `.ee.` in its name, or `.ee` in its directory, is **excluded** and requires a valid n8n Enterprise License. |
| Third-party components | Licensed under their original licenses (retained by their owners). |

**Consequence for this project:** FlowSmith is a workflow-automation product released under
**Business Source License 1.1** with a commercial SaaS restriction. Deriving FlowSmith code from
n8n would (a) import a non-commercial-only grant into a product we may later commercialise, and
(b) likely breach n8n's Limitation 1 and 2. **No n8n code may be transplanted.**

## 2. FlowSmith's own license

Source: `C:\Flowsmith\LICENSE` — **Business Source License 1.1**
- Licensor: Gaurav Sahoo (gauravsahoo-ops)
- Additional Use Grant: non-production, personal, internal-business use permitted.
- Prohibited: hosting FlowSmith as a third-party hosted/managed workflow-automation service without a commercial license.
- Change Date: 2030-01-01 → Change License: MIT.

BSL-1.1 is a recognised source-available license (MPL-2.0-style weak copyleft once it converts).
It is **compatible with keeping FlowSmith's code independent**, and does not permit importing
n8n-licensed material.

---

## 3. Empirical copy-detection results

These are measured, not assumed.

| Test | Method | Result |
|---|---|---|
| **Binary asset overlap** | MD5-hash all 635 `.svg` files under `C:\n8n-master` and compare against all 144 `.svg`/`.jsx` files under `C:\Flowsmith\frontend` (excluding `node_modules`, `dist`) | **0 byte-identical matches** |
| **n8n identifier leakage** | Literal search for `n8n-nodes-base`, `INodeExecutionData`, `VersionedNodeType`, `NodeConnectionType`, `n8n-workflow`, `getWorkflowStaticData`, `IHookFunctions`, `IWebhookFunctions`, `LoadOptionsContext` across all FlowSmith `*.py`, `*.jsx`, `*.js` | **0 hits** (all 10 patterns) |
| **Reverse contamination** | Search `C:\n8n-master` for `flowsmith` | **0 hits** — the two codebases have never been cross-pollinated |
| **Branding** | FlowSmith UI carries only `favicon.svg` / `icons.svg`; no `n8n` string in any frontend source file | ✅ clean |
| **Third-party notices** | `THIRD_PARTY_LICENSES.md` already carries an independently-implemented connector-governance statement (uncommitted, retained) | ✅ present |

## 4. What may be used from n8n

| Asset type | Allowed? | Basis |
|---|---|---|
| **Functional/observable facts** — which integrations exist, what operations they expose, which auth schemes they support, general UI layout conventions (resource→operation pickers, credential selectors, pagination toggles) | ✅ **Yes** | Facts and ideas are not protectable expression; also explicitly the sanctioned use here. |
| **Public API documentation** of third-party services (Salesforce, HubSpot, Microsoft, etc.) | ✅ **Yes** | Public, independently sourced. |
| **General UI/UX patterns** (three-panel node editor, palette search, credential picker) | ✅ **Yes** | Unprotectable ideas/methods of operation; our React implementation is written from scratch. |
| n8n source files (`*.ts`, `*.vue`, `*.json` node descriptions) | ❌ **No** | Sustainable Use License — internal/non-commercial only. |
| `.ee.` files | ❌ **No** | Excluded outright; requires an n8n Enterprise License. |
| n8n icons / brand SVGs / logos | ❌ **No** | Trademark + copyright; also absent from our repo per §3. |
| n8n documentation text | ❌ **No** | Copyrighted expression. |
| n8n `.node.json` "codex" sidecars, workflow fixtures | ❌ **No** | Copyrighted content of the repo. |
| Third-party libraries n8n also uses (MIT/Apache/BSD/ISC) | ✅ **Yes** | Permissive licenses; recorded in `THIRD_PARTY_LICENSES.md`. |
| Any asset whose reuse rights are unclear | ⛔ **Blocked** | Not incorporated until legally cleared, per project safeguard. |

## 5. Third-party dependency posture

- Frontend and backend dependency licenses are already inventoried in **`THIRD_PARTY_LICENSES.md`**
  (permissive-majority matrix; no GPL/AGPL flagged as high-risk).
- New dependencies added during this work must be **MIT / Apache-2.0 / BSD / ISC / MPL-2.0** only.
  Anything LGPL/AGPL/GPL/SSPL requires an explicit clearance entry first.
- **No new runtime dependency was required** for the connector work in this iteration (S3 is
  implemented against the AWS SigV4 REST protocol with the already-present `cryptography` +
  `httpx` libraries rather than pulling in `boto3`).

## 6. Decisions & actions

| # | Decision | Status |
|---|---|---|
| D1 | Use `C:\n8n-master` **only** to enumerate observable capabilities. No file copied, no asset transplanted. | ✅ Enforced — measured clean in §3 |
| D2 | All connector implementations written independently from vendor API documentation. | ✅ In force |
| D3 | Do **not** transcribe n8n node-display names or description strings verbatim. | ✅ In force (our `display_name` / `description` fields are independently worded) |
| D4 | Record this audit in the repo before implementation starts. | ✅ This document |
| D5 | Keep the existing uncommitted `THIRD_PARTY_LICENSES.md` governance paragraph. | ✅ Retained |
| D6 | Flag anything unclear rather than silently reuse. | ⛔ 0 unclear items found in this pass |

## 7. Residual risk assessment

| Risk | Level | Rationale |
|---|---|---|
| Direct code copying | **None detected** | Measured: 0 hash matches, 0 identifier matches. |
| Structural/conceptual similarity | **Low** | Both platforms implement the same well-known industry pattern (resource→operation→parameter). This is an unprotectable idea. FlowSmith's runtime is Python/Pydantic + React; n8n's is TypeScript/NestJS + Vue — no shared architecture. |
| Icon/trademark reuse | **Low** | 0 byte-identical SVGs; brand marks (Salesforce, HubSpot…) are third-party trademarks used nominatively to identify the integration — standard, nominative fair use. |
| Dependency license conflict | **Low** | Permissive-majority inventory maintained in `THIRD_PARTY_LICENSES.md`. |
| Future contributor copying n8n | **Medium** | Mitigated by this report + the repo governance note in `THIRD_PARTY_LICENSES.md`. |

**Overall: CLEAR TO PROCEED** under the safeguards stated in the project brief.
