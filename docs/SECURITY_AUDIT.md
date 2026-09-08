# Security Audit — Phases 23/38

> **Scope:** full-stack review (authentication, authorization, RBAC,
> tenant isolation, credentials, OAuth, API, webhooks, SSRF, XSS, SQL/
> command/code injection, file handling, AI prompt injection, tool
> abuse, secret leakage, audit logs) plus an **automated evidence
> suite** (`backend/tests/test_api/test_security_audit.py`) that fails
> loudly on regression. Status: **12 audit tests + 13 prior security
> tests green; 3 findings fixed; 0 known critical/high open.**

## Findings & fixes

| # | Severity | Finding | Fix | Evidence |
|---|---|---|---|---|
| F1 | **High** | `utils/backup.py:restore_backup` built `gunzip -c "{filepath}" \| psql …` with `shell=True` and an interpolated path — command injection if a crafted filename ever reached it | Removed shell entirely: gzip decompressed in Python streaming into psql stdin (`shell=False`, argv list). Regression test asserts argv-list + no shell even for hostile filenames | `test_restore_backup_never_spawns_a_shell` |
| F2 | **Medium** | Webhook / Salesforce-trigger paths are the ONLY authentication for unauthenticated endpoints, but were user-chosen with no entropy floor ("my-hook" was acceptable) — enumerable trigger URLs. Also: the validation ran **only on workflow update**, so weak/duplicate paths slipped in at create time | `_validate_webhook_paths` now enforces `^[A-Za-z0-9/_.\-]{24,}$` (~2^120 search space) for webhook AND salesforce_trigger nodes, and is called on **create**, update and activation | `test_weak_webhook_paths_rejected_at_save_time`, `test_strong_webhook_path_is_accepted_and_gated` |
| F3 | **Medium** | `GET /api/metrics` was anonymous — per-route traffic volumes aid recon | Endpoint now requires a bearer token (service-user scraping); monitoring docs updated | `test_metrics_endpoint_requires_auth` |
| F4 | **Low** | `/docs`, `/redoc`, `/openapi.json` exposed unconditionally — leaks the complete route surface | New `API_DOCS_ENABLED` setting (default off); endpoints only registered when enabled | `test_api_docs_disabled_by_default` |

## Verified secure (with automated evidence)

| Area | Property | Evidence |
|---|---|---|
| Authentication sweep | Every non-allowlisted `/api` route rejects anonymous access with 401/403 (never 200/500); >80 probes generated from the live route table each run | `test_anonymous_requests_are_rejected_everywhere` |
| Token forgery | Garbage/truncated/tampered JWTs rejected | `test_invalid_and_forged_tokens_are_rejected` |
| Password storage | PBKDF2-SHA256, 600k iterations, per-user salt, constant-time compare (`app/security/jwt.py`) | code review + existing auth suite |
| Authorization | Cross-user GET/PUT/DELETE on workflows, executions, credentials, RAG collections → **404** (existence hidden, not 403-leaked) | `test_cross_user_resource_probes_return_404` |
| RBAC | First user = admin; admin-gated endpoints use `get_current_admin`; last-admin protection | pre-existing `tests/test_api/test_security.py` |
| Credentials at rest | Fernet encryption, key-rotation prefixes; DB blob contains no plaintext; API returns metadata only — plaintext never echoed | `test_credentials_are_encrypted_at_rest`, `test_credential_values_never_appear_in_list_responses`, crypto rotation suite |
| OAuth | Server-side `state` bound to user (`oauth_states`), PKCE verifier stored, replay-purged | code review `app/oauth_providers.py`, `api/oauth.py` |
| Stripe webhook | v1 signature verification (Phase 34) rejects unsigned/forged payloads | billing suite |
| SSRF | SafeHTTPClient: private/link-local/metadata hosts blocked, redirects re-validated, scheme allowlist | pre-existing hardening suites (`test_safe_http_client*.py`) |
| SQL injection | ORM-bound parameters throughout; the two raw-SQL spots (Salesforce SOQL/URL) are regex-gated (`[A-Za-z_][A-Za-z0-9_]*`) before interpolation | grep audit + connector contract tests |
| Command injection | No `os.system`; single `subprocess` site was F1 (fixed); expression engine has no exec surface | `test_restore_backup_never_spawns_a_shell`, expressions battery |
| Code execution via expressions | Sandbox: no eval/exec/import, dunder refusal, depth caps | pre-existing 20-test battery (`test_expressions_security.py`) + spot checks |
| Prompt injection | Generated workflows cannot execute anything by themselves — they must pass the Phase-15 validator against real registries before preview; assistant outputs validated against schemas | Phase 15/16 suites |
| Tool abuse | MCP tools respect RBAC + tenant scope; agent tool-calls bounded by node timeout/iterations | MCP suites |
| Secret leakage in logs/metrics | Request logger records method/template-path/status only; SafeHTTPClient redacts auth headers; metrics labels are route templates (bounded cardinality), secret webhook paths never appear | `test_request_log_line_emitted`, middleware review |
| Audit trail | Register/login(+failed)/workflow CUD/share/admin-prune/AI actions recorded; audit list endpoint admin-only | pre-existing security suite |
| WebSocket | JWT required (4401 close), execution readable by owner only (4404) | `ws.py` review + token-decode test |

## Residual risks (accepted, documented)

1. **Webhook path brute force** — theoretical; 24+ char namespace makes
   enumeration impractical. Optional next step: per-path rate limits
   already exist (`webhook_rate_limit`).
2. **CORS** `allow_methods=["*"]` with explicit origins + credentials —
   acceptable; tighten headers if third-party embeds appear.
3. **Dev key derivation** — missing `CREDENTIALS_ENCRYPTION_KEY`
   derives from jwt_secret in dev; production startup refuses without
   it (`validate_production_settings`).

## How to re-run the audit

```bash
cd backend
pytest tests/test_api/test_security_audit.py tests/test_api/test_security.py \
       tests/test_expressions_security.py tests/test_safe_http_client.py \
       tests/test_safe_http_client_hardening.py -q
```
