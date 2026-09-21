import { useEffect, useState } from 'react'
import { api } from '../api'

export default function DataTableDiscovery({ node, onParamsChange }) {
  const [workspaces, setWorkspaces] = useState([])
  const [tables, setTables] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selectedWs, setSelectedWs] = useState('')

  useEffect(() => {
    api.listWorkspaces().then(data => {
      setWorkspaces(data || [])
      if (data?.length) setSelectedWs(prev => prev || data[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedWs) return
    setLoading(true)
    api.listDataTables({ workspace_id: selectedWs }).then(res => {
      const data = res.data || res
      setTables(Array.isArray(data) ? data : [])
      setError(null)
    }).catch(e => setError(e.message)).finally(() => setLoading(false))
  }, [selectedWs])

  const currentTableId = node.parameters?.table_id || ''
  const currentTable = tables.find(t => t.id === currentTableId)

  return (
    <div className="sf-connect-box" style={{ marginBottom: 12 }}>
      <h4 style={{ margin: '0 0 6px', fontSize: 12 }}>Data Table</h4>
      <label>Workspace
        <select value={selectedWs} onChange={e => setSelectedWs(e.target.value)}>
          {workspaces.length === 0 && <option value="">No workspaces</option>}
          {workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
      </label>
      <label>Table
        <select value={currentTableId} onChange={e => onParamsChange({ ...node.parameters, table_id: e.target.value })}>
          <option value="">Select a table…</option>
          {tables.map(t => <option key={t.id} value={t.id}>{t.name} ({t.columns?.length ?? 0} cols, {t.row_count ?? 0} rows)</option>)}
        </select>
      </label>
      {loading && <p className="hint">Loading tables…</p>}
      {error && <p className="banner-inline err">{error}</p>}
      {currentTable && (
        <div className="hint" style={{ marginTop: 6 }}>
          Columns: {currentTable.columns.map(c => `${c.name}(${c.type})`).join(', ') || 'none'}
        </div>
      )}
      {!currentTableId && <p className="hint">Select a table or enter table_id manually below.</p>}
      <a href="/data-tables" target="_blank" rel="noreferrer" className="hint" style={{ display: 'block', marginTop: 6 }}>Manage tables →</a>
    </div>
  )
}
