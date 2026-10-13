import { lazy } from 'react'

/**
 * Declarative registry of node editors.
 *
 * Every node type resolves to an editor through this table; anything not listed
 * falls back to the schema-driven `DynamicNodeConfigPanel`, so **every** node in
 * FlowSmith has a configuration panel without adding another branch to the modal.
 *
 * Adding support for a node type is a one-line change here.
 *
 * Each entry may define:
 *   component  – the React component (lazy-loaded)
 *   aliases    – extra node types that share the same editor
 *   props      – optional (node, context) => extra props for that editor
 */

const editors = {
  salesforce: () => import('../components/SalesforceNodeEditor'),
  dynamics_crm: () => import('../components/DynamicsCrmNodeEditor'),
  code: () => import('../components/CodeNodeEditor'),
  if_condition: () => import('../components/IfConditionEditor'),
  filter: () => import('../components/FilterNodeEditor'),
  schedule: () => import('../components/ScheduleTriggerEditor'),
  webhook: () => import('../components/WebhookNodeEditor'),
  http_request: () => import('../components/HttpRequestNodeEditor'),
  set_variable: () => import('../components/SetVariableNodeEditor'),
  split: () => import('../components/SplitNodeEditor'),
  compare_datasets: () => import('../components/CompareDatasetsEditor'),
  stop_and_error: () => import('../components/StopAndErrorNodeEditor'),
  switch: () => import('../components/SwitchNodeEditor'),
  wait: () => import('../components/WaitNodeEditor'),
  sub_workflow: () => import('../components/ExecuteWorkflowNodeEditor'),
  execute_workflow_trigger: () => import('../components/ExecuteWorkflowTriggerEditor'),
  token_manager: () => import('../components/TokenManagerNodeEditor'),
  token_fetch: () => import('../components/TokenFetchNodeEditor'),
  token_store: () => import('../components/TokenStoreNodeEditor'),
  ai: () => import('../components/AINodeEditor'),
  csv: () => import('../components/CsvNodeEditor'),
}

/**
 * Node types that need an *additional* panel rendered above the standard
 * configuration panel, rather than a replacement for it.
 * (`data_table` offers a schema-discovery helper alongside its normal form.)
 */
const prePanels = {
  data_table: () => import('../components/DataTableDiscovery'),
}

/** node type -> canonical registry key. Keep flat: aliases share one component. */
const aliases = {
  // Split editor is shared by the list-manipulation nodes.
  item_lists: 'split',
  // Sub-workflow invocation uses the same editor under both names.
  execute_sub_workflow: 'sub_workflow',
  sub_workflow_trigger: 'execute_workflow_trigger',
  // Auth helpers reuse the token editors.
  auth_fetch: 'token_fetch',
  auth_store: 'token_store',
  // CSV parser node shares the dedicated CSV editor
  csv_parser: 'csv',
}

const resolvedCache = new Map()

/**
 * Resolve the editor for a node type.
 *
 * @param {string} nodeType
 * @returns {{ load: () => Promise<any>, kind: 'dedicated' | 'dynamic' } | null}
 *   `null` when nodeType is falsy. `kind` lets callers render a loading
 *   indicator appropriate to the editor.
 */
export function resolveNodeEditor(nodeType) {
  if (!nodeType) return null
  const key = aliases[nodeType] || nodeType

  const cached = resolvedCache.get(key)
  if (cached) return cached

  const load = editors[key]
  const result = load
    ? { load, kind: 'dedicated' }
    : { load: () => import('../components/parameters/DynamicNodeConfigPanel'), kind: 'dynamic' }

  resolvedCache.set(key, result)
  return result
}

/** True when the node type has a purpose-built editor of its own. */
export function hasDedicatedEditor(nodeType) {
  if (!nodeType) return false
  const key = aliases[nodeType] || nodeType
  return Boolean(editors[key])
}

/** All node types that resolve to a dedicated editor (for tests/tooling). */
export function listDedicatedEditorTypes() {
  return [...Object.keys(editors), ...Object.keys(aliases)]
}

/** Wrap a dynamic import in React.lazy exactly once per resolved editor. */
const lazyCache = new Map()
export function lazyEditor(nodeType) {
  const resolved = resolveNodeEditor(nodeType)
  if (!resolved) return null
  const key = aliases[nodeType] || nodeType
  if (!lazyCache.has(key)) lazyCache.set(key, lazy(resolved.load))
  return lazyCache.get(key)
}
