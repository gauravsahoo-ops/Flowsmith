# Security & Access

This document covers the security and access-control features of the
platform, how to configure them, and the operational caveats.

## Authentication

- Passwords are hashed with PBKDF2-HMAC-SHA256 (per-account random salt)
  and JWTs are signed with `jwt_secret` (`HS256`).
- The **first registered account becomes an `admin`**; every later
  account is a `member`.
- Deactivated accounts cannot log in, and their existing tokens are
  rejected (`get_current_user` checks `active` on every request).

## Login throttling

Failed logins are throttled **per email and per source IP**:

| Setting                  | Default | Meaning                          |
| ------------------------ | ------- | -------------------------------- |
| `login_max_attempts`     | 5       | failures before lockout          |
| `login_window_seconds`   | 300     | window in which failures count   |
| `login_lockout_seconds`  | 300     | how long the key stays locked    |

A locked login returns `429` with a `Retry-After` header. Successful
logins clear the failure counters.

## Webhook rate limiting

Public webhook endpoints are rate limited **per webhook path**:

| Setting                 | Default | Meaning                    |
| ----------------------- | ------- | -------------------------- |
| `webhook_rate_limit`    | 60      | requests per window        |
| `webhook_rate_period_s` | 60      | sliding window in seconds  |

Hits over the limit return `429` with `Retry-After`. Unknown paths and
wrong methods are rejected **before** the limiter, so they do not
consume budget.

## Roles & user administration

Admins manage users via `GET/PATCH /api/users` (list, change `role` or
`active`). Guards:

- Non-admins get `403` on the admin endpoints.
- An admin cannot demote or deactivate their **own** account.
- The **last active admin** can never be demoted or deactivated.

## Workflow sharing & access control

Workflow permissions (enforced on every workflow/execution endpoint):

| Permission        | Capabilities                                        |
| ----------------- | --------------------------------------------------- |
| `owner`           | everything: edit, run, activate, delete, share       |
| `edit` share      | view, edit, activate, run — no delete, no sharing   |
| `view` share      | view, read executions — no edits, no runs           |
| none              | `404` on every endpoint (existence is hidden)       |

Share management endpoints (owner only):

- `GET/POST /api/workflows/{id}/shares` — list / share by email
- `PATCH /api/workflows/{id}/shares/{userId}` — change permission
- `DELETE /api/workflows/{id}/shares/{userId}` — unshare

Shares cascade-delete with the workflow. Execution lists and details are
visible to anyone who can view the workflow; retry/cancel require edit
permission.

## Audit log

Security-relevant actions are appended to `audit_events`:
register/login (including failed logins), workflow create/update/
delete/activate/deactivate, shares, credentials, role/state changes and
execution runs. Admins browse the log at `GET /api/audit` with `action`
and `user_id` filters and pagination.

## Credential encryption & key rotation

Credential payloads are encrypted at rest with Fernet (AES-128-CBC)
using `CREDENTIALS_ENCRYPTION_KEY`. When the variable is unset a dev
key is derived from `jwt_secret` (stable across restarts, **dev only** -
production must set the variable and back it up; losing the key means
losing all credentials).

Rotation supports a **comma-separated keyring**: the first key encrypts
new data, and every stored token carries a `k{idx}:` prefix so old
values remain decryptable while keys are rolled.

## Workspace environment variables

Environment variables (`/api/environments`) are encrypted at rest with
the same keyring and follow the same rules as credentials:

- Only workspace/org members can list a workspace's variables; writes
  are restricted to the workspace creator (tenant isolation, spec 28.1).
- Secret values are masked in API responses (last-4 characters only).
- Decryption happens once per job, inside the worker, where the values
  surface to expressions as `{{ $env.KEY }}`. They are never logged,
  never traced, and never appear in execution records.

To rotate:

1. Prepend the **new** key: `CREDENTIALS_ENCRYPTION_KEY="<new>,<old>"`.
2. Re-encrypt stored credentials with the new key:

   ```bash
   python -m app.scripts.rotate_credentials
   ```

3. Remove the **old** key from the variable.

## Operational caveats

- Rate limiters and failure throttles are **in-memory** (single worker).
  Multi-worker deployments must back them with a shared store (Redis,
  etc.) or the limits apply per process.
- The throttles reset when the process restarts.
- Webhook rate limiting is keyed per path only (not per IP); put the
  service behind a reverse proxy for IP-level protection and TLS.
