# Connector Status

**Last verified:** 2026-10-24  
**Source of truth:** `backend/scripts/connector_status.py`

Flowsmith distinguishes three connector populations. They are **not** equivalent.

| Kind | Count | What it means |
|---|---:|---|
| **Native** | **201** | Hand-written vendor connectors plus native REST batches in `vendor_rest.py` and `vendor_rest_batch*.py` |
| **Generated** | **17** | Generated from OpenAPI descriptions under `backend/app/connectors/generated/` |
| **Catalog-only** | **311** | Generic entries derived from the reference inventory. They have no vendor-specific execution code and require an explicit `endpoint_url`. |
| **Total registered names** | **529** | Registry entries retained for workflow/credential compatibility |
| **Canonical discovery entries** | **504** | 529 minus 25 internal-test and duplicate aliases hidden from discovery |

These counts describe the built-in/factory registry. Admin-installed
[connector packs](CONNECTOR_PACKS.md) add generated connectors at runtime and
are intentionally **not** included in these static counts.

Discovery hides internal test fixtures (`e2e_test`,
`e2e_test_polling_trigger`) and duplicate catalog aliases such as
`active_campaign` and `microsoft_teams`. Those keys remain registered so old
workflows and credentials still resolve, but they are not advertised as
separate integrations. The audit manifest records each entry's
`catalog_hidden`, `alias_of`, and `internal` fields.

The runtime **node registry currently exposes 78 node keys**, including the
provider-trigger and HTTP-polling trigger nodes. The certification manifest
under `docs/audit/flowsmith_connector_manifest.json` is synchronized with that
list; the completeness gate passes. “Registered” still does not mean every
vendor API has been live-certified.

### Catalog-only breakdown

The 311 catalog-only registry entries are not 311 native-conversion targets:

| Scope | Count | Meaning |
|---|---:|---|
| `vendor` | **143** | Remaining vendor-ish entries after batches 1-22 — native-conversion candidates |
| `trigger_alias` | **95** | Trigger aliases, not action connectors |
| `node_shadow` | **73** | Names that already exist as workflow node classes |

This breakdown is enforced by `test_parity_connectors_full.py::test_catalog_only_scope_breakdown`.

### Native conversion batch 1

The first native batch has moved these ten entries out of catalog-only:

`action_network`, `bamboo_hr`, `chargebee`, `circle_ci`, `confluence`,
`contentful`, `customer_io`, `databricks`, `freshservice`, and `bitly`.

They use fixed vendor hosts, vendor-specific auth, and explicit operation maps
in `backend/app/connectors/vendor_rest.py`. Their tests mock the safe HTTP
client and cover host selection, required fields, auth failure, and operation
metadata. **They are contract-tested, not live-certified**; live credentials
are still required for vendor acceptance.

Batch 2, implemented from the n8n node reference implementations, adds:

`adalo`, `affinity`, `agile_crm`, `airtop`, `bannerbear`, `baserow`,
`brandfetch`, `bubble`, `dhl`, and `figma`.

Figma was not present in the original inventory, so it is a new native
connector; the total registered names is now **529**.

Batch 3, also mapped from n8n reference nodes, adds:

`drift`, `dropcontact`, `egoi`, `emelia`, `harvest`, `lemlist`,
`mailer_lite`, `mailgun`, `mattermost`, and `noco_d_b`.

Batch 4 adds:

`mailjet`, `message_bird`, `netlify`, `okta`, `onfleet`, `pushbullet`,
`travis_ci`, `webflow`, `wise`, and `zammad`.

Batch 5 adds:

`open_ai`, `paddle`, `sms77`, `taiga`, `monica_crm`, `nasa`, `npm`,
`marketstack`, `mailcheck`, and `mautic`.

Parallel batches 6–22 added 75 more supported native connectors in
`vendor_rest_batch6.py` through `vendor_rest_batch22.py`. Unsupported keys
remain catalog-only with per-batch reasons; the main blockers are AWS SigV4,
OAuth2 token exchange, body/form auth, wire protocols, and local-only
transforms. **143 vendor candidates remain.**

Declared operations by kind:

| Kind | Declared operations |
|---|---:|
| Native | 1,177 |
| Generated | 151 |
| Catalog-only | 755 (generic HTTP operations) |
| **Total** | **2,083** |

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

- **201 native connectors**
- **17 OpenAPI-generated connectors**
- **311 catalog-only reference integrations**
- **529 registered connector names**
- **504 canonical connector names shown in discovery**

Do not describe 528 as “528 native connectors” or “528 integrations equivalent to n8n.” Do not use 528 as proof of vendor coverage.

## Refresh

From `backend/`:

```bash
python scripts/connector_status.py
```

The script prints the current counts and a JSON summary. Update this file whenever the native/generated/catalog-only split changes.
