# Connector Packs

Flowsmith includes an **admin-only connector-pack installer and signed
distribution foundation**. A pack combines an OpenAPI/Swagger spec with metadata
and optional workflow templates. Installation generates a first-class connector
through the same importer used by the Integrations page, validates the generated
code and templates, stores the generated sources in PostgreSQL, and makes them
available to API and worker processes.

This is still **not** a Flowsmith-hosted public marketplace. It can consume a
signed registry index hosted anywhere, verify manifests, enforce pack-level
dependencies, detect revoked signing keys, and propagate install/upgrade/
uninstall changes to other API and worker processes. There is no Flowsmith-
operated registry, 50-pack external catalog, content moderation team, or
dependency installer in this release.

## Manifest format

```json
{
  "name": "petstore",
  "display_name": "Petstore",
  "version": "1.0.0",
  "description": "Petstore connector plus starter workflows.",
  "category": "api",
  "issued_at": "2026-10-24T12:00:00+00:00",
  "expires_at": "2026-10-31T12:00:00+00:00",
  "base_url": "https://api.example.com",
  "spec": "https://api.example.com/openapi.json",
  "spec_sha256": "9f2c...64 hex characters...",
  "signing_key_id": "release-2026",
  "signature": "base64-encoded Ed25519 signature",
  "templates": [
    {
      "name": "Petstore - List Pets",
      "description": "List pets when run manually.",
      "category": "general",
      "workflow_data": {
        "id": "wf_petstore_list",
        "name": "Petstore - List Pets",
        "nodes": [
          {"id": "trigger", "type": "manual_trigger", "parameters": {}},
          {"id": "list", "type": "petstore", "parameters": {"operation": "list_pets"}}
        ],
        "connections": [{"source": "trigger", "target": "list"}],
        "settings": {}
      }
    }
  ]
}
```

| Field | Required | Notes |
|---|---:|---|
| `name` | yes | Connector slug. Must not collide with an existing connector or pack. |
| `display_name` / `title` | no | Falls back to the OpenAPI `info.title`, then `name`. |
| `version` | no | PEP 440 version, default `1.0.0`. Upgrades must increase it. |
| `description` | no | Displayed in the installed-pack list. |
| `category` | no | Connector category, default `api`. |
| `spec` / `openapi` | yes | OpenAPI object, raw JSON/YAML string, or an HTTP(S) URL. |
| `spec_sha256` | for signed URL specs | SHA-256 of the fetched spec bytes. Required whenever a signed/remote manifest points at a spec URL. |
| `base_url` | no | Overrides the server URL declared by the spec. |
| `requires` / `dependencies` | no | Up to 50 installed connector-pack keys that must already exist. |
| `templates` | no | Up to 50 workflow templates. Names must be unique and not reserved. |
| `issued_at` / `expires_at` | remote manifests | Timezone-aware timestamps; maximum lifetime 30 days. Expired/future manifests are rejected. |
| `signing_key_id` / `signature` | remote manifests | Ed25519 signature over the canonical manifest. |

## Signing and trust

Remote `manifest_url` installs **always require** a valid signature. Inline
admin manifests may be unsigned by default; set
`CONNECTOR_PACK_REQUIRE_SIGNATURE=true` to require signatures there too.

Revoked signing key IDs can be rejected without changing the trusted key map:

```bash
CONNECTOR_PACK_REVOKED_KEYS=release-2025,compromised-key
```

Trusted public keys are configured as a JSON map:

```bash
CONNECTOR_PACK_TRUSTED_KEYS='{"release-2026":"MCowBQYDK2VwAyEA..."}'
```

The value can be a PEM public key or a base64-encoded raw 32-byte Ed25519 public
key. The signature covers the canonical JSON encoding of every manifest field
except `signature`; `signing_key_id` is part of the signed payload.

For URL specs, the signature also authenticates `spec_sha256`, and Flowsmith
fetches the spec once, verifies the digest, and passes the verified bytes to the
importer. This prevents a signed manifest from pointing at mutable spec content.

### Generate keys and sign

From `backend/`:

```bash
python scripts/sign_connector_pack.py keygen \
  --key-id release-2026 \
  --private-key pack-private.pem \
  --public-key pack-public.txt

python scripts/sign_connector_pack.py sign \
  --manifest pack.json \
  --private-key pack-private.pem \
  --key-id release-2026 \
  --output pack.signed.json
```

Keep private keys offline. Add `pack-public.txt` contents to
`CONNECTOR_PACK_TRUSTED_KEYS`. In Helm, use
`connectorPacks.trustedKeys`; in Compose, set the environment variable.
Set `connectorPacks.revokedKeys` / `CONNECTOR_PACK_REVOKED_KEYS` when rotating
or revoking a key.

### Signed registry index

A registry index is a signed JSON document listing pack metadata and the
`manifest_url` for each pack:

```json
{
  "schema_version": 1,
  "name": "Acme Private Registry",
  "issued_at": "2026-10-24T12:00:00+00:00",
  "expires_at": "2026-10-31T12:00:00+00:00",
  "packs": [
    {
      "name": "petstore",
      "display_name": "Petstore",
      "version": "1.2.0",
      "description": "Petstore connector",
      "category": "api",
      "manifest_url": "https://registry.example/petstore-1.2.0.json",
      "revoked": false
    }
  ],
  "signing_key_id": "release-2026",
  "signature": "base64-encoded Ed25519 signature"
}
```

Registry indexes must use HTTPS, carry timezone-aware `issued_at` and
`expires_at` fields, and have a lifetime of no more than 30 days. Expired or
future-issued indexes are rejected. The same `sign_connector_pack.py sign`
command signs it. The API
`POST /api/connector-packs/registry/preview` verifies the index signature and
returns its entries without installing anything; the Connector Packs modal
exposes this as the **Signed Registry** tab. Each pack manifest is still fetched
and verified independently before installation. A registry entry marked
`revoked: true` is displayed but cannot be installed from the UI.

## API

All endpoints require authentication. Mutating endpoints require an admin.

### `GET /api/connector-packs`

Lists installed packs, including version, signature status, signing key ID,
manifest SHA-256, template count, and timestamps.

### `POST /api/connector-packs/install`

Install from an inline manifest:

```bash
curl -X POST "$FLOWSMITH_URL/api/connector-packs/install" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"manifest": {"name": "petstore", "spec": "https://api.example.com/openapi.json"}}'
```

Install from a signed manifest URL:

```bash
curl -X POST "$FLOWSMITH_URL/api/connector-packs/install" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"manifest_url": "https://example.com/packs/petstore.json"}'
```

### `POST /api/connector-packs/{connector_key}/upgrade`

Accepts the same `manifest` / `manifest_url` body. The manifest name must map to
the same connector key, and the new version must be greater than the installed
version. The connector is regenerated, pack-owned templates are replaced, and
the database/registry/files are rolled back on failure.

### `DELETE /api/connector-packs/{connector_key}`

Removes the generated connector, pack-owned templates, and pack row. If any
active workflow contains the connector node type, uninstall is rejected with
`409 Conflict`; deactivate those workflows first.

### UI

**Integrations → Connector Packs** installs packs, shows signature status, and
offers Upgrade and Uninstall actions.

## Installation and lifecycle behavior

1. The manifest URL and OpenAPI spec URL are fetched through the shared
   SSRF-safe HTTP client with timeouts and response-size caps.
2. Remote manifests are signature-verified; signed URL specs are digest-verified
   before parsing.
3. The spec is parsed and generated with the existing OpenAPI importer.
4. Generated modules must parse and contain only the expected module docstring,
   future import, and generated statements.
5. The connector key is reserved with a PostgreSQL advisory transaction lock so
   concurrent operations on the same key cannot overwrite each other.
6. Optional templates are graph-validated, stripped of credentials/secrets, and
   stored as public starter templates with a `pack_key` owner.
7. The three generated source files are stored in `connector_packs.generated_sources`
   and written to the process's generated directory.
8. Upgrade invalidates cached generated modules so the new connector code is
   actually loaded, not the old `sys.modules` entry.
9. On failure, generated files and registry entries are removed/restored and the
   database transaction is rolled back. There is no partial pack row.

## Runtime availability

Generated sources are materialized from PostgreSQL in each API and worker
process:

- at startup, via `load_installed_packs()`;
- lazily when an execution encounters an unknown connector node type,
  via `ensure_pack_connector()`.

This avoids requiring a shared container filesystem. The process needs write
access to `backend/app/connectors/generated` (or the equivalent path in the
container). If the root filesystem is read-only, mount a writable volume at that
path or pre-materialize the files before starting the container.

A failed lazy-load attempt is cached for five seconds so unknown node types do
not repeatedly query PostgreSQL.

## Limits and security boundaries

- Admin-only installation, upgrade, and uninstall.
- Remote manifests must be signed. Inline manifests can be made signature-only
  with `CONNECTOR_PACK_REQUIRE_SIGNATURE=true`.
- Manifest size cap: 1 MB. OpenAPI spec fetch cap: 5 MB.
- Maximum 50 templates per pack.
- Duplicate connector keys and conflicting template names are rejected with
  `409 Conflict`.
- Version rollback is rejected; versions must increase.
- Uninstall is rejected while an active workflow or another installed pack
  depends on the connector. The API/worker reconciler polls PostgreSQL every
  10 seconds and removes revoked/tombstoned packs from other processes.
  Uninstall request paths remove the connector immediately in the handling
  process.
- A signing key listed in `CONNECTOR_PACK_REVOKED_KEYS` is rejected for new
  installs and the reconciler unregisters already-installed packs signed by
  that key. The pack row remains visible with `revoked: true` so an admin can
  uninstall or replace it.
- Pack-level dependencies are checked at install/upgrade/uninstall time. Python
  package dependency installation is still not performed.
- Packs installed before the `pack_key` migration have no template-ownership
  marker; upgrading or uninstalling them may leave those older templates in
  place. Reinstall them to establish ownership.
- Template replacement deletes the pack's old templates. User-created templates
  with different ownership are never deleted.
- There is a signed registry-index client and revocation flags for entries and
  signing keys, but no Flowsmith-hosted registry, moderation service, automatic
  revocation feed, public 50-pack catalog, or Python dependency resolver yet.
  There is no cryptographic attestation chain beyond the signed manifest,
  signing key ID, and manifest/SHA-256 provenance stored by Flowsmith.
  The 50-external-pack ecosystem target is not met by this code alone.
- Generated source integrity is protected by the AST shape check plus the
  manifest signature. Database administrators can still alter stored sources;
  protect database credentials accordingly.
- Pack installation requires database write access and filesystem write access.
  It does not install Python dependencies; the spec must target capabilities
  available in the running image.
