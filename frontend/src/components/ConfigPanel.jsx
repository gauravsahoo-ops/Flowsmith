import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import { useCredentialStore } from '../stores/credentialStore'
import ExpressionHelper from './ExpressionHelper'
import JsonForm from './JsonForm'
import SalesforceDiscovery from './SalesforceDiscovery'
import DataTableDiscovery from './DataTableDiscovery'
import {
  IDEMPOTENCY_LABEL,
  IDEMPOTENCY_HINT,
  NODE_COLORS,
} from '../utils/nodeConstants'
import { CollapsibleSection, OpSafetyHint } from './shared/CollapsibleSection'
import { NodeIcon } from './NodeIcons'

const VERSION_LABEL = 'Version'

// Phase 16: AI-assisted node configuration. Suggestions are validated
// server-side against the node's real schema, shown as EDITABLE JSON,
// and only applied as a normal local edit on explicit user action.
function AiConfigAssist({ node, updateNode }) {
  const [intent, setIntent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [suggestion, setSuggestion] = useState(null) // {text, ok, issues, explanation}
  const [applying, setApplying] = useState(false)

  async function suggest() {
    if (!intent.trim() || busy) return
    setBusy(true)
    setError(null)
    setSuggestion(null)
    try {
      const operation = node.parameters?.operation || null
      const data = await api.suggestNodeConfig({
        node_type: node.type,
        operation,
        intent: intent.trim(),
      })
      setSuggestion({
        text: JSON.stringify(data.parameters ?? {}, null, 2),
        ok: Boolean(data.ok),
        issues: data.issues || [],
        explanation: data.explanation || '',
      })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function apply() {
    if (!suggestion) return
    let parsed
    try {
      parsed = JSON.parse(suggestion.text)
    } catch (err) {
      setError(`Invalid JSON: ${err.message}`)
      return
    }
    setApplying(true)
    try {
      // Normal local edit — persisted only via the usual Save flow.
      updateNode(node.id, { parameters: parsed })
      setSuggestion(null)
      setIntent('')
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="ai-assist">
      <label>
        What should this node do?
        <textarea
          rows={2}
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
          placeholder="e.g. search for the lead by email and return its id"
        />
      </label>
      <button className="ghost" disabled={busy || !intent.trim()} onClick={suggest}>
        {busy ? 'Thinking…' : '🤖 Suggest parameters'}
      </button>
      {error && <p className="banner-inline err">{error}</p>}
      {suggestion && (
        <div className="ai-suggestion">
          <span className={`gen-verdict ${suggestion.ok ? 'ok' : 'err'}`}>
            {suggestion.ok ? '✓ validated' : '✗ has issues'}
          </span>
          {suggestion.explanation && <p className="hint">{suggestion.explanation}</p>}
          {suggestion.issues.map((i, idx) => (
            <p key={idx} className={`banner-inline ${i.severity === 'error' ? 'err' : 'info'}`}>
              {i.code}: {i.message}
            </p>
          ))}
          <textarea
            className="ai-json"
            rows={8}
            spellCheck="false"
            value={suggestion.text}
            onChange={(e) => setSuggestion({ ...suggestion, text: e.target.value })}
          />
          <p className="hint">Edit freely — applying is a normal edit; save the workflow to persist.</p>
          <div className="ai-actions">
            <button className="primary" disabled={applying} onClick={apply}>Apply</button>
            <button className="ghost" onClick={() => setSuggestion(null)}>Discard</button>
          </div>
        </div>
      )}
    </div>
  )
}



export default function ConfigPanel() {
  const selectedId = useUiStore((s) => s.selectedNodeId)
  const nodeEditorOpen = useUiStore((s) => s.nodeEditorOpen)
  const nodes = useWorkflowStore((s) => s.nodes)
  const catalog = useWorkflowStore((s) => s.catalog)
  const workflow = useWorkflowStore((s) => s.workflow)
  const versions = useWorkflowStore((s) => s.versions)
  const updateNode = useWorkflowStore((s) => s.updateNode)
  const deleteNodes = useWorkflowStore((s) => s.deleteNodes)
  const duplicateNodes = useWorkflowStore((s) => s.duplicateNodes)
  const rollbackVersion = useWorkflowStore((s) => s.rollbackVersion)
  const credentials = useCredentialStore((s) => s.credentials)

  const [mapping, setMapping] = useState([])
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Load upstream fields whenever the selected node changes (Phase 5).
  useEffect(() => {
    setMapping([])
    if (!workflow?.id || !selectedId) return
    let alive = true
    api
      .upstreamFields(workflow.id, selectedId)
      .then((data) => {
        if (!alive) return
        setMapping(data.fields || [])
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [workflow?.id, selectedId])

  async function previewExpression(expression) {
    const data = await api.previewExpression(workflow.id, {
      expression,
      node_id: selectedId,
    })
    return data
  }

  const flowNode = nodes.find((n) => n.id === selectedId)
  const node = flowNode?.data?.node
  const meta = useMemo(
    () => (node ? catalog.find((n) => n.type === node.type) : null),
    [catalog, node],
  )
  const schema = meta?.parameters_schema
  const credTypes = meta?.credential_types || []

  // Hide when the node editor modal is open (replaced by centered modal)
  if (nodeEditorOpen) return null

  if (!flowNode || !node) {
    return (
      <aside className="panel">
        <h2>Config</h2>
      {workflow?.id && <ExpressionHelper workflowId={workflow.id} />}
        <p className="hint">Select a node to configure it.</p>
      </aside>
    )
  }

  function setSetting(key, value) {
    updateNode(node.id, { settings: { ...(node.settings || {}), [key]: value } })
  }

  function setCredential(type, id) {
    const credentials = { ...(node.credentials || {}) }
    if (id) credentials[type] = id
    else delete credentials[type]
    updateNode(node.id, { credentials })
  }

  const handleParamsChange = (newParams) => {
    updateNode(node.id, { parameters: newParams })
  }

  return (
    <aside className="panel">
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <NodeIcon type={node.type} icon={node.settings?.icon || meta?.icon} size={22} />
        <span>{(node.settings || {}).label || meta?.display_name || node.type}</span>
      </h2>
      <div className="node-id">{node.id} · {node.type}</div>

      {meta?.idempotency && (
        <p className={`hint idempotency idem-${meta.idempotency}`} title={IDEMPOTENCY_HINT[meta.idempotency]}>
          {IDEMPOTENCY_LABEL[meta.idempotency] || meta.idempotency}
        </p>
      )}
      {node.type === 'salesforce' && meta?.operations && (
        <OpSafetyHint operation={(node.parameters || {}).operation} operations={meta.operations} />
      )}
      {workflow && (
        <p className="hint" style={{ marginBottom: 8, fontSize: 12 }}>
          {VERSION_LABEL}: {workflow.version || '—'}
        </p>
      )}
      {versions && versions.length > 1 && (
        <div style={{ marginBottom: 8, fontSize: 12 }}>
          {VERSION_LABEL} history: {versions
            .slice(0, 3)
            .map((v) => `${v.version} (` + new Date(v.updated_at).toLocaleDateString() + `)`)
            .join(' • ')}
          {versions.length > 3 && `+${versions.length - 3} more`}
        </div>
      )}
      {workflow && versions && versions.length > 1 && (
        <button
          className="ghost"
          onClick={() => {
            const version = window.prompt('Enter version number to rollback to:', versions[0]?.version || '')
            if (version) {
              rollbackVersion(workflow.id, Number(version)).catch((err) => window.alert(err.message))
            }
          }}
          title="Rollback to selected version"
        >
          ↻ Rollback
        </button>
      )}

      <CollapsibleSection title="Parameters" defaultOpen>
        {node.type === 'salesforce' && (
          <SalesforceDiscovery
            node={node}
            onParamsChange={handleParamsChange}
          />
        )}
        {node.type === 'data_table' && (
          <DataTableDiscovery node={node} onParamsChange={handleParamsChange} />
        )}
        {schema ? (
          <JsonForm
            schema={schema}
            value={node.parameters || {}}
            onChange={handleParamsChange}
            mapping={mapping}
            onPreview={previewExpression}
          />
        ) : (
          <p className="hint">No parameters defined for this node.</p>
        )}

        {node.type === 'webhook' && (
          <>
            <h3>Public URL</h3>
            <p className="hint">Call this URL to start the workflow (no auth). Must be active.</p>
            <input
              readOnly
              value={`${window.location.origin}/api/webhooks/${node.parameters?.path || ''}`}
              onFocus={(e) => e.target.select()}
            />
          </>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="Appearance" defaultOpen={false}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
          <label style={{ width: 80 }}>
            Icon
            <input
              value={(node.settings || {}).icon || ''}
              placeholder={meta?.icon || '🌐'}
              maxLength={6}
              onChange={(e) => setSetting('icon', e.target.value)}
              style={{ textAlign: 'center', fontSize: 18 }}
              title="Custom icon or emoji for this node"
            />
          </label>
          <label style={{ flex: 1 }}>
            Custom label
            <input
              value={(node.settings || {}).label || ''}
              placeholder={meta?.display_name || node.type}
              onChange={(e) => setSetting('label', e.target.value)}
            />
          </label>
        </div>
        <label>
          Colour
          <select
            value={(node.settings || {}).color || ''}
            onChange={(e) => setSetting('color', e.target.value)}
          >
            {NODE_COLORS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      </CollapsibleSection>

      <CollapsibleSection title="Credential" defaultOpen={false} badge={credTypes.length || ''}>
        {credTypes.length === 0 ? (
          <p className="hint">This node needs no credentials.</p>
        ) : (
          <>
            {credTypes.map((type) => {
              const options = credentials.filter((c) => c.type === type)
              const value = node.credentials?.[type] || ''
              return (
                <label key={type}>
                  {type}
                  <select value={value} onChange={(e) => setCredential(type, e.target.value)}>
                    <option value="">None</option>
                    {options.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>
              )
            })}
            {credentials.length === 0 && (
              <p className="hint">No credentials stored yet — open Credentials in the sidebar.</p>
            )}
          </>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="Execution" defaultOpen={false}>
        <label className="check">
          <input
            type="checkbox"
            checked={Boolean(node.settings?.continue_on_error)}
            onChange={(e) => setSetting('continue_on_error', e.target.checked)}
          />
          Continue on error
        </label>
      <label>
        Timeout (seconds)
        <input
          type="number"
          min={0}
          value={node.settings?.timeout_seconds ?? 0}
          onChange={(e) => setSetting('timeout_seconds', Number(e.target.value))}
        />
      </label>
      <label>
        Retries (extra attempts after a transient failure)
        <input
          type="number"
          min={0}
          max={10}
          value={node.settings?.retry_max_attempts ?? 0}
          onChange={(e) => setSetting('retry_max_attempts', Number(e.target.value) || 0)}
        />
      </label>
      <label>
        Retry backoff (seconds, doubles each attempt)
        <input
          type="number"
          min={0}
          value={node.settings?.retry_backoff_seconds ?? 2}
          onChange={(e) => setSetting('retry_backoff_seconds', Number(e.target.value) || 0)}
        />
      </label>

        {Number(node.settings?.retry_max_attempts ?? 0) > 0 && meta?.idempotency && (
          <p className={`hint ${meta.idempotency === 'idempotent' ? '' : 'retry-risky'}`}>
            {meta.idempotency === 'idempotent' &&
              'Retries are safe: this node is idempotent. Only transient errors (network, timeouts) retry — never invalid params or credentials.'}
            {meta.idempotency === 'conditionally_idempotent' &&
              'Retries only duplicate side effects for non-read-only runs (POST/PATCH, INSERT/UPDATE/DELETE).'}
            {meta.idempotency === 'non_idempotent' &&
              'This node is not idempotent — retries may duplicate side effects (emails sent, model calls billed, rows written).'}
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="✨ AI assist" defaultOpen={false}>
        <AiConfigAssist node={node} updateNode={updateNode} />
      </CollapsibleSection>

      <div className="panel-actions">
        <button className="ghost" onClick={() => duplicateNodes([node.id])} title="Duplicate this node (Ctrl+D)">
          ⧉ Duplicate
        </button>
        {!confirmDelete ? (
          <button className="danger" onClick={() => setConfirmDelete(true)} title="Delete this node">
            Delete
          </button>
        ) : (
          <div className="nem-confirm-delete">
            <span className="hint">Delete?</span>
            <button className="danger" onClick={() => { deleteNodes([node.id]) }}>
              Yes
            </button>
            <button className="ghost" onClick={() => setConfirmDelete(false)}>
              No
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}