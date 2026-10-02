import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import EmptyState from '../components/shared/EmptyState'

const TYPE_OPTIONS = ['string', 'number', 'boolean', 'date', 'datetime', 'json']

function ColumnManager({ table, onChanged }) {
  const [cols, setCols] = useState(table.columns || [])
  const [editing, setEditing] = useState(null) // col id being edited
  const [newCol, setNewCol] = useState({ name: '', type: 'string', required: false, default_value: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { setCols(table.columns || []) }, [table])

  const handleAdd = async (e) => {
    e.preventDefault()
    if (!newCol.name.trim()) return
    setBusy(true); setError(null)
    try {
      await api.createDataTableColumn(table.id, { name: newCol.name.trim(), type: newCol.type, required: newCol.required, default_value: newCol.default_value || null })
      setNewCol({ name: '', type: 'string', required: false, default_value: '' })
      onChanged()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  const handleUpdate = async (col, patch) => {
    setBusy(true); setError(null)
    try {
      await api.updateDataTableColumn(table.id, col.id, patch)
      setEditing(null)
      onChanged()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  const handleDelete = async (col) => {
    if (!window.confirm(`Delete column “${col.name}”? This will remove its data from all rows.`)) return
    setBusy(true); setError(null)
    try {
      await api.deleteDataTableColumn(table.id, col.id)
      onChanged()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  const handleReorder = async (from, to) => {
    if (from === to) return
    const reordered = [...cols]
    const [moved] = reordered.splice(from, 1)
    reordered.splice(to, 0, moved)
    const order = reordered.map(c => c.id)
    setCols(reordered)
    try {
      await api.reorderDataTableColumns(table.id, order)
      onChanged()
    } catch (err) { setError(err.message) }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h3 style={{ margin: '0 0 8px' }}>Columns</h3>
      {error && <div className="banner-inline err">{error}</div>}
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>#</th><th>Name</th><th>Type</th><th>Required</th><th>Default</th><th>Actions</th></tr></thead>
          <tbody>
            {cols.map((col, idx) => (
              <tr key={col.id}>
                <td>{idx + 1}</td>
                <td>
                  {editing === col.id ? (
                    <input defaultValue={col.name} id={`edit-name-${col.id}`} />
                  ) : <strong>{col.name}</strong>}
                </td>
                <td><span className="badge badge-muted">{col.type}</span></td>
                <td>{col.required ? 'Yes' : 'No'}</td>
                <td className="muted" style={{ fontSize: 11 }}>{col.default_value || '—'}</td>
                <td>
                  <div className="row-actions">
                    {editing === col.id ? (
                      <>
                        <button className="ghost small" disabled={busy} onClick={() => {
                          const inp = document.getElementById(`edit-name-${col.id}`)
                          handleUpdate(col, { name: inp.value })
                        }}>Save</button>
                        <button className="ghost small" onClick={() => setEditing(null)}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button className="ghost small" onClick={() => setEditing(col.id)}>Edit</button>
                        <button className="ghost small" onClick={() => handleDelete(col)} title="Delete column" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          </svg>
                        </button>
                        <button className="ghost small" disabled={idx === 0} onClick={() => handleReorder(idx, idx - 1)}>↑</button>
                        <button className="ghost small" disabled={idx === cols.length - 1} onClick={() => handleReorder(idx, idx + 1)}>↓</button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form onSubmit={handleAdd} style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap', alignItems: 'end' }}>
        <label>Name<input value={newCol.name} onChange={e => setNewCol({ ...newCol, name: e.target.value })} required maxLength={255} placeholder="email" /></label>
        <label>Type
          <select value={newCol.type} onChange={e => setNewCol({ ...newCol, type: e.target.value })}>
            {TYPE_OPTIONS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="check" style={{ flexDirection: 'row', alignItems: 'center' }}><input type="checkbox" checked={newCol.required} onChange={e => setNewCol({ ...newCol, required: e.target.checked })} /> Required</label>
        <label>Default<input value={newCol.default_value} onChange={e => setNewCol({ ...newCol, default_value: e.target.value })} placeholder="optional" /></label>
        <button className="primary" type="submit" disabled={busy || !newCol.name.trim()}>Add column</button>
      </form>
      <p className="hint" style={{ marginTop: 8 }}>Drag ↑↓ to reorder. Changing a column name updates existing rows atomically.</p>
    </div>
  )
}

function RowEditor({ table, onRowChanged }) {
  const [rows, setRows] = useState([])
  const [meta, setMeta] = useState({ page: 1, pageSize: 25, total: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState('')
  const [sortOrder, setSortOrder] = useState('asc')
  const [filterCol, setFilterCol] = useState('')
  const [filterOp, setFilterOp] = useState('contains')
  const [filterVal, setFilterVal] = useState('')
  const [page, setPage] = useState(1)
  const [editingRow, setEditingRow] = useState(null) // id or 'new'
  const [editData, setEditData] = useState({})
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const filters = filterCol && filterVal ? JSON.stringify([{ column: filterCol, op: filterOp, value: filterVal }]) : undefined
      const { data, meta: m } = await api.listDataTableRows(table.id, { page, pageSize: 25, search: search.trim() || undefined, sort_by: sortBy || undefined, sort_order: sortOrder, filters })
      setRows(data || [])
      if (m) setMeta(m)
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }, [table.id, page, search, sortBy, sortOrder, filterCol, filterOp, filterVal])

  useEffect(() => { load() }, [load])
  useEffect(() => { setPage(1) }, [search, sortBy, sortOrder, filterCol, filterVal])

  const startNew = () => {
    const init = {}
    for (const c of table.columns) {
      if (c.default_value != null) init[c.name] = c.default_value
      else if (c.type === 'boolean') init[c.name] = false
      else if (c.type === 'number') init[c.name] = 0
      else if (c.type === 'json') init[c.name] = {}
      else init[c.name] = ''
    }
    setEditData(init)
    setEditingRow('new')
  }

  const startEdit = (row) => {
    setEditData({ ...row.data })
    setEditingRow(row.id)
  }

  const handleSave = async () => {
    setBusy(true); setError(null)
    try {
      if (editingRow === 'new') {
        await api.createDataTableRow(table.id, editData)
      } else {
        await api.updateDataTableRow(table.id, editingRow, editData)
      }
      setEditingRow(null)
      setEditData({})
      load()
      onRowChanged?.()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const handleDelete = async (row) => {
    if (!window.confirm(`Delete row ${row.id.slice(0,8)}?`)) return
    setBusy(true); setError(null)
    try {
      await api.deleteDataTableRow(table.id, row.id)
      load()
      onRowChanged?.()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const handleBulkDelete = async () => {
    const selected = Array.from(document.querySelectorAll('input.row-check:checked')).map(el => el.dataset.id)
    if (!selected.length) return alert('No rows selected')
    if (!window.confirm(`Delete ${selected.length} rows?`)) return
    setBusy(true); setError(null)
    try {
      await api.bulkDeleteDataTableRows(table.id, selected)
      load()
      onRowChanged?.()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Rows</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="ghost small" onClick={handleBulkDelete} disabled={busy}>Bulk delete</button>
          <button className="primary" onClick={startNew} disabled={busy}>＋ Add row</button>
        </div>
      </div>

      <div className="toolbar" style={{ marginBottom: 12 }}>
        <input className="search-input" placeholder="Search…" value={search} onChange={e => setSearch(e.target.value)} aria-label="Search rows" />
        <select value={sortBy} onChange={e => setSortBy(e.target.value)} aria-label="Sort by">
          <option value="">Sort by created</option>
          {table.columns.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
        </select>
        <select value={sortOrder} onChange={e => setSortOrder(e.target.value)} aria-label="Sort order">
          <option value="asc">Asc</option>
          <option value="desc">Desc</option>
        </select>
        <select value={filterCol} onChange={e => setFilterCol(e.target.value)} aria-label="Filter column">
          <option value="">Filter column</option>
          {table.columns.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
        </select>
        {filterCol && (
          <>
            <select value={filterOp} onChange={e => setFilterOp(e.target.value)}>
              <option value="contains">contains</option>
              <option value="eq">eq</option>
              <option value="ne">ne</option>
              <option value="gt">gt</option>
              <option value="lt">lt</option>
            </select>
            <input placeholder="value" value={filterVal} onChange={e => setFilterVal(e.target.value)} style={{ width: 120 }} />
          </>
        )}
      </div>

      {error && <div className="banner-inline err">{error}</div>}

      {editingRow && (
        <div className="card" style={{ marginBottom: 12, borderColor: 'var(--accent)' }}>
          <h4 style={{ margin: '0 0 8px' }}>{editingRow === 'new' ? 'New row' : `Edit ${editingRow.slice(0,8)}`}</h4>
          <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
            {table.columns.map(col => (
              <label key={col.id}>{col.name} {col.required && <span style={{ color: 'var(--red)' }}>*</span>}
                {col.type === 'boolean' ? (
                  <select value={String(editData[col.name] ?? false)} onChange={e => setEditData({ ...editData, [col.name]: e.target.value === 'true' })}>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : col.type === 'json' ? (
                  <textarea value={typeof editData[col.name] === 'string' ? editData[col.name] : JSON.stringify(editData[col.name] ?? '', null, 2)} onChange={e => {
                    try { setEditData({ ...editData, [col.name]: JSON.parse(e.target.value) }) } catch { setEditData({ ...editData, [col.name]: e.target.value }) }
                  }} rows={2} />
                ) : (
                  <input
                    type={col.type === 'number' ? 'number' : col.type === 'date' ? 'date' : col.type === 'datetime' ? 'datetime-local' : 'text'}
                    value={editData[col.name] ?? ''}
                    onChange={e => setEditData({ ...editData, [col.name]: col.type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value })}
                    placeholder={col.type}
                  />
                )}
              </label>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button className="primary" onClick={handleSave} disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
            <button className="ghost" onClick={() => { setEditingRow(null); setEditData({}) }}>Cancel</button>
          </div>
        </div>
      )}

      {loading ? <LoadingSkeleton rows={5} /> : rows.length === 0 ? (
        <EmptyState icon="database" title="No rows" description={search || filterCol ? "No rows match the current search/filter." : "Add your first row to this table."} />
      ) : (
        <>
          <div className="table-wrap" style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead><tr><th><input type="checkbox" onChange={e => {
                document.querySelectorAll('input.row-check').forEach(el => { el.checked = e.target.checked })
              }} /></th><th>ID</th>{table.columns.map(c => <th key={c.id}>{c.name}<div className="hint" style={{ fontSize: 10 }}>{c.type}</div></th>)}<th>Created</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.map(row => (
                  <tr key={row.id}>
                    <td><input type="checkbox" className="row-check" data-id={row.id} /></td>
                    <td className="muted" style={{ fontSize: 11 }}>{row.id.slice(0,8)}</td>
                    {table.columns.map(col => (
                      <td key={col.id} style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={String(row.data[col.name] ?? '')}>
                        {col.type === 'json' ? (
                          <code style={{ fontSize: 11 }}>{typeof row.data[col.name] === 'object' ? JSON.stringify(row.data[col.name]).slice(0,60) : String(row.data[col.name] ?? '')}</code>
                        ) : col.type === 'boolean' ? (
                          String(row.data[col.name] ?? '')
                        ) : (
                          String(row.data[col.name] ?? '')
                        )}
                      </td>
                    ))}
                    <td className="muted" style={{ fontSize: 11 }}>{row.created_at ? new Date(row.created_at).toLocaleDateString() : '—'}</td>
                    <td>
                      <div className="row-actions">
                        <button className="ghost small" onClick={() => startEdit(row)}>Edit</button>
                        <button className="ghost small" onClick={() => handleDelete(row)} title="Delete row" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
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
          <div className="pagination" style={{ marginTop: 12 }}>
            <button className="ghost" disabled={meta.page <= 1 || loading} onClick={() => setPage(p => Math.max(1, p - 1))}>← Prev</button>
            <span className="hint">Page {meta.page} · {meta.total} total</span>
            <button className="ghost" disabled={meta.page * meta.pageSize >= meta.total || loading} onClick={() => setPage(p => p + 1)}>Next →</button>
          </div>
        </>
      )}
    </div>
  )
}

export default function DataTableEditorPage() {
  const { tableId } = useParams()
  const navigate = useNavigate()
  const [table, setTable] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [editName, setEditName] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const data = await api.getDataTable(tableId)
      setTable(data)
      setEditName(data.name)
      setEditDesc(data.description || '')
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }, [tableId])

  useEffect(() => { load() }, [load])

  const handleSaveMeta = async () => {
    setSaving(true); setError(null)
    try {
      await api.updateDataTable(tableId, { name: editName.trim(), description: editDesc.trim() })
      load()
    } catch (e) { setError(e.message) } finally { setSaving(false) }
  }

  if (loading) return <div className="page"><PageHeader title="Data Table" /><LoadingSkeleton rows={6} /></div>
  if (error) return <div className="page"><PageHeader title="Data Table" /><div className="banner-inline err">{error} <button className="ghost" onClick={() => navigate('/data-tables')}>Back</button></div></div>
  if (!table) return null

  return (
    <div className="page data-table-editor">
      <PageHeader
        title={table.name}
        description={table.description || `${table.columns.length} columns · ${table.row_count ?? 0} rows · ${table.workspace_id.slice(0,8)}`}
        breadcrumbs={[{ label: 'Data Tables', href: '/data-tables' }, { label: table.name }]}
        actions={<button className="ghost" onClick={() => navigate('/data-tables')}>← Back</button>}
      />

      <div className="card" style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'end', flexWrap: 'wrap' }}>
        <label>Table name<input value={editName} onChange={e => setEditName(e.target.value)} maxLength={255} /></label>
        <label>Description<input value={editDesc} onChange={e => setEditDesc(e.target.value)} placeholder="Optional" /></label>
        <button className="primary" onClick={handleSaveMeta} disabled={saving || !editName.trim()}>{saving ? 'Saving…' : 'Save'}</button>
        <span className="hint">ID: {table.id} · Workspace: {table.workspace_id}</span>
      </div>

      {error && <div className="banner-inline err">{error}</div>}

      <ColumnManager table={table} onChanged={load} />

      <RowEditor table={table} onRowChanged={load} />
    </div>
  )
}
