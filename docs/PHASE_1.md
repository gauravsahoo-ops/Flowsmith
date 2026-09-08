# Phase 1 — Execution Engine (M1)

> **Milestone:** `execute_workflow` runs a workflow from JSON: manual
> trigger → HTTP → set-data. Tests green.
> **Status:** ✅ Complete — 44 tests passing

## 1. What Phase 1 delivers

The engine is the core product (spec §67: engine first, canvas last).
It reads the workflow JSON contract, validates the graph, executes
nodes in topological order, passes data between them, and records
per-node status — with no UI and no HTTP API yet.

```text
workflow JSON ──► validate ──► topological sort ──► execute nodes ──► results + events
```

## 2. What to do

- Build a workflow in JSON and run it from Python (see demo below)
- Branch with IF, merge items from multiple parents, resolve `{{ }}`
  expressions, fail/retry-aware error handling, per-node timeouts,
  cooperative cancellation
- Register new node types without touching engine code (the SDK)

## 3. Project layout

```text
backend/
├── requirements.txt        # pydantic, httpx, pytest, pytest-asyncio, respx
├── pytest.ini
├── app/
│   ├── schemas/workflow.py # workflow JSON contract (Pydantic, §6/§24)
│   ├── engine/
│   │   ├── errors.py       # WorkflowValidationError, NodeExecutionError,
│   │   │                   #   NodeTimeoutError, NodeCancelledError (§27)
│   │   ├── graph.py        # build_graph, validate_graph, topological_sort (§8.1)
│   │   ├── node_base.py    # BaseNode / NodeContext / NodeResult SDK (§7/§26)
│   │   ├── expressions.py  # safe {{ }} evaluator, no eval/exec (§30)
│   │   └── executor.py     # execute_workflow() — the engine (§8.5)
│   └── nodes/              # node registry + built-in nodes
│       ├── registry.py     # NODE_REGISTRY = {type: class} (§7)
│       ├── manual_trigger.py
│       ├── http_request.py
│       ├── set_data.py
│       └── if_condition.py
└── tests/
    ├── conftest.py         # workflow builders + stub nodes (slack, db, boom, slow)
    ├── test_graph.py       # validation rules (§24.3)
    ├── test_engine.py      # execution behavior (§51.1) — the most important file
    └── test_nodes/         # per-node tests (§51.3)
```

## 4. The workflow contract (single source of truth)

Defined once in `app/schemas/workflow.py` (§6, §24). Both the future
API and frontend must speak this shape.

```json
{
  "id": "wf_001",
  "name": "Greet someone",
  "nodes": [
    { "id": "trigger", "type": "manual_trigger", "position": {"x": 0, "y": 0}, "parameters": {} },
    { "id": "set", "type": "set_data", "position": {"x": 200, "y": 0},
      "parameters": { "fields": { "greeting": "Hello {{ $json.name }}!" } } }
  ],
  "connections": [
    { "source": "trigger", "sourceHandle": "main", "target": "set", "targetHandle": "main" }
  ]
}
```

Engine settings per node (`node.settings`):

| Setting                | Meaning                                            |
| ---------------------- | -------------------------------------------------- |
| `continue_on_error`    | On failure pass a `$error` item onward instead of stopping (§8.3) |
| `timeout_seconds`      | Kill the node after N seconds → `NODE_TIMEOUT` (§36) |

## 5. Built-in nodes

| Type             | Category    | Handles        | Notes                                  |
| ---------------- | ----------- | -------------- | -------------------------------------- |
| `manual_trigger` | Triggers    | out: main      | Passes trigger items through           |
| `http_request`   | Actions     | in/out: main   | GET/POST/PUT/PATCH/DELETE, typed errors |
| `set_data`       | Transform   | in/out: main   | merge or replace mode, creates from nothing |
| `if_condition`   | Logic       | out: true/false| 7 operators, per-item `$json.path`     |

IF conditions evaluate `$json.field` paths natively per item; `{{ }}`
expressions are resolved once by the executor against the first input
item (§8.5).

## 6. Key engine behaviors

- **Validation (§24.3):** unique node ids, known node types, valid
  parameters, connections reference existing nodes, valid handles,
  no cycles. Errors carry `{code, node_id, field, message}`.
- **Ordering:** Kahn topological sort — every node runs after its
  parents. Cyclic graphs are rejected with `CYCLIC_GRAPH`.
- **Data flow:** items are plain JSON dicts. Multi-parent nodes
  combine items from each parent edge, respecting source handles.
- **Errors (§8.3):** a node failure stops downstream nodes (marked
  skipped) and fails the execution — unless `continue_on_error`,
  in which case `{"$error": {...}}` flows onward.
- **Timeouts (§36):** per-node `timeout_seconds` via
  `asyncio.wait_for`; the shortest applicable timeout wins.
- **Cancellation (§36):** cooperative — cancelling the outer task
  marks the execution `cancelled`.
- **Expressions (§30):** `{{ $json.field }}`, `{{ $node.<id>.json.field }}`,
  `{{ $workflow.id }}`, `{{ $execution.id }}`, `{{ $now }}`. Path lookup
  only — no `eval`, no imports, no shell. Unresolvable expressions are
  left visible in the output.
- **Events (§37):** `execution.started`, `node.started`,
  `node.completed`, `node.failed`, `execution.failed/completed/cancelled`
  — the future WebSocket layer consumes these.

## 7. Running it

```powershell
cd backend
.\.venv\Scripts\python -m pytest          # 44 tests
```

Demo (from the repo root):

```powershell
@'
import sys, asyncio; sys.path.insert(0, "backend")
from app.schemas.workflow import Workflow
from app.engine.executor import execute_workflow

demo = Workflow(id="wf_demo", name="M1 demo", nodes=[
    {"id": "trigger", "type": "manual_trigger"},
    {"id": "set", "type": "set_data", "parameters": {"fields": {"greeting": "Hello {{ $json.name }}!"}}},
])
r = asyncio.run(execute_workflow(demo, [{"name": "Gaurav"}]))
print(r.status, "->", r.results["set"]["main"][0])
'@ | & .\backend\.venv\Scripts\python.exe -
```

Output: `success -> {'name': 'Gaurav', 'greeting': 'Hello Gaurav!'}`

## 8. How to add a new node (the SDK)

One file, two parts — no core changes (spec §7, §26):

```python
# app/nodes/my_node.py
from pydantic import BaseModel
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

class MyNodeParams(BaseModel):
    url: str

@register
class MyNode(BaseNode[MyNodeParams]):   # generic: params typed per node
    node_type = "my_node"
    display_name = "My Node"
    version = 1
    description = "Does something."
    category = "Actions"
    icon = "✨"
    parameters_schema = MyNodeParams

    async def run(self, ctx: NodeContext, params: MyNodeParams, input_items: list[dict]) -> NodeResult:
        return NodeResult(output_items=[{"url": params.url, **item} for item in input_items])
```

Then add `my_node` to the import in `app/nodes/registry.py`.

## 9. Test coverage map

| Area            | File                        | Covers                                                          |
| --------------- | --------------------------- | --------------------------------------------------------------- |
| Validation      | `tests/test_graph.py`       | empty/duplicate/unknown/invalid params/dangling/handles/cycles  |
| Engine          | `tests/test_engine.py`      | chains, branching, merging, error stop, continue_on_error,      |
|                 |                             | expressions, timeouts, cancellation, multi-item flow            |
| HTTP node       | `tests/test_nodes/`         | success, body, timeout, connection error, schema rejection      |
| IF node         | `tests/test_nodes/`         | 7 operators, literal, coercion, nested paths, invalid compare   |
| Set/Manual      | `tests/test_nodes/`         | merge/replace/no-input modes, passthrough                       |

## 10. Deferred to later phases (intentionally)

- Webhook / schedule / email / database nodes → M2
- FastAPI, auth, CRUD, SQLite/PostgreSQL → M3
- React Flow canvas → M4
- WebSocket live status → M5 (polling fallback is spec-approved)
- Credential encryption, retries, pruning → M6/M9
- AI nodes → M10

---

*Phase 1 of the roadmap in `docs/COMPLETE_OWN_N8N_ALTERNATIVE_DEVELOPER_SPEC.md` (M1, §18).*
