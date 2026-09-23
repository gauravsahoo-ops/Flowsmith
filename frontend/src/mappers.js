// React Flow <-> workflow JSON conversion (spec 6 contract).
//
// Editor decorations (comments, groups, edge labels) are NOT workflow
// nodes — the backend rejects unknown node types and the engine must
// never see them. They live in `workflow.settings.editor` (a free-form
// dict the API persists untouched) and are rehydrated into ephemeral
// canvas elements on load.

export const EDITOR_SETTINGS_KEY = 'editor';

export function toReactFlow(workflow) {
  const nodes = (workflow.nodes || []).map((n) => ({
    id: n.id,
    type: 'custom',
    position: n.position || { x: 0, y: 0 },
    data: { node: n },
  }))
  // Node type index to validate/correct handles on branching nodes
  const nodeTypeMap = new Map((workflow.nodes || []).map((n) => [n.id, n.type]))

  // Preserve all connections (cycles and duplicate wires are allowed).
  // Edges need unique ids for React Flow; suffix duplicates with an index.
  const counts = new Map()
  const edges = []
  for (const c of workflow.connections || []) {
    let shandle = c.sourceHandle ?? 'main'
    const thandle = c.targetHandle ?? 'main'

    const srcType = nodeTypeMap.get(c.source)
    if ((srcType === 'if_condition' || srcType === 'if') && shandle === 'main') {
      shandle = 'true'
    } else if ((srcType === 'loop' || srcType === 'loop_over_items') && shandle === 'main') {
      shandle = 'loop'
    } else if (srcType === 'switch' && shandle === 'main') {
      shandle = 'route_0'
    }

    const baseKey = `${c.source}|${shandle}|${c.target}|${thandle}`
    const n = (counts.get(baseKey) || 0)
    counts.set(baseKey, n + 1)
    const id = n === 0
      ? `${c.source}->${c.target}->${shandle}`
      : `${c.source}->${c.target}->${shandle}#${n}`
    edges.push({
      id,
      source: c.source,
      sourceHandle: shandle,
      target: c.target,
      targetHandle: thandle,
    })
  }
  return { nodes, edges }
}

// --- editor decorations -------------------------------------------------

/** Read `workflow.settings.editor` decorations defensively. */
export function readDecorations(workflow) {
  const editor = workflow?.settings?.[EDITOR_SETTINGS_KEY] || {}
  return {
    comments: Array.isArray(editor.comments) ? editor.comments : [],
    groups: Array.isArray(editor.groups) ? editor.groups : [],
    edgeLabels:
      editor.edgeLabels && typeof editor.edgeLabels === 'object'
        ? { ...editor.edgeLabels }
        : {},
  }
}

/**
 * Merge current editor decoration state back into a workflow payload's
 * settings. `decor` = {comments, groups, edgeLabels} as stored by the
 * workflowStore (already plain serialisable shapes).
 */
export function withDecorations(workflowPayload, decor) {
  const settings = { ...(workflowPayload.settings || {}) }
  const editor = {
    comments: decor.comments,
    groups: decor.groups,
    edgeLabels: decor.edgeLabels,
  }
  const empty =
    !editor.comments.length &&
    !editor.groups.length &&
    Object.keys(editor.edgeLabels).length === 0
  if (empty) delete settings[EDITOR_SETTINGS_KEY]
  else settings[EDITOR_SETTINGS_KEY] = editor
  return { ...workflowPayload, settings }
}

export function toWorkflowJson(workflow, nodes, edges) {
  return {
    ...workflow,
    nodes: nodes.map((n) => {
      const node = n.data?.node || {}
      const out = {
        id: n.id,
        type: node.type ?? n.type,
        position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
        parameters: node.parameters || n.parameters || {},
        settings: node.settings || n.settings || {},
      }
      if (node.credentials) out.credentials = node.credentials
      if (node.version) out.version = node.version
      return out
    }),
    connections: edges.map((e) => ({
      source: e.source,
      sourceHandle: e.sourceHandle ?? 'main',
      target: e.target,
      targetHandle: e.targetHandle ?? 'main',
    })),
  }
}

// Human-approval decision stamp (Phase 36/40): execution.results.approval.
export function formatApprovalStamp(stamp) {
  if (!stamp) return ''
  const who = `user #${stamp.approved_by ?? '?'}`
  const verb = stamp.approved === false ? 'Rejected' : stamp.approved === true ? 'Approved' : 'Decision'
  const when = stamp.approved_at ? ` · ${new Date(stamp.approved_at).toLocaleString()}` : ''
  return `${verb} by ${who}${when}`
}
