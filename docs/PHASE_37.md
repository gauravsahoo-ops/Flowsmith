# Phase 37 — Google Calendar Connector (Third First-Party Integration)

The generic OAuth provider framework earns its keep a third time.

## OAuth (`google_calendar` provider)

- Authorize: `accounts.google.com/o/oauth2/v2/auth` with forced
  `access_type=offline` + `prompt=consent` so a refresh token is minted
  on **every** connect (Google otherwise issues one only on first
  consent).
- Token exchange + refresh: `oauth2.googleapis.com/token`
  (form-encoded; Content-Type explicit — see the Phase 36 Salesforce
  fix).
- Identity label decoded locally from `id_token` (no extra network
  call, no signature check needed inside the TLS exchange path).
- Server config: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_REDIRECT_URI` (derives from `PUBLIC_URL` when unset),
  `GOOGLE_SCOPES` (default `openid email …/auth/calendar.events`).

Framework improvement extracted while adding it: provider specs now take
an optional `config_prefix` (defaults to the key) so setting names don't
have to match long provider keys.

## Connector

- Provider client (`providers/google_calendar.py`): Calendar v3 events —
  list (time window), get, create, update, delete. Refresh-on-demand
  with in-memory cache and one-shot 401 retry; Salesforce-style error
  taxonomy (401 after retry → AUTH_FAILED, 404 NOT_FOUND,
  429 RATE_LIMITED retryable, 5xx UNAVAILABLE retryable); calendar-id
  regex allowlist blocks path traversal.
- Connector + definition: node type `google_calendar`; per-operation
  idempotency (create non-idempotent); registered in discovery.

## Credential type

`google_calendar`: `{user, refresh_token(secret), oauth}` — OAuth-only;
validator refuses empty refresh tokens.

## Frontend

Credentials panel: "Connect Google Calendar" box + reconnect action on
existing connections (same popup/message plumbing as SF/HubSpot).

## Tests (10 new)

OAuth flow (4): authorize URL shape incl. offline/consent params,
encrypted credential storage with id_token-derived label, reconnect
replacement, unknown-provider 404.
Provider/full-stack (6): create with refresh-then-post ordering,
refresh-on-401 recovery (two token hits, new bearer on retry), error
taxonomy incl. retryability, calendar-id traversal rejection, full
workflow run through queue/engine with expression-resolved event +
secret-leak check, discovery lists google_calendar.

## Evidence

Backend **738 tests**: full suite 720 passed under concurrent human
dev-stack load (18 documented timing flakes — identical set passed
18/18 in 21 s immediately after, matching the Phase 36 contention
class). pyright repo-wide **0 errors** · vitest 108/108 · lint/build
clean. Playwright E2E not run this phase (:8000 occupied by the dev
server).

## Known limitations / follow-ups

- Events only (no calendar-list management, no attendees write helpers).
- Live-org acceptance pending real Google credentials (mirrors
  Salesforce's pre-live state; the scripted suite covers the wire
  contract).
