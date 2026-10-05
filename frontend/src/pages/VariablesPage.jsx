import { useEffect, useState, useCallback } from 'react'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import WorkspaceTabs from '../components/shared/WorkspaceTabs'

export default function VariablesPage() {
  const [workspaces, setWorkspaces] = useState([])
  const [wsId, setWsId] = useState('')
  const [vars, setVars] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [form, setForm] = useState({ key: '', value: '', is_secret: false })
  const [busy, setBusy] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [search, setSearch] = useState('')

  const loadWs = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.listWorkspaces()
      setWorkspaces(data || [])
      if (data?.length) setWsId(prev => prev || data[0].id)
    } catch(e){
      setError(e.message)
    } finally{
      setLoading(false)
    }
  }, [])
  const loadVars = useCallback(async (id) => {
    if (!id) return
    setLoading(true); setError(null)
    try { const data = await api.listEnvVars(id); setVars(data || []) } catch(e){ setError(e.message); setVars([])} finally{ setLoading(false)}
  }, [])

  useEffect(() => { loadWs() }, [loadWs])
  useEffect(() => { if (wsId) loadVars(wsId) }, [wsId, loadVars])

  async function handleSave(e) {
    e.preventDefault()
    if (!form.key.trim() || !wsId) return
    setBusy(true); setError(null); setNotice(null)
    try {
      await api.upsertEnvVar({ workspace_id: wsId, key: form.key.trim().toUpperCase(), value: form.value, is_secret: form.is_secret })
      setNotice(`Saved “${form.key.trim().toUpperCase()}”.`)
      setForm({ key: '', value: '', is_secret: false })
      await loadVars(wsId)
    } catch(err){ setError(err.message)} finally{ setBusy(false)}
  }

  const filtered = vars.filter(v => !search.trim() || v.key.toLowerCase().includes(search.trim().toLowerCase()))

  return (
    <div className="page variables-page">
      <PageHeader title="Variables" description="Workspace environment variables. Use them as {{ $env.KEY }} in any node. Secrets are encrypted and never shown again." />
      <WorkspaceTabs />

      <div className="toolbar">
        <label className="toolbar-select">Workspace
          <select value={wsId} onChange={e => setWsId(e.target.value)} style={{ marginLeft: 8 }}>
            {workspaces.length === 0 && <option value="">No workspaces</option>}
            {workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </label>
        <input className="search-input" placeholder="Search keys…" value={search} onChange={e => setSearch(e.target.value)} aria-label="Search variables" />
      </div>

      {error && <div className="banner-inline err">{error}</div>}
      {notice && <div className="banner-inline ok">{notice}</div>}

      {wsId && (
        <form className="env-form" onSubmit={handleSave} style={{ margin: '16px 0' }}>
          <input placeholder="KEY" value={form.key} onChange={e => setForm({ ...form, key: e.target.value.toUpperCase() })} disabled={busy} required />
          <input placeholder="value" value={form.value} onChange={e => setForm({ ...form, value: e.target.value })} disabled={busy} required />
          <label className="env-secret"><input type="checkbox" checked={form.is_secret} onChange={e => setForm({ ...form, is_secret: e.target.checked })} /> secret</label>
          <button className="primary" type="submit" disabled={busy || !form.key.trim()}>Save</button>
        </form>
      )}

      {loading ? <LoadingSkeleton rows={5} /> : filtered.length === 0 ? (
        <EmptyState icon="variables" title={vars.length === 0 ? "No variables in this workspace." : "No matches"} description={vars.length === 0 ? "Add a variable above. Reference it with {{ $env.KEY }}." : `No variables match “${search}”.`} />
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Key</th><th>Value</th><th>Type</th><th>Actions</th></tr></thead>
            <tbody>
              {filtered.map(v => {
                const isConnStr = /DATABASE_URL|POSTGRES|MYSQL|MONGODB|REDIS|DSN|CONNECTION_STRING/i.test(v.key)
                return (
                <tr key={v.id}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{
                        width: 28, height: 28, borderRadius: 6,
                        background: v.is_secret ? 'rgba(245, 158, 11, 0.12)' : 'rgba(99, 102, 241, 0.12)',
                        border: v.is_secret ? '1px solid rgba(245, 158, 11, 0.3)' : '1px solid rgba(99, 102, 241, 0.25)',
                        display: 'grid', placeItems: 'center',
                        color: v.is_secret ? '#fbbf24' : '#818cf8',
                        flexShrink: 0
                      }}>
                        {v.is_secret ? (
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                        ) : (
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/></svg>
                        )}
                      </div>
                      <code style={{ fontSize: 13, fontWeight: 600, color: '#f8fafc' }}>{v.key}</code>
                      <button
                        type="button"
                        className="ghost small"
                        title={`Copy snippet: {{ $env.${v.key} }}`}
                        onClick={() => navigator.clipboard.writeText(`{{ $env.${v.key} }}`)}
                        style={{ padding: '2px 6px', fontSize: 10, color: '#94a3b8', borderRadius: 4 }}
                      >
                        Copy
                      </button>
                    </div>
                  </td>
                  <td className={v.is_secret ? 'secret' : ''} style={{ fontFamily: 'monospace', fontSize: 12 }}>{v.is_secret ? '••••••••' : v.value}</td>
                  <td>
                    <span className={`badge ${v.is_secret ? 'badge-amber' : 'badge-muted'}`} style={{
                      padding: '2px 7px', borderRadius: 99, fontSize: 10.5, fontWeight: 600,
                      background: v.is_secret ? 'rgba(245, 158, 11, 0.12)' : 'rgba(255, 255, 255, 0.05)',
                      color: v.is_secret ? '#fbbf24' : '#94a3b8',
                      border: v.is_secret ? '1px solid rgba(245, 158, 11, 0.3)' : '1px solid rgba(255, 255, 255, 0.08)'
                    }}>
                      {v.is_secret ? 'secret' : 'plain'}
                    </span>
                  </td>
                  <td>
                    <button
                      className="ghost small"
                      onClick={() => setDeleteTarget(v)}
                      title={isConnStr ? 'Delete connection string' : 'Delete variable'}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      </svg>
                      <span>{isConnStr ? 'Delete connection string' : 'Delete'}</span>
                    </button>
                  </td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {workspaces.length === 0 && !loading && <div className="hint" style={{ marginTop: 12 }}>No workspaces found. Create one via the API or ask an admin.</div>}

      <ConfirmDialog open={Boolean(deleteTarget)} title={`Delete ${/DATABASE_URL|POSTGRES|MYSQL|MONGODB|REDIS|DSN|CONNECTION_STRING/i.test(deleteTarget?.key || '') ? 'connection string' : 'variable'} “${deleteTarget?.key}”?`} description={/DATABASE_URL|POSTGRES|MYSQL|MONGODB|REDIS|DSN|CONNECTION_STRING/i.test(deleteTarget?.key || '') ? 'The connection string will be permanently removed from this workspace. Workflows using it will fail until updated.' : 'The variable will be removed from future executions.'} confirmLabel={/DATABASE_URL|POSTGRES|MYSQL|MONGODB|REDIS|DSN|CONNECTION_STRING/i.test(deleteTarget?.key || '') ? 'Delete connection string' : 'Delete'} variant="danger" onCancel={() => setDeleteTarget(null)} onConfirm={async () => { try{ await api.deleteEnvVar(deleteTarget.id); await loadVars(wsId)} catch(e){ setError(e.message)} finally{ setDeleteTarget(null) } }} />
    </div>
  )
}
