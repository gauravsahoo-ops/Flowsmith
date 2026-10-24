# Connector Status

**Last verified:** 2026-10-24  
**Source of truth:** `backend/scripts/connector_status.py`

Flowsmith distinguishes three connector populations. They are **not** equivalent.

| Kind | Count | What it means |
|---|---:|---|
| **Native** | **76** | Hand-written, vendor-specific connector classes in `backend/app/connectors/*_connector.py` |
| **Generated** | **17** | Generated from OpenAPI descriptions under `backend/app/connectors/generated/` |
| **Catalog-only** | **435** | Generic entries derived from the reference inventory. They have no vendor-specific execution code and require an explicit `endpoint_url`. |
| **Total registered names** | **528** | The number the registry exposes to discovery/UI |

These counts describe the built-in/factory registry. Admin-installed
[connector packs](CONNECTOR_PACKS.md) add generated connectors at runtime and
are intentionally **not** included in these static counts.

Declared operations by kind:

| Kind | Declared operations |
|---|---:|
| Native | 474 |
| Generated | 151 |
| Catalog-only | 1,005 (generic HTTP operations) |
| **Total** | **1,630** |

## What catalog-only means

A catalog-only connector is a **generic HTTP adapter**, not a native integration. It is useful for quick API experiments, but it does not implement vendor-specific resources, pagination, auth refresh, or error taxonomy.

Execution behavior:

- With an explicit `endpoint_url`: it performs a real, SSRF-guarded HTTP request.
- Without `endpoint_url`: it raises `CONNECTOR_NOT_CONFIGURED`.
- It **never** returns a synthetic success payload.

This is enforced by:

- `backend/app/connectors/parity_connectors.py`
- `backend/tests/test_no_fake_success.py`
- `backend/tests/test_parity_connectors_full.py`

## Public claims

Use these numbers unless this document and the script are updated together:

- **76 native connectors**
- **17 OpenAPI-generated connectors**
- **435 catalog-only reference integrations**
- **528 registered connector names**

Do not describe 528 as “528 native connectors” or “528 integrations equivalent to n8n.” Do not use 528 as proof of vendor coverage.

## Refresh

From `backend/`:

```bash
python scripts/connector_status.py
```

The script prints the current counts and a JSON summary. Update this file whenever the native/generated/catalog-only split changes.
