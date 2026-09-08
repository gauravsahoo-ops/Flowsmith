# Phase 6 — Credentials & secrets management (M6)

> **Milestone:** store, validate and inject credentials with secrets
> encrypted at rest, exposed only as metadata (spec 12, 29).
> **Status:** backend + frontend done, E2E verified (encrypted blob,
> `$cred` resolution in a real run, save-time validation).

## 1. What Phase 6 delivers

```text
frontend form -> POST /api/credentials  -> validate -> Fernet-encrypt -> store
                                              ^
                                              |            (decrypt only at run time)
workflow node "http" credential  -> executor -> $cred.http.api_key -> headers
```

- **Credential API** (`/api/credentials`, spec 9): `GET` (list),
  `GET /types` (catalog), `POST` (create → 201), `DELETE /{id}` (204).
  The API **never returns secret data** — only `{id, name, type}` — and
  the DB column stores a Fernet token, never plaintext.
- **Encryption** (`app/security/crypto.py`): AES-128-CBC via
  `cryptography`'s Fernet. Key comes from the `CREDENTIALS_ENCRYPTION_KEY`
  env var / `credentials_encryption_key` setting; in dev, a stable key is
  derived from `jwt_secret` with a warning (spec 12.2: production must
  set the env var).
- **Types** (`app/credentials/registry.py`): `http`, `smtp`, `database`,
  each with a Pydantic schema for server-side validation, the JSON schema
  for the UI form, and a `secret_fields` list so the UI renders password
  inputs.
- **Nodes declare what they accept** — `credential_types` on the node
  class (`http_request` → `["http"]`, `send_email` → `["smtp"]`,
  `database_query` → `["database"]`). The workflow payload carries
  `node.credentials = {type: credential_id}`; the backend validates at
  save time that (a) the node supports the type and (b) the credential
  exists and belongs to the user (422 otherwise).
- **Decrypt immediately before execution** (spec 29.5): the engine takes
  a `credential_resolver`; `_run_one` resolves the node's refs just
  before building parameters, and the resolved values land in the
  expression context as `$cred` (`{{ $cred.http.api_key }}` in headers,
  `{{ $cred.smtp.username }}`, …).
- **Frontend**: `CredentialStore` + a `CredentialsPanel` modal (list,
  delete, schema-driven create form with password inputs), a
  "🔑 Credentials" entry in the sidebar, and per-node credential selects
  in `ConfigPanel` for every type in the node's `credential_types`.

## 2. Why it took the shape it did (bugs found on the way)

1. **The `body: "none"` sentinel broke real HTTP runs** — the canvas
   sends `"body": "none"` for "no body", but the HTTP node treated any
   non-None value as a JSON payload, so GET requests went out with a
   `"none"` JSON body. On Windows, servers that don't read the request
   body close with RST (not FIN), so the client hit `httpx.ReadError`
   mid-response with an empty message (`"HTTP request failed: "`).
   It only shows against a live server, never in TestClient/respx.
   Fix: the node treats the string `"none"` as no body
   (`tests/test_nodes/test_http_request.py::test_body_none_sentinel_sends_no_payload`).
2. **ReadError vs the runner thread** — the empty ReadError message
   looked like a runner-thread/uvicorn issue; isolating it took a
   dedicated echo server + minimal reproductions (direct httpx call
   worked, full engine failed → bisected to the `body` value, not the
   transport).
3. **Types catalog needed `secret_fields`** — the UI must know which
   fields are secrets to render password inputs; `list_types()` now
   includes it.

## 3. Files

```text
backend/app/
├── credentials/
│   ├── registry.py          # type schemas, SECRET_FIELDS, list_types
│   └── service.py           # CRUD + resolve_credentials (decrypt)
├── security/crypto.py       # Fernet helpers, dev-key fallback
├── models/credential.py     # id/name/type/data(LargeBinary)
├── api/credentials.py       # /api/credentials* router
├── schemas/workflow.py      # WorkflowNode.credentials
├── api/workflows.py         # _validate_credential_refs (create + update)
├── api/executions.py        # credential_resolver wiring
├── engine/executor.py       # per-node resolution before run
├── engine/expressions.py    # $cred in the expression context
└── nodes/http_request.py    # credential_types = ["http"], body "none" fix

backend/tests/
├── test_credentials_engine.py   # $cred, missing cred, resolver wiring
└── test_api/test_credentials.py # CRUD, encryption at rest, isolation

frontend/src/
├── stores/credentialStore.js
├── components/CredentialsPanel.jsx
├── components/ConfigPanel.jsx   # per-type credential selects
├── components/Sidebar.jsx       # "🔑 Credentials" entry
└── api.js                       # list/create/delete/types
```

## 4. Verification

- `pytest`: **130 passed** (114 before M6 + 9 credential API + 6 engine +
  +1 body-sentinel regression); pyright clean.
- Live E2E (`backend/data/app.db`):
  - credential created → raw column is a `gAAAA…` Fernet token, no
    plaintext anywhere;
  - workflow with an `http_request` node + `credentials: {http: …}` and
    `X-Echo: {{ $cred.http.api_key }}` → run succeeded, echo server
    received `E2E_SECRET_KEY_42`;
  - workflow referencing an unknown credential → rejected 422 at save;
  - delete works, list returns metadata only.
