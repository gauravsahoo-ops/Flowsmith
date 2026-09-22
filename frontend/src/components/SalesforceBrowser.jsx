import { useEffect, useMemo, useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import { getToken } from '../api'

const CURATED_LABELS = {
  create: { label: 'Create', hint: 'Create a record' },
  upsert: { label: 'Create or Update', hint: 'Create a new record, or update the current one if it already exists (upsert)' },
  delete: { label: 'Delete', hint: 'Delete a record' },
  get: { label: 'Get', hint: 'Get a record' },
  query: { label: 'Get Many', hint: 'Get many records' },
  describe: { label: 'Get Summary', hint: "Returns an overview of the object's metadata" },
  update: { label: 'Update', hint: 'Update a record' },
  custom_api_call: { label: 'Custom API Call', hint: 'Make a custom API call' },
  flow_invoke: { label: 'Invoke Flow', hint: 'Invoke an autolaunched Flow' },
  search: { label: 'Search', hint: 'Search records' },
  list: { label: 'List Objects', hint: 'List all objects' },
  bulk: { label: 'Bulk', hint: 'Bulk load' },
  add_note: { label: 'Add Note', hint: 'Add note to an account' },
}

export default function SalesforceBrowser({ onClose }) {
  const [search, setSearch] = useState('')
  const [triggersOpen, setTriggersOpen] = useState(true)
  const [actionsOpen, setActionsOpen] = useState(true)
  const [expandedCats, setExpandedCats] = useState(() => new Set(['Account Actions']))
  const [opsData, setOpsData] = useState(null)
  const [triggersData, setTriggersData] = useState(null)
  const [matrix, setMatrix] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setLoading(true)
    const headers = { Authorization: `Bearer ${getToken()}` }
    Promise.all([
      fetch('/api/connectors/salesforce', { headers }).then(r => r.json()).then(j => j.data).catch(() => null),
      fetch('/api/connectors/salesforce/resources', { headers }).then(r => r.json()).then(j => j.data).catch(() => null),
    ]).then(([connRes, resMatrix]) => {
      if (!alive) return
      if (connRes?.operations) setOpsData(connRes.operations)
      if (connRes?.triggers) setTriggersData(connRes.triggers)
      if (resMatrix?.resources) {
        setMatrix(resMatrix.resources)
        if (resMatrix.labels) setLabels(resMatrix.labels)
        // expand first few resources by default
        const first = Object.keys(resMatrix.resources)[0]
        if (first) setExpandedCats(new Set([`${first} Actions`]))
      }
      // Fallback: try direct ops endpoint
      if (!connRes?.operations) {
        fetch('/api/connectors/salesforce/operations', { headers }).then(r => r.json()).then(j => {
          if (j.data?.operations) setOpsData(j.data.operations)
        }).catch(() => {})
      }
      setLoading(false)
    }).catch(e => {
      if (!alive) return
      setError(e.message || 'Failed to load')
      setLoading(false)
    })
    return () => { alive = false }
  }, [])

  const filteredTriggers = useMemo(() => {
    if (!triggersData) return {}
    const q = search.trim().toLowerCase()
    if (!q) return triggersData
    const out = {}
    for (const [k, v] of Object.entries(triggersData)) {
      const hay = `${k} ${v.display_name || ''} ${v.description || ''} ${v.trigger_type || ''}`.toLowerCase()
      if (hay.includes(q)) out[k] = v
    }
    return out
  }, [triggersData, search])

  const filteredOpsGroups = useMemo(() => {
    if (matrix) {
      // Build per-resource groups from single source matrix
      const groups = {}
      for (const [resource, ops] of Object.entries(matrix)) {
        const list = []
        // For Account, inject Add Note as alias to create (UI-only, backend maps to create Note)
        const opsWithAlias = resource === 'Account' && ops.includes('create') && !ops.includes('add_note')
          ? ['add_note', ...ops]
          : ops
        for (const backendOp of opsWithAlias) {
          // Map backend id to curated label (or fallback to opsData display)
          let display = backendOp
          let desc = ''
          let hint = ''
          if (backendOp === 'add_note') {
            display = 'Add Note'
            desc = 'Add note to an account'
            hint = desc
          } else if (CURATED_LABELS[backendOp]) {
            display = CURATED_LABELS[backendOp].label
            // Make hint resource-specific
            if (backendOp === 'create') hint = `Create a ${resource === 'CustomObject' ? 'custom record' : resource}`
            else if (backendOp === 'query') hint = `Get many ${resource}s`
            else if (backendOp === 'describe') hint = `Returns an overview of ${resource}'s metadata`
            else hint = CURATED_LABELS[backendOp].hint
            desc = hint
            // For Get Many vs query distinction, keep label as Get Many
            if (backendOp === 'query') display = 'Get Many'
            if (backendOp === 'describe') display = 'Get Summary'
            if (backendOp === 'upsert') display = 'Create or Update'
            if (backendOp === 'custom_api_call') display = 'Custom API Call'
            if (backendOp === 'flow_invoke') display = 'Invoke Flow'
          } else {
            // fallback to opsData
            const meta = opsData?.[backendOp]
            if (meta) {
              display = meta.display_name || backendOp
              desc = meta.description || ''
            } else {
              display = backendOp
            }
          }
          const key = backendOp === 'add_note' ? 'add_note' : backendOp
          list.push({ key, display_name: display, description: desc, hint, backendOp })
        }
        // Filter by search
        const q = search.trim().toLowerCase()
        const filtered = q ? list.filter(op => `${op.key} ${op.display_name} ${op.description} ${resource}`.toLowerCase().includes(q)) : list
        if (filtered.length) groups[`${resource} Actions`] = filtered
      }
      return groups
    }
    if (!opsData) return {}
    // Fallback: generic grouping
    const CATEGORY_MAP = { search: 'Record', get: 'Record', create: 'Record', update: 'Record', upsert: 'Record', delete: 'Record', query: 'Query', describe: 'Discovery', list: 'Discovery', bulk: 'Bulk', custom_api_call: 'Custom', flow_invoke: 'Flow' }
    const groups = {}
    for (const [key, op] of Object.entries(opsData)) {
      const cat = CATEGORY_MAP[key] || 'Other'
      const label = `${cat} Actions`
      ;(groups[label] ||= []).push({ key, display_name: op.display_name || key, description: op.description || '', backendOp: key })
    }
    if (!search.trim()) return groups
    const q = search.trim().toLowerCase()
    const out = {}
    for (const [cat, list] of Object.entries(groups)) {
      const filtered = list.filter(op => `${op.key} ${op.display_name} ${op.description} ${cat}`.toLowerCase().includes(q))
      if (filtered.length) out[cat] = filtered
    }
    return out
  }, [opsData, matrix, search])

  const triggerCount = triggersData ? Object.keys(triggersData).length : 0
  // For header when not searching, show total unique backend ops or matrix total
  const totalActionCount = useMemo(() => {
    if (matrix) return Object.values(matrix).reduce((s, arr) => s + arr.length, 0) + (matrix.Account?.includes('create') ? 1 : 0) // + Add Note
    if (opsData) return Object.keys(opsData).length
    return 0
  }, [matrix, opsData])
  const filteredTriggerCount = Object.keys(filteredTriggers).length
  const filteredActionCount = Object.values(filteredOpsGroups).reduce((s, arr) => s + arr.length, 0)

  const handleSelectTrigger = () => {
    const addNode = useWorkflowStore.getState().addNode
    const openEditor = useUiStore.getState().openNodeEditor
    const id = addNode('salesforce_trigger', { x: 200 + Math.random()*100, y: 200 + Math.random()*100 })
    if (id) openEditor(id)
    onClose?.()
  }

  const handleSelectAction = (op) => {
    const addNode = useWorkflowStore.getState().addNode
    const openEditor = useUiStore.getState().openNodeEditor
    const updateNode = useWorkflowStore.getState().updateNode
    // op is {key, display_name, backendOp} where key is backend id or alias
    // Derive resource from category: "Account Actions" → "Account"
    // Find which category this op belongs to to get resource
    let resource = 'Account'
    for (const [cat, list] of Object.entries(filteredOpsGroups)) {
      if (list.includes(op)) {
        resource = cat.replace(' Actions', '')
        break
      }
    }
    const id = addNode('salesforce', { x: 300 + Math.random()*100, y: 200 + Math.random()*100 })
    if (id) {
      let backendOp = op.backendOp || op.key
      // Map curated aliases to backend
      if (backendOp === 'add_note') backendOp = 'create'
      // For CustomApiCall resource, operation is custom_api_call regardless of label
      // For Flow, operation is flow_invoke
      const params = { operation: op.key, resource, object_name: resource === 'CustomObject' ? '' : resource === 'CustomApiCall' ? '' : resource === 'Search' ? '' : resource, backendOp }
      // Special handling per curated operation
      if (op.key === 'add_note') {
        params.operation = 'add_note'
        params.resource = 'Account'
        params.object_name = 'Note'
        params.record = { ParentId: '', Title: '', Body: '' }
      } else if (op.key === 'custom_api_call') {
        params.operation = 'custom_api_call'
        params.custom_api_url = '/services/data/v63.0/sobjects/Account'
        params.custom_api_method = 'GET'
        if (resource === 'Flow') {
          params.operation = 'flow_invoke'
          params.flow_api_name = ''
        }
      } else if (op.key === 'query' || op.display_name === 'Get Many') {
        params.operation = 'query'
        const soqlFields = resource === 'Account' ? 'Id, Name, Type, LastModifiedDate' : 'Id, Name'
        // Unlimited — no LIMIT, paginated via max_pages (100)
        params.soql = `SELECT ${soqlFields} FROM ${resource === 'CustomObject' ? 'My_Object__c' : resource}`
        params.max_pages = 100
        // normalize to curated alias for editor
        if (resource === 'Account') params.operation = 'get_many'
      } else if (op.key === 'describe' || op.display_name === 'Get Summary') {
        params.operation = 'describe'
        params.object_name = resource === 'CustomObject' ? '' : resource
      } else if (op.key === 'search') {
        params.operation = 'search'
        params.search_field = 'Email'
        params.search_value = ''
      } else {
        // generic CRUD
        params.operation = backendOp
        // Map curated editor values: get_many etc. for Account
        if (resource === 'Account' && backendOp === 'query') params.operation = 'get_many'
        if (resource === 'Account' && backendOp === 'describe') params.operation = 'describe'
      }
      // Ensure resource is stored for validation
      params.resource = resource
      updateNode(id, { parameters: params })
      openEditor(id)
    }
    onClose?.()
  }

  const toggleCat = (cat) => {
    setExpandedCats(prev => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  return (
    <div className="sf-browser">
      <div className="sf-browser-header">
        <button className="ghost" onClick={onClose} aria-label="Back">←</button>
        <span className="sf-browser-title">Salesforce</span>
        <span className="sf-browser-subtitle">☁️</span>
      </div>

      <div className="sf-browser-search">
        <span className="sf-search-icon">🔍</span>
        <input
          autoFocus
          placeholder="Search Salesforce Actions..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => { if (e.key === 'Escape') setSearch('') }}
          aria-label="Search Salesforce Actions"
        />
        {search && (
          <button className="ghost small" onClick={() => setSearch('')} aria-label="Clear search">✕</button>
        )}
      </div>

      {loading && <div className="hint" style={{ padding: '12px' }}>Loading Salesforce operations…</div>}
      {error && <div className="banner-inline err">{error}</div>}

      {!loading && (
        <>
          <div className="sf-section">
            <button className="sf-section-head" onClick={() => setTriggersOpen(v => !v)} aria-expanded={triggersOpen}>
              <span className="sf-caret">{triggersOpen ? '▾' : '▸'}</span>
              Triggers ({search ? filteredTriggerCount : triggerCount})
            </button>
            {triggersOpen && (
              <div className="sf-section-body">
                {Object.keys(filteredTriggers).length === 0 ? (
                  <div className="hint" style={{ padding: '8px 12px', fontSize: 12 }}>
                    {search ? 'No triggers match your search' : 'No triggers available'}
                  </div>
                ) : (
                  Object.entries(filteredTriggers).map(([key, trig]) => (
                    <button
                      key={key}
                      className="sf-op-item"
                      onClick={() => handleSelectTrigger(key)}
                      title={trig.description || trig.trigger_key}
                    >
                      <span className="sf-op-icon">☁️</span>
                      <span className="sf-op-name">{trig.display_name || trig.trigger_key || key}</span>
                      <span className="sf-op-type">{trig.trigger_type || 'webhook'}</span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>

          <div className="sf-section">
            <button className="sf-section-head" onClick={() => setActionsOpen(v => !v)} aria-expanded={actionsOpen}>
              <span className="sf-caret">{actionsOpen ? '▾' : '▸'}</span>
              Actions ({search ? filteredActionCount : totalActionCount})
            </button>
            {actionsOpen && (
              <div className="sf-section-body">
                {Object.keys(filteredOpsGroups).length === 0 ? (
                  <div className="hint" style={{ padding: '12px', textAlign: 'center' }}>No Salesforce actions found</div>
                ) : (
                  Object.entries(filteredOpsGroups).map(([cat, ops]) => (
                    <div key={cat} className="sf-category">
                      <button className="sf-category-head" onClick={() => toggleCat(cat)} aria-expanded={expandedCats.has(cat)}>
                        <span className="sf-caret">{expandedCats.has(cat) ? '▾' : '▸'}</span>
                        {cat} ({ops.length})
                      </button>
                      {expandedCats.has(cat) && (
                        <div className="sf-category-body">
                          {ops.map(op => (
                            <button
                              key={`${cat}-${op.key}-${op.display_name}`}
                              className="sf-op-item"
                              onClick={() => handleSelectAction(op)}
                              title={op.description}
                            >
                              <span className="sf-op-icon">☁️</span>
                              <span className="sf-op-name">{op.display_name}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
