# Workflow import / export

Workflows are portable JSON documents. Export produces a
self-describing envelope; import accepts three shapes and normalizes
them into the native format (`app/importexport.py`).

## Export

`GET /api/workflows/{id}/export` (any viewer) returns:

```json
{
  "format": "opencode-workflow",
  "version": 1,
  "exported_at": "2026-08-20T…",
  "workflow": { "id": "…", "name": "…", "nodes": […], "connections": […], "settings": {} }
}
```

The `workflow` object is exactly what `POST /api/workflows` accepts, so
export → import round-trips losslessly (node ids, positions, parameters
and settings are preserved). The UI exposes this as **⬇ Export** in the
TopBar (downloads a JSON file).

## Import

`POST /api/workflows/import` (authenticated) accepts:

1. the export envelope above (detected by `format`/`workflow`),
2. a bare native document (`nodes` is a list, `connections` a list),
3. an **n8n workflow export**.

Id collisions are handled by minting a fresh id (`wf_import_<hex>`);
the original id is reported in `meta.source_id`. The imported workflow
is created as a new draft (version 1) with a version snapshot, exactly
like `POST /api/workflows`.

## n8n conversions

| n8n type | native type | parameter mapping |
| --- | --- | --- |
| `n8n-nodes-base.manualTrigger` | `manual_trigger` | — |
| `n8n-nodes-base.scheduleTrigger` | `schedule` | `rule.cronExpression` / `cron`, `timezone` |
| `n8n-nodes-base.set` | `set_data` | `assignments[]` → `fields` (merge mode) |
| `n8n-nodes-base.if` | `if_condition` | first condition, common operators (equals/notEquals/contains/startsWith/greaterThan/lessThan) |
| `n8n-nodes-base.httpRequest` | `http_request` | `method`, `url`, `sendHeaders` → `headers`, `jsonBody` → `body` |
| `n8n-nodes-base.webhook` | `webhook` | `path`, `httpMethod` |
| `n8n-nodes-base.salesforce` | `salesforce` | `resource`/`operation` preserved, rest passed through |

Structural conversions: positions `[x, y]` → `{x, y}`; dict-form
`connections` (per-source output handles) → connection list with
`sourceHandle`/`targetHandle` (IF true/false branches map correctly);
edges referencing nodes that are not in the document (n8n keeps unused
branches) are dropped.

Credentials referenced by n8n nodes are **not** imported (credentials
are per-user here) — re-attach them in the UI before running.

Unknown n8n node types are rejected with a 422 listing the unsupported
types, rather than silently importing a workflow that cannot run.

## Tests

`backend/tests/test_api/test_importexport.py` — round-trip, native
import, id-collision handling, n8n conversion (nodes, positions,
IF-handle edges, dangling branches), unknown-type rejection, auth.