import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import WorkspaceTabs from '../components/shared/WorkspaceTabs'
import ConfirmDialog from '../components/shared/ConfirmDialog'

export default function DataTablesPage() {
  const navigate = useNavigate()
  const [tables, setTables] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState('updated')
  const [workspaces, setWorkspaces] = useState([])
  const [wsId, setWsId] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newWs, setNewWs] = useState('')
  const [creating, setCreating] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const loadWorkspaces = async () => {
    try {
      const data = await api.listWorkspaces()
      setWorkspaces(data || [])
      if (data?.length) {
        setWsId(prev => prev || data[0].id)
        setNewWs(prev => prev || data[0].id)
      }
    } catch {}
  }

  const loadTables = async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await api.listDataTables({ workspace_id: wsId || undefined, search: search.trim() || undefined, page: 1, pageSize: 100 })
      setTables(data || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadWorkspaces() }, [])
  useEffect(() => {
    if (!wsId) return
    const t = setTimeout(() => { loadTables() }, search ? 300 : 0)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, search])

  useEffect(() => {
    if (!showCreate) return
    const onKey = (e) => { if (e.key === 'Escape') setShowCreate(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showCreate])

  const sorted = useMemo(() => {
    const out = [...tables]
    if (sortBy === 'name') out.sort((a, b) => a.name.localeCompare(b.name))
    else if (sortBy === 'created') out.sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    else out.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
    return out
  }, [tables, sortBy])

  const handleCreate = async (e) => {
    e.preventDefault()
    const targetWs = newWs || wsId || (workspaces[0]?.id)
    if (!newName.trim() || !targetWs) return
    setCreating(true)
    try {
      const tbl = await api.createDataTable({ name: newName.trim(), description: newDesc.trim(), workspace_id: targetWs, columns: [] })
      setNewName('')
      setNewDesc('')
      setShowCreate(false)
      navigate(`/data-tables/${tbl.id}`)
    } catch (e) {
      setError(e.message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="page data-tables-page">
      <PageHeader
        title="Data Tables"
        description="Structured storage for your workflows — create tables, define columns, and manage rows."
        actions={<button className="primary" onClick={() => setShowCreate(true)}>＋ Create table</button>}
      />
      <WorkspaceTabs />

      <div className="toolbar">
        <div className="toolbar-left">
          <select value={wsId} onChange={e => { setWsId(e.target.value); setNewWs(e.target.value); }} aria-label="Workspace">
            {workspaces.length === 0 && <option value="">No workspaces</option>}
            {workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <input className="search-input" placeholder="Search tables…" value={search} onChange={e => setSearch(e.target.value)} aria-label="Search tables" />
        </div>
        <div className="toolbar-right">
          <select value={sortBy} onChange={e => setSortBy(e.target.value)} aria-label="Sort by">
            <option value="updated">Sort by updated</option>
            <option value="created">Sort by created</option>
            <option value="name">Sort by name</option>
          </select>
          <button className="ghost" onClick={loadTables} disabled={loading}>↻ Refresh</button>
        </div>
      </div>

      {showCreate && (
        <div className="overlay" onClick={() => setShowCreate(false)}>
          <div className="confirm-dialog" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Create table">
            <h3>Create Data Table</h3>
            <p className="hint" style={{ margin: '0 0 12px' }}>Define structured tables and records for your workflows.</p>
            <form onSubmit={handleCreate} className="cred-form">
              <label>Workspace
                <select value={newWs || wsId} onChange={e => setNewWs(e.target.value)} required>
                  {workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </label>
              <label>Table name
                <input value={newName} onChange={e => setNewName(e.target.value)} required maxLength={255} placeholder="e.g. Customers, Leads, Tickets" autoFocus />
              </label>
              <label>Description (optional)
                <input value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder="e.g. Synced customer list from Salesforce" />
              </label>
              <div className="confirm-actions">
                <button className="ghost" type="button" onClick={() => setShowCreate(false)}>Cancel</button>
                <button className="primary" type="submit" disabled={creating || !newName.trim()}>{creating ? 'Creating…' : 'Create Table'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {error && <div className="banner-inline err">{error}</div>}

      {loading ? <LoadingSkeleton rows={5} /> : sorted.length === 0 ? (
        workspaces.length === 0 ? (
          <EmptyState icon="database" title="No workspaces" description="Create a workspace first to store data tables." />
        ) : search.trim() ? (
          <EmptyState icon="search" title="No matches" description={`No tables match “${search}”.`} action={<button className="ghost" onClick={() => setSearch('')}>Clear search</button>} />
        ) : (
          <EmptyState icon="database" title="No Data Tables yet" description="Create a table to store structured data for your workflows." action={<button className="primary" onClick={() => setShowCreate(true)}>Create table</button>} />
        )
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Table</th><th>Columns</th><th>Rows</th><th>Created</th><th>Updated</th><th>Actions</th></tr></thead>
            <tbody>
              {sorted.map(tbl => (
                <tr key={tbl.id} className="clickable" onClick={() => navigate(`/data-tables/${tbl.id}`)} tabIndex={0} onKeyDown={e => { if (e.key === 'Enter') navigate(`/data-tables/${tbl.id}`)}}>
                  <td>
                    <strong>{tbl.name}</strong>
                    {tbl.description && <div className="hint" style={{ fontSize: 11 }}>{tbl.description.slice(0,80)}</div>}
                    <div className="hint" style={{ fontSize: 11 }}>{tbl.id.slice(0,8)}</div>
                  </td>
                  <td className="hint">{tbl.columns?.length ?? 0} columns</td>
                  <td><span className="badge badge-muted">{tbl.row_count ?? 0} rows</span></td>
                  <td className="muted" style={{ fontSize: 12 }}>{tbl.created_at ? new Date(tbl.created_at).toLocaleDateString() : '—'}</td>
                  <td className="muted" style={{ fontSize: 12 }}>{tbl.updated_at ? new Date(tbl.updated_at).toLocaleDateString() : '—'}</td>
                  <td>
                    <div className="row-actions" onClick={e => e.stopPropagation()}>
                      <button className="ghost small" onClick={() => navigate(`/data-tables/${tbl.id}`)}>Open</button>
                      <button className="ghost small" onClick={() => setDeleteTarget(tbl)} title="Delete table" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={`Delete “${deleteTarget?.name}”?`}
        description="This will delete the table and all its rows and columns. This cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={async () => {
          try {
            await api.deleteDataTable(deleteTarget.id)
            setDeleteTarget(null)
            loadTables()
          } catch (e) { setError(e.message) }
        }}
      />
    </div>
  )
}
