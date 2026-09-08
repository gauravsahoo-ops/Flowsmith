# Phase 39 — Google Sheets Connector

Completes the Google business loop: Sheets ↔ Calendar workflows
(e.g. spreadsheet rows → calendar events) using one OAuth app and per-
product credential types.

## Provider (`providers/google_sheets.py`)
- Shares the Google OAuth app via `config_prefix="google"` — same client
  id/secret as Calendar, separate scope set
  (`GOOGLE_SHEETS_SCOPES`, default `openid email …/auth/spreadsheets`).
- Refresh-on-demand with in-memory cache, one-shot 401 retry; error
  taxonomy identical to Calendar/Salesforce/HubSpot.
- Spreadsheet-id regex allowlist blocks path traversal.

## Connector & definition
- Node type `google_sheets`; operations:
  - `read`   — values from an A1 range → `{rows, count}`
  - `append` — append one row (`USER_ENTERED`, INSERT_ROWS)
  - `update` — overwrite a range with rows
- Idempotency: append is non-idempotent; read/update idempotent.
- Registered in discovery; `google_sheets` credential type
  (OAuth-only, refresh token encrypted at rest).

## Frontend
"Connect Google Sheets" box + reconnect actions (shared popup plumbing).

## Tests (5 new)
Provider unit (append w/ refresh ordering + USER_ENTERED param; read row
mapping), taxonomy incl. retryability + spreadsheet-id traversal
rejection, full-stack append through queue/engine with expression-
resolved cells + secret-leak check on the execution record, discovery
listing.

## Evidence
Backend dual-pass: fast **631 passed / 0 failed**, timing **122 passed /
0 failed** (first runs each had 1 documented contention flake that
vanished on rerun). pyright repo-wide **0 errors** · vitest 111 ·
lint/build clean.

## Known limitations / follow-ups
- Values API only (no formatting/sheet management).
- Live-Google acceptance still pending real credentials (same state as
  Calendar; wire contract covered by scripts).
