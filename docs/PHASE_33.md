# Phase 33 — Generic OAuth2 Provider Framework + HubSpot Connector

Salesforce was the reference connector; this phase proves the platform's
OAuth + connector architecture generalizes by extracting it and shipping
a second first-party business connector on top.

## Generic OAuth2 provider framework (`app/oauth_providers.py`)

One flow, N providers. The security-critical machinery is implemented
once and shared:

- server-side client id/secret/redirect (never exposed to the frontend),
- single-use TTL-bound `state` bound to the authenticated user,
- PKCE for providers that support it,
- refresh tokens stored only inside Fernet-encrypted credentials,
- reconnect semantics (one active OAuth credential per user+provider),
- audit events and frontend redirect markers per provider.

A provider registers an `OAuthProviderSpec` describing only what differs:
authorize/token URLs, request shapes, identity lookup (friendly display
label), the stored credential blob, and its audit/marker names.
Registered today: **salesforce** (unchanged behaviour, legacy paths kept)
and **hubspot** (`POST /api/auth/hubspot/connect`,
`GET /api/auth/hubspot/callback`).

Server config: `HUBSPOT_CLIENT_ID`, `HUBSPOT_CLIENT_SECRET`,
`HUBSPOT_REDIRECT_URI` (defaults to `{PUBLIC_URL}/api/auth/hubspot/callback`),
`HUBSPOT_SCOPES`.

## HubSpot connector

- **Provider client** (`app/providers/hubspot.py`): CRM v3 access with
  OAuth refresh-on-demand (access tokens are minted from the encrypted
  refresh token and cached in memory only) or a private-app token.
  Error taxonomy mapped like Salesforce (401 AUTH_FAILED after refresh,
  404 NOT_FOUND, 429 RATE_LIMITED retryable, 5xx UNAVAILABLE retryable);
  standard-object allowlist blocks path traversal via `object_type`.
- **Connector + definition**: node type `hubspot` with operations
  search / get / create / update over contacts, companies, deals,
  tickets, products, quotes — idempotency declared per operation
  (create is non-idempotent), surfaced in discovery exactly like
  Salesforce.
- **Credential type** `hubspot`: OAuth mode (encrypted refresh_token) or
  private-app token; secrets redacted everywhere.

## Frontend

- Credentials panel: "Connect HubSpot" button (same popup flow as
  Salesforce), reconnect per connection, generalized popup-message
  handling (`oauth` source alongside the legacy Salesforce one).

## Tests (13 new)

- OAuth flow (7): authorize URL shape/state storage, server-config 422s,
  code exchange at `/oauth/v1/token` with server secret, encrypted
  credential creation (refresh token never in plaintext), state replay
  rejection, provider-error redirect, unknown provider 404.
- Provider/connector/full-stack (6): search with on-the-fly refresh,
  private-token mode (no token call), error taxonomy incl. retryability,
  object-type traversal rejection, full workflow run through queue/engine
  with expression-resolved properties + secret-leak check on the
  execution record, connector discovery lists hubspot.

## Evidence

Backend 705 passed / 0 failed · vitest 108/108 · lint/build clean ·
pyright 0 errors on new modules · Playwright E2E 6/6.

## Known limitations / follow-ups

- HubSpot operations cover the uniform CRM v3 object surface; custom
  objects and associations are future work.
- Token refresh happens in-process per worker; no distributed lock
  (harmless: refresh is idempotent, worst case two workers refresh).
- Salesforce identity lookup stays inside its spec; other providers can
  opt out (identity label is best-effort by contract).
