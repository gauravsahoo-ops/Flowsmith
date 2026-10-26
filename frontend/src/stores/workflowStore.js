// workflowStore: the canvas state, debounced-synced to the backend
// (spec 11: every canvas change -> 500ms debounced PUT).
//
// Phase 12 (premium editor): undo/redo history, internal clipboard,
// comment/group/edge-label decorations, cycle-safe connections and a
// memoized catalog index for large-workflow performance.

import { create } from 'zustand'
import { addEdge, applyEdgeChanges, applyNodeChanges } from '@xyflow/react'
import { api } from '../api'
import {
  readDecorations,
  toReactFlow,
  toWorkflowJson,
  withDecorations,
} from '../mappers'
import { useUiStore } from './uiStore'
import { edgeKey } from '../utils/graphUtils'
import { createHistory } from '../utils/history'

let saveTimer = null
let initPromise = null
let loadSeq = 0

function isDecorationId(id) {
  return typeof id === 'string' && (id.startsWith('comment_') || id.startsWith('group_'))
}

function resolveRef(prop, schema) {
  if (!prop?.$ref) return prop
  const name = prop.$ref.split('/').pop()
  return schema?.$defs?.[name] || prop
}

function defaultsFromSchema(schema) {
  const out = {}
  for (const [key, rawProp] of Object.entries(schema?.properties || {})) {
    const prop = resolveRef(rawProp, schema)
    if (prop.default !== undefined) out[key] = prop.default
    else if (prop.type === 'boolean') out[key] = false
    else if (prop.type === 'number' || prop.type === 'integer') out[key] = 0
    else if (prop.type === 'array') out[key] = []
    else if (prop.type === 'object') out[key] = {}
    else out[key] = ''
  }
  return out
}

export const useWorkflowStore = create((set, get) => ({
  workflow: null, // {id, name, version, active, ...}
  nodes: [],
  edges: [],
  catalog: [],
  catalogIndex: new Map(), // type -> meta (O(1) node lookups on big graphs)
  versions: [], // version history
  previewVersion: null, // snapshot object when previewing a historical version
  previewLoading: false,

  // editor decorations (Phase 12) — persisted via workflow.settings.editor
  comments: [], // [{id, x, y, width, height, text, color}]
  groups: [], // [{id, label, x, y, width, height, color}]
  edgeLabels: {}, // "<src>|<shandle>|<tgt>" -> label

  // undo/redo + clipboard
  canUndo: false,
  canRedo: false,
  clipboard: null, // {nodes: [...plain node json], edges, origin}

  loading: true,
  saving: false,
  savedAt: null,
  error: null,
  generated: null, // Phase 15: {workflow, validation, attempts} awaiting approval

  _history: createHistory(),
  _dirty: false,
  _editSeq: 0,
  _dragHistoryOpen: false,
  autoSave: false, // Auto-save disabled by default (manual save only)

  setAutoSave(enabled) {
    set({ autoSave: Boolean(enabled) })
  },

  // ------------------------------------------------------------------
  // history plumbing
  // ------------------------------------------------------------------

  /** Record the CURRENT state before a mutation. */
  pushHistory(coalesceKey = null) {
    const { nodes, edges, _history } = get()
    _history.push(nodes, edges, coalesceKey)
    set({ canUndo: _history.canUndo(), canRedo: false })
  },

  undo() {
    const { nodes, edges, _history } = get()
    const prev = _history.undo({ nodes, edges })
    if (!prev) return
    set({
      nodes: prev.nodes,
      edges: prev.edges,
      canUndo: _history.canUndo(),
      canRedo: true,
    })
    scheduleSave()
  },

  redo() {
    const { nodes, edges, _history } = get()
    const next = _history.redo({ nodes, edges })
    if (!next) return
    set({
      nodes: next.nodes,
      edges: next.edges,
      canUndo: true,
      canRedo: _history.canRedo(),
    })
    scheduleSave()
  },

  // Called only after the user has confirmed leaving the editor. The next
  // load of this workflow will replace the retained canvas with server state.
  discardUnsavedChanges() {
    clearTimeout(saveTimer)
    set({ _dirty: false, savedAt: null })
  },

  // ------------------------------------------------------------------
  // lifecycle
  // ------------------------------------------------------------------

  async init(preferredWorkflowId = null) {
    // Idempotent: React StrictMode double-invokes this in dev; a second
    // call must not create a duplicate workflow for fresh users.
    if (initPromise) return initPromise
    const loadSeqAtStart = loadSeq
    initPromise = (async () => {
      try {
        const catalog = await api.listNodes()
        set({
          catalog,
          catalogIndex: new Map(catalog.map((n) => [n.type, n])),
        })
        const list = await api.listWorkflows()

        // On /workflows/:id the editor page owns hydration. Loading the
        // most-recent workflow here would race it and can leave the canvas
        // showing the wrong workflow.
        if (preferredWorkflowId) return

        // A route/user load may have started while the catalog/list were in
        // flight. Let that newer request win instead of clobbering it with
        // the most-recent workflow from this list.
        if (loadSeq !== loadSeqAtStart) return

        // Keep loading=true until load/createNew finishes: showing the
        // canvas early lets edits race with the workflow hydration and
        // get clobbered (e.g. the first setName is lost).
        if (list.length) await get().load(list[0].id)
        else await get().createNew('My Workflow')
      } catch (err) {
        set({ loading: false, error: err.message })
      }
    })()
    return initPromise
  },

  async listVersions(workflowId) {
    try {
      const res = await api.listVersions(workflowId)
      // A version response for the previous workflow must not leak into the
      // history drawer after a switch.
      if (get().workflow?.id !== workflowId) return
      const list = Array.isArray(res) ? res : (res?.data || [])
      set({ versions: list })
    } catch {
      // non-critical, version history is optional
    }
  },

  async setPreviewVersion(versionNum) {
    const { workflow } = get()
    if (!workflow?.id) return
    if (!versionNum) {
      set({ previewVersion: null, previewLoading: false })
      return
    }
    const workflowId = workflow.id
    set({ previewLoading: true })
    try {
      const res = await api.getVersion(workflowId, versionNum)
      if (get().workflow?.id !== workflowId) return
      const data = res?.data || res
      set({ previewVersion: data, previewLoading: false })
    } catch (err) {
      if (get().workflow?.id !== workflowId) return
      set({ previewLoading: false, error: `Failed to load version: ${err.message}` })
    }
  },

  exitPreview() {
    set({ previewVersion: null, previewLoading: false })
  },

  async rollbackVersion(workflowId, version) {
    try {
      const res = await api.rollbackVersion(workflowId, { version })
      if (get().workflow?.id !== workflowId) return null
      const data = res?.data || res
      const { nodes, edges } = toReactFlow(data)
      const decor = readDecorations(data)
      set({ workflow: data, nodes, edges, ...decor, savedAt: new Date(), previewVersion: null, previewLoading: false })
      get()._history.reset()
      set({ canUndo: false, canRedo: false })
      await get().listVersions(workflowId)
    } catch (err) {
      set({ error: err.message })
      throw err
    }
  },

  async createNew(name) {
    const id = crypto.randomUUID()
    const wf = await api.createWorkflow({
      id,
      name,
      nodes: [],
      connections: [],
      settings: {},
    })
    set({
      workflow: wf,
      nodes: [],
      edges: [],
      comments: [],
      groups: [],
      edgeLabels: {},
      versions: [],
      previewVersion: null,
      previewLoading: false,
      generated: null,
      savedAt: new Date(),
      loading: false,
      saving: false,
      error: null,
      _dirty: false,
    })
    useUiStore.getState().closeNodeEditor()
    useUiStore.getState().selectNode(null)
    get()._history.reset()
    set({ canUndo: false, canRedo: false })
    return wf
  },

  async load(id) {
    // Rapid A -> B -> C navigation can resolve out of order. Only the most
    // recent load may hydrate the canvas; older responses are discarded.
    const requestId = ++loadSeq
    clearTimeout(saveTimer)
    set({ loading: true, saving: false, error: null })
    try {
      const wf = await api.getWorkflow(id)
      if (requestId !== loadSeq) return null
      let { nodes, edges } = toReactFlow(wf)
    // Migrate legacy Salesforce nodes with operation 'execute' (engine generic) → valid curated op + upgrade Account Get Many SOQL to include Type/LastModifiedDate for Table
    let needsSave = false
    nodes = nodes.map(n => {
      const nd = n.data?.node
      if (nd?.type === 'salesforce' && nd.parameters) {
        const p = { ...nd.parameters }
        let changed = false
        if (!p.operation || p.operation === 'execute' || p.operation === '') {
          p.operation = p.resource === 'Account' ? 'create' : p.resource === 'Search' ? 'search' : p.resource === 'Flow' ? 'flow_invoke' : p.resource === 'CustomApiCall' ? 'custom_api_call' : 'query'
          if (p.operation === 'execute') p.operation = 'create'
          changed = true
        }
        if (p.resource === 'execute') { p.resource = 'Account'; changed = true }
        // Upgrade Account Get Many SOQL to include real Type/LastModifiedDate for Table/JSON image parity
        if ((p.operation === 'query' || p.operation === 'get_many') && p.resource === 'Account' && typeof p.soql === 'string' && p.soql.includes('SELECT Id, Name FROM Account')) {
          p.soql = p.soql.replace('SELECT Id, Name FROM Account', 'SELECT Id, Name, Type, LastModifiedDate FROM Account')
          p.soql = p.soql.replace(/\s+LIMIT\s+\d+\s*$/i, '')
          p.max_pages = 100
          changed = true
        }
        if ((p.operation === 'query' || p.operation === 'get_many') && p.resource === 'Account' && typeof p.soql === 'string' && p.soql.includes('LIMIT') && p.soql.includes('Type')) {
          const stripped = p.soql.replace(/\s+LIMIT\s+\d+\s*$/i, '')
          if (stripped !== p.soql) { p.soql = stripped; p.max_pages = 100; changed = true }
        }
        if (changed) { needsSave = true; return { ...n, data: { node: { ...nd, parameters: p } } } }
      }
      return n
    })
      if (needsSave && get().autoSave) {
        saveTimer = setTimeout(() => get().save().catch(()=>{}), 600)
      }
      const decor = readDecorations(wf)
      set({
        workflow: wf,
        nodes,
        edges,
        ...decor,
        loading: false,
        saving: false,
        error: null,
        savedAt: needsSave ? null : new Date(),
        // A freshly loaded workflow is clean. Migration edits above may
        // legitimately need saving and therefore keep it dirty.
        _dirty: Boolean(needsSave),
        _editSeq: (get()._editSeq || 0) + 1,
        versions: [],
        previewVersion: null,
        previewLoading: false,
        generated: null,
      })
      useUiStore.getState().closeNodeEditor()
      useUiStore.getState().selectNode(null)
      useUiStore.getState().closeHistoryDrawer()
      get()._history.reset()
      set({ canUndo: false, canRedo: false })
      get().listVersions(id).catch(() => {})
      return wf
    } catch (err) {
      // A superseded request failed after a newer one succeeded; do not
      // surface its error or clear the new workflow's loading state.
      if (requestId !== loadSeq) return null
      set({ loading: false, saving: false, error: err.message })
      throw err
    }
  },

  async deleteWorkflow(id) {
    // Cancel any pending debounced save so it can't fire into a 404
    // after the workflow is gone.
    clearTimeout(saveTimer)
    await api.deleteWorkflow(id)
    set({ workflow: null, nodes: [], edges: [], versions: [], comments: [], groups: [], edgeLabels: {}, savedAt: null })
    get()._history.reset()
    set({ canUndo: false, canRedo: false })
    const list = await api.listWorkflows()
    if (list.length) await get().load(list[0].id)
    else await get().createNew('My Workflow')
  },

  async generateWorkflow(prompt) {
    // Phase 15: the candidate is a PREVIEW — creation happens only on
    // explicit user approval (approveGenerated).
    const res = await api.generateWorkflow(prompt)
    set({ generated: res })
    return res
  },

  async approveGenerated() {
    const { generated } = get()
    if (!generated?.workflow) return null
    const saved = await api.createWorkflow(generated.workflow)
    set({ generated: null })
    await get().load(saved.id)
    useUiStore.getState().selectNode(null)
    return saved
  },

  discardGenerated() {
    set({ generated: null })
  },

  // ------------------------------------------------------------------
  // canvas event handlers
  // ------------------------------------------------------------------

  onNodesChange(changes) {
    // Decorations are ephemeral canvas elements (not store.nodes): route
    // their changes to the decoration stores instead.
    const decor = changes.filter((c) => isDecorationId(c.id))
    const plain = changes.filter((c) => !isDecorationId(c.id))
    for (const c of decor) {
      if (c.type === 'position' && c.position) {
        if (c.id.startsWith('comment_')) {
          set({
            comments: get().comments.map((cm) =>
              cm.id === c.id ? { ...cm, x: c.position.x, y: c.position.y } : cm,
            ),
          })
          scheduleSave()
        }
        // Groups move via GroupNode's own handler (moves members too).
      } else if (c.type === 'remove') {
        if (c.id.startsWith('comment_')) get().deleteComment(c.id)
        else if (c.id.startsWith('group_')) get().ungroup(c.id)
      }
    }

    // Position drags commit as ONE undo step: snapshot the pre-drag state
    // when the gesture starts (first streaming position change), never
    // during or after. Programmatic moves (auto-layout/paste) push their
    // own history before mutating.
    const startsDrag = plain.some(
      (c) => c.type === 'position' && c.dragging === true,
    )
    if (startsDrag && !get()._dragHistoryOpen) {
      set({ _dragHistoryOpen: true })
      get().pushHistory()
    }
    const structural = plain.some((c) =>
      ['remove', 'add'].includes(c.type),
    )
    if (structural) get().pushHistory()
    const hasUserEdit = plain.some(
      (c) =>
        c.type === 'remove' ||
        c.type === 'add' ||
        (c.type === 'position' && (c.dragging === false || (!c.dragging && c.position)))
    )
    if (plain.length) {
      set({ nodes: applyNodeChanges(plain, get().nodes) })
      syncGroupBounds(get, set)
      if (hasUserEdit) {
        scheduleSave()
      }
    }
    if (startsDrag) {
      // The gesture's final change arrives in a later batch; close the
      // window then so a fresh gesture re-snapshots.
      queueMicrotask(() => {
        set({ _dragHistoryOpen: false })
      })
    }
  },
  onEdgesChange(changes) {
    const hasStructural = changes.some((c) => c.type === 'remove' || c.type === 'add')
    const hasSelection = changes.some((c) => c.type === 'select' || c.type === 'deselect')
    if (hasStructural) {
      get().pushHistory()
      set({ edges: applyEdgeChanges(changes, get().edges) })
      scheduleSave()
    } else if (hasSelection) {
      // Selection is managed internally by React Flow — don't touch our store
      // to avoid re-creating the edges array on every pointermove.
    } else {
      // Other changes (dimensions, etc.)
      set({ edges: applyEdgeChanges(changes, get().edges) })
    }
  },
  onConnect(connection) {
    const { edges, canConnect } = get()
    if (!canConnect(connection)) return
    get().pushHistory()
    set({
      edges: addEdge(
        { ...connection, id: crypto.randomUUID(), data: { isNew: true } },
        edges,
      ),
    })
    scheduleSave()
  },

  canConnect(connection) {
    // Only reject self-loops (a node can't connect to itself). Cycles and
    // duplicate wires are allowed — the backend engine executes nodes in
    // topological order with each node running at most once per pass, so
    // a visual cycle is harmless. Duplicate edges (e.g. two wires from
    // A to B on different handles) are also fine and sometimes needed.
    if (!connection.source || !connection.target || connection.source === connection.target) {
      return false
    }
    return true
  },

  nextNodeId(base) {
    const ids = new Set(get().nodes.map((n) => n.id))
    let i = 1
    while (ids.has(`${base}_${i}`)) i += 1
    return `${base}_${i}`
  },

  addNode(type, position) {
    // catalogIndex is built at init; fall back to a scan when tests or
    // hot-reload injected a raw catalog without it.
    const meta =
      get().catalogIndex.get(type) ||
      get().catalog.find((n) => n.type === type) ||
      {}
    const { nodes, nextNodeId } = get()
    const id = nextNodeId(type)
    const rawParams = defaultsFromSchema(meta.parameters_schema)
    // Salesforce single source: ensure new nodes never start as 'execute' (engine generic)
    let parameters = rawParams
    if (type === 'salesforce') {
      const p = { ...rawParams }
      if (!p.resource || p.resource === 'Record' || p.resource === 'Other') p.resource = 'Account'
      if (p.object_name === 'Record') p.object_name = 'Account'
      if (!p.operation || p.operation === 'execute' || p.operation === '') {
        // Curated default for Account
        p.operation = 'create'
        p.object_name = p.object_name || 'Account'
        if (!p.record) p.record = { Name: '' }
      }
      // Migrate legacy execute
      if (p.operation === 'execute') p.operation = 'create'
      parameters = p
    }
    if (type === 'http_request') {
      const p = { ...rawParams }
      if (!p.url || p.url === '') p.url = ''
      if (!p.method) p.method = 'GET'
      // Ensure toggles default to false for new nodes (clean empty state)
      if (p.sendQuery === undefined) p.sendQuery = false
      if (p.sendHeaders === undefined) p.sendHeaders = false
      if (p.sendBody === undefined) p.sendBody = false
      if (!p.bodyContentType) p.bodyContentType = 'json'
      if (!p.jsonBodyMode) p.jsonBodyMode = 'fields'
      parameters = p
    }
    const node = {
      id,
      type,
      version: 1,
      position,
      parameters,
      settings: {},
    }
    get().pushHistory()
    set({
      nodes: [...nodes, { id, type: 'custom', position, data: { node } }],
    })
    scheduleSave()
    return id
  },

  insertNodeOnEdge(edgeId, type) {
    const { nodes, edges, addNode } = get()
    const edge = edges.find((e) => e.id === edgeId)
    if (!edge) return null

    const sourceNode = nodes.find((n) => n.id === edge.source)
    const targetNode = nodes.find((n) => n.id === edge.target)
    if (!sourceNode || !targetNode) return null

    // Calculate midpoint between source and target
    const sPos = sourceNode.position || { x: 0, y: 0 }
    const tPos = targetNode.position || { x: 0, y: 0 }
    const midX = Math.round((sPos.x + tPos.x) / 2)
    const midY = Math.round((sPos.y + tPos.y) / 2)

    // Add the new node at the midpoint
    const newNodeId = addNode(type, { x: midX, y: midY })

    // Replace the old edge with two new connecting edges
    const currentEdges = get().edges.filter((e) => e.id !== edgeId)
    const edge1 = {
      id: crypto.randomUUID(),
      source: edge.source,
      sourceHandle: edge.sourceHandle || null,
      target: newNodeId,
      targetHandle: null,
      type: 'exec',
    }
    const edge2 = {
      id: crypto.randomUUID(),
      source: newNodeId,
      sourceHandle: null,
      target: edge.target,
      targetHandle: edge.targetHandle || null,
      type: 'exec',
    }

    get().pushHistory()
    set({ edges: [...currentEdges, edge1, edge2] })
    scheduleSave()

    useUiStore.getState().selectNode(newNodeId)
    return newNodeId
  },

  deleteNodes(ids) {
    if (!ids.length) return
    const doomed = new Set(ids)
    const { nodes, edges } = get()
    get().pushHistory()
    set({
      nodes: nodes.filter((n) => !doomed.has(n.id)),
      edges: edges.filter((e) => !doomed.has(e.source) && !doomed.has(e.target)),
    })
    pruneEmptyGroups(get, set)
    if (useUiStore.getState().selectedNodeId && doomed.has(useUiStore.getState().selectedNodeId)) {
      useUiStore.getState().selectNode(null)
    }
    scheduleSave()
  },

  duplicateNodes(ids) {
    const { nodes, edges, nextNodeId } = get()
    const srcNodes = nodes.filter((n) => ids.includes(n.id))
    if (!srcNodes.length) return
    get().pushHistory()
    const idMap = {}
    const copies = srcNodes.map((n) => {
      const newId = nextNodeId(n.data.node.type)
      idMap[n.id] = newId
      return {
        ...n,
        id: newId,
        selected: true,
        position: { x: n.position.x + 40, y: n.position.y + 40 },
        data: { node: { ...n.data.node, id: newId } },
      }
    })
    const srcIds = new Set(srcNodes.map((n) => n.id))
    const copyEdges = edges
      .filter((e) => srcIds.has(e.source) && srcIds.has(e.target))
      .map((e) => ({
        ...e,
        id: crypto.randomUUID(),
        source: idMap[e.source],
        target: idMap[e.target],
      }))
    set({
      nodes: [...nodes.map((n) => ({ ...n, selected: false })), ...copies],
      edges: [...edges, ...copyEdges],
    })
    useUiStore.getState().selectNode(copies[0].id)
    scheduleSave()
  },

  clearSelection() {
    set({ nodes: get().nodes.map((n) => ({ ...n, selected: false })) })
    useUiStore.getState().selectNode(null)
  },

  updateNode(id, patch) {
    // Consecutive updates of the same shape coalesce into one undo step.
    get().pushHistory(`node:${id}:${Object.keys(patch).join(',')}`)
    set({
      nodes: get().nodes.map((n) =>
        n.id === id
          ? { ...n, data: { node: { ...n.data.node, ...patch } } }
          : n,
      ),
    })
    scheduleSave()
  },

  setName(name) {
    const trimmed = (name || '').slice(0, 255)
    set({ workflow: { ...get().workflow, name: trimmed }, savedAt: null, _dirty: true })
    scheduleSave()
  },

  // ------------------------------------------------------------------
  // clipboard (Phase 12)
  // ------------------------------------------------------------------

  copySelection(ids) {
    const { nodes, edges } = get()
    const chosen = nodes.filter((n) => ids.includes(n.id))
    if (!chosen.length) return
    const origin = chosen.reduce(
      (acc, n) => ({ x: Math.min(acc.x, n.position.x), y: Math.min(acc.y, n.position.y) }),
      { x: Infinity, y: Infinity },
    )
    // Internal edges between copied nodes come along for the ride.
    const chosenIds = new Set(chosen.map((n) => n.id))
    const innerEdges = edges.filter((e) => chosenIds.has(e.source) && chosenIds.has(e.target))
    set({
      clipboard: {
        nodes: chosen.map((n) => ({ ...n.data.node, position: { ...n.position } })),
        edges: innerEdges.map((e) => ({
          source: e.source,
          sourceHandle: e.sourceHandle ?? 'main',
          target: e.target,
          targetHandle: e.targetHandle ?? 'main',
        })),
        origin,
      },
    })
  },

  cutSelection(ids) {
    get().copySelection(ids)
    get().deleteNodes(ids)
  },

  paste(at) {
    const clip = get().clipboard
    if (!clip) return null
    const { nodes, edges, nextNodeId } = get()
    get().pushHistory()

    const base = at || { ...(clip.origin ?? { x: 0, y: 0 }) }
    base.x += 48
    base.y += 48

    const idMap = new Map()
    const copies = clip.nodes.map((raw) => {
      const newId = nextNodeId(raw.type)
      idMap.set(raw.id, newId)
      const dx = raw.position.x - (clip.origin?.x ?? 0)
      const dy = raw.position.y - (clip.origin?.y ?? 0)
      return {
        id: newId,
        type: 'custom',
        position: { x: base.x + dx, y: base.y + dy },
        selected: true,
        data: { node: { ...raw, id: newId } },
      }
    })
    const pastedEdges = (clip.edges ?? [])
      .filter((e) => idMap.has(e.source) && idMap.has(e.target))
      .map((e) => ({
        id: crypto.randomUUID(),
        source: idMap.get(e.source),
        target: idMap.get(e.target),
        sourceHandle: e.sourceHandle ?? 'main',
        targetHandle: e.targetHandle ?? 'main',
      }))
    set({
      nodes: [...nodes.map((n) => ({ ...n, selected: false })), ...copies],
      edges: [...edges, ...pastedEdges],
    })
    if (copies.length) useUiStore.getState().selectNode(copies[0].id)
    scheduleSave()
    return copies.length
  },

  selectAll() {
    set({ nodes: get().nodes.map((n) => ({ ...n, selected: true })) })
  },

  // ------------------------------------------------------------------
  // decorations: comments / groups / edge labels (Phase 12)
  //
  // These are editor-only state persisted through workflow.settings —
  // not graph nodes — so they intentionally bypass undo history.
  // ------------------------------------------------------------------

  addComment(at, text = '') {
    const id = `comment_${crypto.randomUUID().slice(0, 8)}`
    set({
      comments: [
        ...get().comments,
        { id, x: at.x, y: at.y, width: 220, height: 90, text, color: 'amber' },
      ],
    })
    scheduleSave()
    return id
  },

  updateComment(id, patch) {
    set({
      comments: get().comments.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    })
    scheduleSave()
  },

  deleteComment(id) {
    set({ comments: get().comments.filter((c) => c.id !== id) })
    scheduleSave()
  },

  groupSelected(nodeIds = [], label = 'Group Frame', color = 'blue') {
    const { nodes } = get()
    const members = nodes.filter((n) => nodeIds.includes(n.id))
    let minX = 140
    let minY = 140
    let maxX = 460
    let maxY = 320
    if (members.length > 0) {
      minX = Math.min(...members.map((n) => n.position.x)) - 32
      minY = Math.min(...members.map((n) => n.position.y)) - 48
      maxX = Math.max(...members.map((n) => n.position.x + (n.width || 180)))
      maxY = Math.max(...members.map((n) => n.position.y + (n.height || 72)))
    } else {
      const allNodes = nodes.filter((n) => n.type === 'custom')
      if (allNodes.length > 0) {
        minX = Math.min(...allNodes.map((n) => n.position.x)) - 32
        minY = Math.min(...allNodes.map((n) => n.position.y)) - 48
        maxX = minX + 360
        maxY = minY + 220
      }
    }
    const id = `group_${crypto.randomUUID().slice(0, 8)}`
    set({
      groups: [
        ...get().groups,
        {
          id,
          label,
          x: minX,
          y: minY,
          width: Math.max(maxX - minX + 32, 260),
          height: Math.max(maxY - minY + 32, 160),
          color,
        },
      ],
    })
    scheduleSave()
    return id
  },

  updateGroup(id, patch) {
    set({
      groups: get().groups.map((g) => (g.id === id ? { ...g, ...patch } : g)),
    })
    scheduleSave()
  },

  ungroup(id) {
    set({ groups: get().groups.filter((g) => g.id !== id) })
    scheduleSave()
  },

  setEdgeLabel(source, sourceHandle, target, label) {
    const key = edgeKey({ source, sourceHandle, target })
    const next = { ...get().edgeLabels }
    if (label == null || label === '') delete next[key]
    else next[key] = label
    set({ edgeLabels: next })
    scheduleSave()
  },

  /** Current edges with labels applied (React Flow `label` field). */
  labeledEdges() {
    const { edges, edgeLabels } = get()
    if (!Object.keys(edgeLabels).length) return edges
    return edges.map((e) => {
      const label = edgeLabels[edgeKey(e)]
      return label ? { ...e, label } : e
    })
  },

  async toggleActive() {
    const { workflow } = get()
    if (!workflow?.id) return
    const workflowId = workflow.id
    const result = await api.setActive(workflowId, !workflow.active)
    if (get().workflow?.id !== workflowId) return result
    set({ workflow: { ...get().workflow, active: result.active } })
    return result
  },

  async setActive(active) {
    const { workflow } = get()
    if (!workflow?.id) return
    const workflowId = workflow.id
    const result = await api.setActive(workflowId, Boolean(active))
    if (get().workflow?.id !== workflowId) return result
    set({ workflow: { ...get().workflow, active: result.active } })
    return result
  },

  async togglePinned() {
    const { workflow } = get()
    if (!workflow?.id) return
    const workflowId = workflow.id
    const currentPinned = Boolean(workflow.pinned || workflow.settings?.pinned)
    const nextPinned = !currentPinned
    try {
      await api.setPinned(workflowId, nextPinned)
    } catch {
      // fallback
    }
    try {
      const stored = JSON.parse(localStorage.getItem('pinned_workflows') || '[]')
      const s = new Set(Array.isArray(stored) ? stored : [])
      if (nextPinned) s.add(workflowId); else s.delete(workflowId)
      localStorage.setItem('pinned_workflows', JSON.stringify([...s]))
    } catch (err) { console.error('[flowsmith] stores/workflowStore.js', err) }
    if (get().workflow?.id !== workflowId) return
    const current = get().workflow
    const settings = { ...(current.settings || {}), pinned: nextPinned }
    set({ workflow: { ...current, pinned: nextPinned, settings } })
  },

  setWorkflowSettings(patch) {
    const { workflow } = get()
    if (!workflow) return
    set({
      workflow: { ...workflow, settings: { ...(workflow.settings || {}), ...patch } },
      savedAt: null,
      _dirty: true,
    })
    scheduleSave()
  },

  async save() {
    const { workflow, nodes, edges, comments, groups, edgeLabels } = get()
    if (!workflow) return
    if (get().saving) {
      // A save is already in flight; record dirty state so edits aren't lost
      set({ _dirty: true })
      if (get().autoSave) scheduleSave()
      return null
    }
    clearTimeout(saveTimer)
    const payload = withDecorations(toWorkflowJson(workflow, nodes, edges), {
      comments,
      groups,
      edgeLabels,
    })
    const savedWorkflowId = workflow.id
    const editSeqAtStart = get()._editSeq || 0
    const loadSeqAtStart = loadSeq
    // Consume the dirty flag: any edit made while the request is in flight
    // bumps _editSeq, so completion only clears state if nothing changed
    // underneath us.
    set({ saving: true, error: null })
    try {
      const saved = await api.saveWorkflow(savedWorkflowId, payload)
      // The user may have switched workflows while the save was in flight.
      // Never apply an old workflow's response over the newly loaded one.
      if (loadSeq !== loadSeqAtStart) return saved
      if (get().workflow?.id !== savedWorkflowId) return saved
      const hasNewerEdits = (get()._editSeq || 0) !== editSeqAtStart
      set({
        workflow: saved,
        savedAt: hasNewerEdits ? get().savedAt : new Date(),
        saving: false,
        _dirty: hasNewerEdits,
      })
      if (hasNewerEdits && get().autoSave) scheduleSave()
      return saved
    } catch (err) {
      if (loadSeq === loadSeqAtStart && get().workflow?.id === savedWorkflowId) {
        set({ saving: false, error: err.message, _dirty: true })
      }
      throw err
    }
  },

  applyWorkflowModification(modifiedWorkflowJson) {
    if (!modifiedWorkflowJson) return
    const { workflow } = get()
    get().pushHistory('ai-modify')
    const { nodes, edges } = toReactFlow(modifiedWorkflowJson)
    const decor = readDecorations(modifiedWorkflowJson)
    set({
      workflow: { ...workflow, ...modifiedWorkflowJson },
      nodes,
      edges,
      ...decor,
      canUndo: true,
      canRedo: false,
    })
    scheduleSave()
  },
}))

/** Keep stored group geometry roughly in step while members move. */
function syncGroupBounds(get, set) {
  const groups = get().groups
  if (!groups.length) return
  const nodes = get().nodes
  let changed = false
  const next = groups.map((g) => {
    const members = nodes.filter(
      (n) =>
        n.position.x >= g.x - 4 &&
        n.position.y >= g.y - 4 &&
        n.position.x <= g.x + g.width &&
        n.position.y <= g.y + g.height,
    )
    if (!members.length) return g
    const minX = Math.min(...members.map((n) => n.position.x)) - 28
    const minY = Math.min(...members.map((n) => n.position.y)) - 44
    const maxX = Math.max(...members.map((n) => n.position.x + (n.width || 172)))
    const maxY = Math.max(...members.map((n) => n.position.y + (n.height || 64)))
    const width = Math.max(maxX - minX + 28, 160)
    const height = Math.max(maxY - minY + 28, 120)
    if (
      Math.abs(minX - g.x) > 2 ||
      Math.abs(minY - g.y) > 2 ||
      Math.abs(width - g.width) > 2 ||
      Math.abs(height - g.height) > 2
    ) {
      changed = true
      return { ...g, x: minX, y: minY, width, height }
    }
    return g
  })
  if (changed && set) set({ groups: next })
}

/** Drop groups whose members are all gone. */
function pruneEmptyGroups(get, set) {
  const groups = get().groups
  if (!groups.length) return
  const nodes = get().nodes
  const nextGroups = groups.filter((g) =>
    nodes.some(
      (n) =>
        n.position.x >= g.x &&
        n.position.y >= g.y &&
        n.position.x <= g.x + g.width &&
        n.position.y <= g.y + g.height,
    ),
  )
  if (nextGroups.length !== groups.length) set({ groups: nextGroups })
}

function scheduleSave() {
  const current = useWorkflowStore.getState()
  useWorkflowStore.setState({
    _dirty: true,
    savedAt: null,
    _editSeq: (current._editSeq || 0) + 1,
  })
  clearTimeout(saveTimer)
  // Auto-save is disabled by default: only manual save via Save button or Ctrl+S
  if (!useWorkflowStore.getState().autoSave) {
    return
  }
  saveTimer = setTimeout(() => {
    useWorkflowStore.getState().save().catch((err) => {
      const isEmpty = err?.message?.includes('at least one node')
      if (isEmpty) return
      // Retry once after a short delay on transient failure
      setTimeout(() => {
        if (useWorkflowStore.getState()._dirty) {
          useWorkflowStore.getState().save().catch(() => {})
        }
      }, 2000)
    })
  }, 500)
}

export function resetInit() {
  initPromise = null
}

/** True when there are unsaved canvas changes. */
export function isDirty() {
  return useWorkflowStore.getState()._dirty
}

/** Prompt the user if there are unsaved changes; returns false to cancel. */
export function confirmDiscard() {
  if (!useWorkflowStore.getState()._dirty) return true
  return window.confirm('You have unsaved changes. Discard them?')
}
