# Phase 22 — New nodes: slack, telegram, websocket, csv/json, file I/O

> **Status:** done — five new node types extend the built-in set; all
> declare `credential_types`, idempotency and version like every other
> node, and are catalog-served to the canvas automatically.

## 1. What Phase 22 delivers

- **`slack`** — send a message to a Slack channel via
  `https://slack.com/api/chat.postMessage` with a `slack` credential
  (bot token). Returns the posted message metadata.
- **`telegram`** — send a message via the Bot API
  (`https://api.telegram.org/bot<token>/sendMessage`) with a
  `telegram` credential (bot token + optional chat id in params).
- **`websocket`** — connect to a WS endpoint and send/receive a
  message (`websockets` library); used for live-streaming bridges.
- **`csv_json_transform`** — convert CSV text ⇄ JSON arrays with
  delimiter/header options.
- **`file_io`** — read/write local files (path + content params) for
  on-box automation; the path is resolved on the machine running the
  worker.

All five follow the Node SDK contract: registered via
`@register`, declare a Pydantic `parameters_schema`, credential types
where applicable, and idempotency levels (spec 35) so retry safety is
surfaced in the UI.

## 2. Files

```text
backend/app/nodes/slack.py               # Slack node (credential: slack)
backend/app/nodes/telegram.py            # Telegram node (credential: telegram)
backend/app/nodes/websocket.py           # WebSocket send/receive node
backend/app/nodes/csv_json_transform.py  # CSV <-> JSON transform node
backend/app/nodes/file_io.py             # file read/write node
backend/app/nodes/registry.py            # import list extended
frontend/src/components/ConfigPanel.jsx  # credentials UI (generic, schema-driven)
```

## 3. Verification

- Each node registered in the catalog with schema, credential types
  and idempotency; execution covered by node tests.
- Full suite green; pyright clean; frontend build/lint clean.