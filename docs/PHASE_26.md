# Phase 26 — Security Hardening: Salesforce Implementation Review

> **Milestone:** the Salesforce credential → connector → HTTP stack was
> audited end to end, three real security defects were found and fixed
> in SafeHTTPClient (wire-redaction of Authorization headers, SSRF
> redirect bypass, `localhost`/literal-IP SSRF gaps), a response-size
> cap was added, and the whole guarantee set is now locked down by 14
> new security tests (8 unit-level on the real client, 6 full-stack
> secret-leakage/isolation).
> **Status:** done — affected suites 138 passed, no regressions; pyright
> clean on changed app code.

## 1. Defects found & fixed (all in `app/security/safe_http_client.py`)

1. **Authorization headers were redacted ON THE WIRE** (critical). The
   redacted header dict (`Authorization: ***REDACTED***`) was what the
   client actually sent, so Salesforce OAuth tokens (and HTTP-connector
   API keys) never reached the target in production. The suite never
   caught it because every Salesforce test scripts a fake client. Fix:
   real headers go on the wire verbatim; redaction now applies only to
   what is logged — the client logs `outbound METHOD scheme://host/path
   headers={redacted}` at DEBUG, and `_redact_sensitive_headers` remains
   the redaction helper.
2. **SSRF bypass via redirects** (high). `follow_redirects=True` re-issued
   requests without revalidation, so an allowed host could redirect to
   `169.254.169.254`/localhost. Fix: an httpx `event_hooks["request"]`
   hook validates **every** outbound request before it is sent —
   including redirect targets — blocking non-http(s) schemes,
   non-standard ports (policy: 80/443, configurable via `allowed_ports`),
   and SSRF hosts.
3. **SSRF blocklist gaps**. `localhost` (hostname form) was not blocked;
   literal-IP edge forms (decimal `2130706433`, hex `0x7f000001`,
   IPv4-mapped `::ffff:127.0.0.1`, CGNAT `100.64.0.0/10`) slipped past
   the string regexes. Fix: `ipaddress`-based classification for literal
   IPs (loopback/private/link-local/multicast/unspecified/reserved +
   CGNAT), with the string patterns kept for hostnames. DNS-rebinding
   (hostname → internal IP after validation) remains an accepted risk —
   the client validates names, not resolutions.
4. **No response-size control** (medium). Responses were buffered
   unbounded. Fix: default cap `max_response_bytes=10 MB` (configurable
   per client and per call), enforced on the streaming read path with a
   fail-fast `CONNECTOR_UNAVAILABLE` error (`retryable=False`).

## 2. Verified (existing guarantees, now test-locked)

- **Encryption at rest:** credential `data` is a Fernet-ciphertext blob
  (`app/security/crypto.py`, key rotation `k{idx}:` prefixes). Caveat:
  when `CREDENTIALS_ENCRYPTION_KEY` is unset the key derives from
  `jwt_secret` — fine in dev, **must** be set in production.
- **Never exposed to the frontend:** `GET /api/credentials` returns
  `{id, name, type}` only; there is **no** `GET /api/credentials/{id}`
  endpoint (405 on the DELETE-only route); create/delete return meta only.
- **Not stored in workflow JSON:** nodes carry `credentials: {type:
  id}`; secret values never enter `workflows.data`, version/trigger/
  execution snapshots, or queue payloads (DB-row sweeps).
- **Not stored in execution history:** detail/results/items/trace/error +
  every `executions.*` column are swept for secret markers.
- **Never logged:** no `logger.*` calls exist in the provider/connector/
  executor/SafeHTTPClient; the request middleware logs method/path/
  status only; the new debug log is redacted. Captured-log sweeps assert
  secret markers never appear in messages or exception info.
- **SafeHTTPClient everywhere:** token + data API calls both go through
  `get_safe_http_client()`; no direct httpx in the Salesforce path.
- **Timeouts:** 30 s per call (connect/read/write/pool), mapping to
  `CONNECTOR_TIMEOUT` (`retryable=True`).
- **Authorization:** credential resolution is owner-scoped at run time
  (`CREDENTIALS_REQUIRED` on foreign refs — the only leakage is the
  credential **id**, never name/values); cross-user saves are allowed
  but can never run; shared editors cannot resolve the owner's
  credentials.
- **Tenant/workspace isolation:** per-user ownership + explicit workflow
  shares is the enforcement model (the `workspace_id`/`organization_id`
  columns exist but are dormant — not consulted by `app/api/access.py`);
  the Salesforce token cache is keyed by `instance_url|username`
  (org-scoped, no cross-user data exposure).

## 3. Intentional, documented vector

`$cred` expressions (`{{ $cred.salesforce.client_secret }}`) expose the
**running user's own** decrypted credentials inside expressions — an
intentional feature (n8n-style). Since credential resolution is
owner-scoped, no cross-user exfiltration is possible; a non-owner's run
fails before any node executes. The owner deliberately writing their own
secrets into outputs/history is accepted product behavior.

## 4. Tests

- `backend/tests/test_safe_http_client_hardening.py` (8, real client +
  `httpx.MockTransport`): SSRF host blocklist incl. edge forms;
  scheme/port policy; redirect-to-blocked-host refused before the second
  request; redirects to allowed hosts still followed; Authorization sent
  verbatim on the wire while logs show only `***REDACTED***`; response
  cap enforced (fail-fast, `retryable=False`, per-call override); timeout
  → typed retryable `CONNECTOR_TIMEOUT`.
- `backend/tests/test_api/test_security_hardening.py` (6, full stack):
  credentials API surface (meta-only, 405 on GET /{id}, ciphertext at
  rest); workflow JSON (API + DB) holds ids only; execution history
  (responses + all stored columns) holds no secrets; failed runs never
  log secrets (captured records incl. exc_info); foreign save/run fails
  `CREDENTIALS_REQUIRED` with no leak; shared editor cannot resolve the
  owner's credentials.
- Regression: safe-http client + security + all Salesforce suites —
  **138 passed**; pyright clean on changed `app/` code.

## 5. Run

```powershell
cd backend
..\.venv\Scripts\python -m pytest tests/test_safe_http_client.py tests/test_safe_http_client_hardening.py tests/test_api/test_security_hardening.py -q
```