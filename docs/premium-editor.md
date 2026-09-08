# Phase 12 — Premium Workflow Editor

> Phase 13 (workflow debugger) lives in `docs/workflow-debugger.md`.

Frontend-only upgrade of the React Flow editor (@xyflow/react v12).
No backend/API changes: everything persists through the existing
workflow document (`WorkflowNode` is extra-allow and
`workflow.settings` is free-form, so editor decoration rides along in
`settings.editor` without touching the engine contract).

## Feature map

| Feature | Where | Notes |
|---|---|---|
| Node search | Sidebar | fuzzy match over display name/type/category; `×N` chip jumps to canvas instances |
| Drag/drop | Sidebar → Canvas | existing; adds drop-target highlight overlay |
| Keyboard shortcuts | Canvas global handler | see table below; inputs/textareas exempt except Ctrl+K |
| Undo/redo | `utils/history.js` + store | snapshot stack (100 deep); parameter typing coalesces into one step (600 ms same-key window); drags snapshot once at gesture start |
| Copy/paste | store clipboard | Ctrl+C/X/V; internal edges travel with copies; paste offsets +48px |
| Duplicate | store (pre-existing) + Ctrl+D | unchanged behaviour |
| Multi-select | React Flow shift-drag / shift-click | all store ops accept id arrays |
| Grouping | GroupNode + store.groups | visual frame; drag moves contained nodes; geometry auto-follows members; ungroup keeps nodes; empty groups prune themselves |
| Comments | CommentNode + store.comments | sticky notes; double-click edit; blank = self-delete; colour variants |
| Labels | ConfigPanel "Appearance" (node label) + `setEdgeLabel` API (wire labels) | node label/color persist in `node.settings`; wire labels in `settings.editor.edgeLabels` keyed by connection signature |
| Minimap | React Flow MiniMap (restyle) | pannable/zoomable, dark mask |
| Zoom | Controls + Ctrl+=/-, Ctrl+0 fit, toolbar Fit | min/max zoom clamps 0.1–2.5 |
| Auto-layout | `utils/autoLayout.js` | dependency-free Sugiyama-lite: longest-path layers + barycenter sweeps, LR/TB, cycle-safe, isolated-column parking; single undo step; lazy-loaded chunk |
| Connection validation | `utils/graphUtils.wouldCreateCycle` + health panel | cycles rejected at connect time; toolbar badge shows problem count (cycles/orphans/duplicate wires) with drill-down list |
| Execution highlighting | ExecutionEdge + CustomNode | wires animate green once their source completes; red thickens on failed targets |
| Error highlighting | CustomNode | failed cards get red ring + inline error excerpt (from last-run trace) |
| Input/output preview | executionStore.runPreview + CustomNode chips | per-node output-count + duration chips after a run; derived once per trace update |
| Command palette | CommandPalette.jsx (Ctrl+K) | commands + add-node catalog + go-to-node, subsequence fuzzy scoring, ↑↓/⏎ navigation |
| Config panels | ConfigPanel | collapsible sections: Parameters / Appearance / Credential / Execution |

## Keyboard map

| Keys | Action |
|---|---|
| Ctrl+K | command palette (works while typing) |
| Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y | undo / redo |
| Ctrl+C / Ctrl+X / Ctrl+V | copy / cut / paste selection |
| Ctrl+A | select all nodes |
| Ctrl+D | duplicate selection |
| Delete / Backspace | delete selection (React Flow built-in) |
| Ctrl+= / Ctrl+- / Ctrl+0 | zoom in / out / fit |
| Escape | clear selection / close overlays |
| ? | open palette (shortcuts reference) |

## Large-workflow optimisations

- memoized `CustomNode` with **primitive** zustand selectors
  (`catalogIndex.get(type)`, `nodeStatuses[id]`, `runPreview[id]`) — a
  status event re-renders exactly the transitioning nodes;
- `runPreview` derived once per trace update in the store, never per render;
- catalog lookup via prebuilt `Map` (was `Array.find` per node per render);
- `onlyRenderVisibleElements` on the canvas;
- history snapshots are shallow array copies (nodes are immutable);
- debounced saves (existing 500 ms) unchanged.

## Persistence shape

```jsonc
// workflow.settings.editor (stripped entirely when empty)
{
  "comments": [{ "id": "comment_ab12", "x": 40, "y": 80, "width": 220,
                 "height": 90, "text": "review before enabling", "color": "amber" }],
  "groups":   [{ "id": "group_c34d", "label": "Stage 1", "x": 0, "y": 0,
                 "width": 420, "height": 260, "color": "blue" }],
  "edgeLabels": { "a|main|b|main": "only if approved" }
}
```

Comments/groups are ephemeral React Flow elements rebuilt on load — they
never enter `workflow.nodes`, so graph validation and the executor are
untouched. Import/export carries them automatically inside settings.

## Tests

- `src/editor.test.js` (16): history coalescing/limits/redo-branch
  invalidation; cycle detection incl. back-edge direction bug caught by
  test; graph validation; auto-layout layering/isolates/cycles/TB;
  decoration round-trip; fuzzy scoring.
- Existing suites untouched and green: 135/135 vitest; Playwright E2E
  selectors (`.canvas`, `.rf-node.status-*`, `__wfStore` hooks,
  `addNode/onConnect/updateNode/save` signatures) all preserved.
