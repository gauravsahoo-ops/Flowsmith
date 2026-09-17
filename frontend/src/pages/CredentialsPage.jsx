import { useEffect, useState } from 'react'
import { api } from '../api'
import { useCredentialStore } from '../stores/credentialStore'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import WorkspaceTabs from '../components/shared/WorkspaceTabs'

function defaultsFromSchema(schema) {
  const out = {}
  for (const [key, prop] of Object.entries(schema?.properties || {})) {
    if (prop.default !== undefined) out[key] = prop.default
    else if (prop.type === 'boolean') out[key] = false
    else if (prop.type === 'number' || prop.type === 'integer') out[key] = 0
    else out[key] = ''
  }
  return out
}

export default function CredentialsPage() {
  const credentials = useCredentialStore(s => s.credentials)
  const types = useCredentialStore(s => s.types)
  const load = useCredentialStore(s => s.load)
  const create = useCredentialStore(s => s.create)
  const remove = useCredentialStore(s => s.remove)
  const connectOAuth = useCredentialStore(s => s.connectOAuth)

  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [form, setForm] = useState({ name: '', type: '', data: {} })
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [oauthBusy, setOauthBusy] = useState('')
  const [fallbackUrl, setFallbackUrl] = useState('')
  const [sfLoginUrl, setSfLoginUrl] = useState('')
  const [showSfAdvanced, setShowSfAdvanced] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [loading, setLoading] = useState(true)
  const [providers, setProviders] = useState([])
  const [predefined, setPredefined] = useState([])
  const [reportOpen, setReportOpen] = useState(false)
  const [testingId, setTestingId] = useState(null)
  const [testResult, setTestResult] = useState(null)
  const [reconnectingId, setReconnectingId] = useState(null)

  useEffect(() => {
    load().finally(() => setLoading(false))
  }, [])
  useEffect(() => {
    api.listCredentialProviders().then(d => setProviders(Array.isArray(d) ? d : [])).catch(()=>{})
    api.listPredefinedCredentials().then(d => setPredefined(Array.isArray(d) ? d : [])).catch(()=>{})
  }, [])

  const filtered = credentials.filter(c => {
    if (typeFilter !== 'all' && c.type !== typeFilter) return false
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      if (!`${c.name} ${c.type}`.toLowerCase().includes(q)) return false
    }
    return true
  })

  const schema = types.find(t => t.type === form.type)?.parameters_schema
  const secretFields = new Set(types.find(t => t.type === form.type)?.secret_fields || [])
  const isOAuthType = ['salesforce','hubspot','google_calendar','google_sheets','gmail','google_drive','google_docs'].includes(form.type)

  async function handleReconnect(c) {
    setReconnectingId(c.id)
    setError(null)
    setNotice(null)
    try {
      const res = await api.reconnectCredential(c.id)
      if (res && res.ok && res.refreshed) {
        setNotice(res.message || `${c.name} reconnected successfully.`)
        await load()
        return
      }
      if (res && res.ok === false && res.code === 'NOT_FOUND') {
        setError('Credential not found. Refreshing list…')
        await load()
        return
      }
      if (res && res.ok === false && res.message) {
        setNotice(res.message)
      }
      handleOAuth(c.type, c.type === 'salesforce' ? (sfLoginUrl || undefined) : undefined)
    } catch (err) {
      if (err && err.status === 404) {
        setError('Credential not found. Refreshing list…')
        try { await load() } catch {}
        return
      }
      setError((err && err.message) || 'Reconnect failed.')
    } finally {
      setReconnectingId(null)
    }
  }

  async function handleOAuth(provider, loginUrl) {
    setOauthBusy(provider); setError(null); setNotice(null); setFallbackUrl('')
    try {
      const { authorizeUrl } = await connectOAuth(provider, loginUrl)
      if (!authorizeUrl) throw new Error('Failed to get authorization URL')
      setFallbackUrl(authorizeUrl)
      const w = window.open(authorizeUrl, `oauth-${provider}`, 'width=520,height=640')
      if (!w) {
        setError('Popup blocked. Allow popups for this site, or copy the authorization link below.')
        return
      }
      let handled = false
      const expectedOrigin = window.location.origin
      // Also accept backend API origin if different from frontend origin
      let backendOrigin = null
      try {
        const apiBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
        if (apiBase) {
          const u = new URL(apiBase)
          backendOrigin = u.origin
        }
      } catch {}
      const handler = (event) => {
        // Validate origin - allow same origin and backend origin
        try {
          const origin = event.origin
          const isExpected = origin === expectedOrigin || origin === backendOrigin
          if (!isExpected && origin !== 'null') {
            // Still allow * for dev, but log
            console.warn('OAuth message from unexpected origin', origin)
          }
        } catch {}
        const msg = event.data
        if (!msg || typeof msg !== 'object') return
        // Support both new (source:oauth,type:...) and legacy (source:salesforce-oauth)
        const isOAuth = msg.source === 'oauth' || msg.source === 'salesforce-oauth'
        const isSuccess = msg.type === 'salesforce-oauth-success' || (msg.ok === true)
        const isError = msg.type === 'salesforce-oauth-error' || (msg.ok === false)
        if (!isOAuth || (!isSuccess && !isError)) return
        // Validate provider matches if present
        if (msg.provider && msg.provider !== provider) return
        handled = true
        if (isSuccess || msg.ok) {
          setNotice(`${msg.provider || provider} connected.`)
          setError(null)
        } else {
          setError(msg.error || 'Authorization failed.')
          setNotice(null)
        }
        window.removeEventListener('message', handler)
        setOauthBusy('')
        setFallbackUrl('')
        // Refetch real backend state (source of truth)
        load()
        if (w && !w.closed) w.close()
      }
      window.addEventListener('message', handler)
      // Detect popup closed without success
      const pollClosed = setInterval(() => {
        if (w.closed) {
          clearInterval(pollClosed)
          if (!handled) {
            setOauthBusy('')
            // Don't show error if user just closed, just reset
          }
          window.removeEventListener('message', handler)
        }
      }, 500)
      setTimeout(() => {
        clearInterval(pollClosed)
        setOauthBusy('')
        window.removeEventListener('message', handler)
      }, 120000)
    } catch (e) { setError(e.message); setOauthBusy(''); setFallbackUrl('') }
  }

  async function handleCreate(e) {
    e.preventDefault()
    if (!form.name.trim() || !form.type) return
    setBusy(true); setError(null); setNotice(null)
    try {
      await create({ name: form.name.trim(), type: form.type, data: form.data })
      setForm({ name: '', type: '', data: {} })
      setNotice('Credential saved.')
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="page credentials-page">
      <PageHeader
        title="Credentials"
        description="Manage encrypted connections used by your workflows. Secrets are stored encrypted and never shown again."
      />
      <WorkspaceTabs />

      <div className="toolbar">
        <input className="search-input" placeholder="Search credentials…" value={search} onChange={e => setSearch(e.target.value)} aria-label="Search credentials" />
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} aria-label="Filter by type">
          <option value="all">All types</option>
          {types.map(t => <option key={t.type} value={t.type}>{t.name}</option>)}
        </select>
        <span className="hint">{filtered.length}/{credentials.length}</span>
      </div>

      {notice && <div className="banner-inline ok">{notice}</div>}
      {error && <div className="banner-inline err">{error}</div>}
      {testResult && (
        <div className={`banner-inline ${testResult.ok ? 'ok' : 'err'}`} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderRadius: 8, padding: '10px 14px', margin: '12px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>{testResult.ok ? '✓' : '⚠'}</span>
            <span>
              <strong>{testResult.name || testResult.id}:</strong>{' '}
              {testResult.message || (testResult.ok ? 'Connection test passed' : 'Test failed')}
              {testResult.identity && (
                <span className="hint" style={{ marginLeft: 6, opacity: 0.9 }}>({testResult.identity})</span>
              )}
            </span>
          </div>
          <button className="ghost small" onClick={() => setTestResult(null)} aria-label="Dismiss">✕</button>
        </div>
      )}

      {loading ? <LoadingSkeleton rows={4} /> : filtered.length === 0 ? (
        credentials.length === 0 ? <EmptyState icon="🔑" title="No credentials yet" description="Add a credential to connect workflows to external services. Secrets are encrypted at rest." /> : <EmptyState icon="🔍" title="No matches" description="No credentials match your search." />
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
              {filtered.map(c => (
                <tr key={c.id}>
                  <td><strong>{c.name}</strong><div className="hint" style={{ fontSize: 11 }}>{c.id.slice(0,8)}</div></td>
                  <td><span className="badge badge-muted">{c.type}</span></td>
                  <td><span className="dot status-success" /> <span className="hint">Encrypted</span></td>
                  <td>
                    {['salesforce','hubspot','google_calendar','google_sheets','gmail','google_drive','google_docs'].includes(c.type) && (
                      <button
                        className="ghost small"
                        onClick={() => handleReconnect(c)}
                        disabled={oauthBusy === c.type || reconnectingId === c.id}
                        title="Auto-reconnect or renew token"
                      >
                        {reconnectingId === c.id ? 'Reconnecting…' : (oauthBusy === c.type ? '…' : '↻ Reconnect')}
                      </button>
                    )}
                    <button
                      className="ghost small"
                      onClick={async () => {
                        setTestingId(c.id)
                        setTestResult(null)
                        try {
                          const r = await api.testCredential(c.id)
                          setTestResult({ ...r, id: c.id, name: c.name })
                        } catch (e) {
                          setTestResult({ ok: false, message: e.message, id: c.id, name: c.name })
                        } finally {
                          setTestingId(null)
                        }
                      }}
                      disabled={testingId === c.id}
                      title="Test connection with live service"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                    >
                      {testingId === c.id ? (
                        <>
                          <span className="dot status-running" style={{ width: 6, height: 6 }} />
                          <span>Testing…</span>
                        </>
                      ) : (
                        <>
                          <span>⚡</span>
                          <span>Test</span>
                        </>
                      )}
                    </button>
                    <button className="ghost small" onClick={() => setDeleteTarget(c)} title={['database','postgres','mysql','redis','mongodb'].includes(c.type) ? 'Delete connection string' : 'Delete'}>{['database','postgres','mysql','redis','mongodb'].includes(c.type) ? '🗑 Delete connection string' : '🗑'}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <section className="card" style={{ marginTop: 16 }}>
        <button className="ghost" onClick={() => setReportOpen(v => !v)} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="cfg-caret">{reportOpen ? '▾' : '▸'}</span>
          <span style={{ fontWeight: 600 }}>Provider Capability Report</span>
          <span className="hint" style={{ marginLeft: 'auto', fontSize: 11 }}>{providers.length} generic · {predefined.length} predefined</span>
        </button>
        {reportOpen && (
          <div style={{ marginTop: 12 }}>
            <h3 style={{ fontSize: 12, textTransform: 'uppercase', color: 'var(--muted)', margin: '8px 0 6px' }}>Generic Auth Providers</h3>
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Provider</th><th>Auth Type</th><th>Status</th></tr></thead>
                <tbody>
                  {providers.length === 0 ? <tr><td colSpan={3} className="hint">Loading…</td></tr> : providers.map(p => (
                    <tr key={p.id}>
                      <td><code>{p.id}</code> {p.displayName && <span className="hint">— {p.displayName}</span>}</td>
                      <td><code>{p.authType}</code></td>
                      <td>{p.implemented ? <span style={{ color: 'var(--green)', fontWeight: 600 }}>IMPLEMENTED</span> : <span style={{ color: 'var(--red)' }}>Not implemented</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3 style={{ fontSize: 12, textTransform: 'uppercase', color: 'var(--muted)', margin: '16px 0 6px' }}>Predefined Credentials</h3>
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>ID</th><th>Display Name</th><th>Provider</th><th>Status</th></tr></thead>
                <tbody>
                  {predefined.length === 0 ? <tr><td colSpan={4} className="hint">Loading…</td></tr> : predefined.map(p => (
                    <tr key={p.id}>
                      <td><code>{p.id}</code></td>
                      <td>{p.displayName}</td>
                      <td><code>{p.provider}</code></td>
                      <td>{p.implemented ? <span style={{ color: 'var(--green)', fontWeight: 600 }}>IMPLEMENTED</span> : <span style={{ color: 'var(--amber)' }}>REGISTERED / NOT IMPLEMENTED</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint" style={{ marginTop: 8, fontSize: 11 }}>Adding a provider requires: 1) credential definition 2) credential schema 3) authentication provider 4) registration 5) tests. HTTP Request discovers it via registry.</p>
          </div>
        )}
      </section>

      <section className="card" style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 14, margin: '0 0 8px' }}>New credential</h2>

        {isOAuthType && (
          <div className="sf-connect-box">
            <p className="hint">Connect via OAuth — you authorize with your own account; refresh tokens are stored encrypted server-side.</p>
            <button className="primary" onClick={() => handleOAuth(form.type, form.type === 'salesforce' ? (sfLoginUrl || undefined) : undefined)} disabled={!!oauthBusy || !form.type}>{oauthBusy ? 'Connecting…' : `Connect ${form.type}`}</button>
            {form.type === 'salesforce' && (
              <>
                <button className="ghost" onClick={() => setShowSfAdvanced(v => !v)} style={{ marginTop: 6, marginLeft: 6 }}>
                  {showSfAdvanced ? 'Hide' : 'Use a different org login URL'}
                </button>
                {showSfAdvanced && (
                  <div style={{ marginTop: 6 }}>
                    <input value={sfLoginUrl} onChange={e => setSfLoginUrl(e.target.value)} placeholder="https://login.salesforce.com" />
                  </div>
                )}
              </>
            )}
            {fallbackUrl && (
              <div style={{ marginTop: 8, wordBreak: 'break-all' }}>
                <p className="hint">If the popup didn't open, copy this link:</p>
                <a href={fallbackUrl} target="_blank" rel="noreferrer" className="linklike" style={{ fontSize: 11 }}>{fallbackUrl.slice(0,80)}…</a>
                <button className="ghost small" onClick={() => navigator.clipboard.writeText(fallbackUrl)} style={{ marginLeft: 6 }}>Copy</button>
              </div>
            )}
          </div>
        )}

        <form onSubmit={handleCreate} className="cred-form">
          <label>Name<input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required placeholder="My credential" /></label>
          <label>Type
            <select value={form.type} onChange={e => setForm({ ...form, type: e.target.value, data: defaultsFromSchema(types.find(t => t.type === e.target.value)?.parameters_schema) })} required>
              <option value="">Select…</option>
              {types.map(t => <option key={t.type} value={t.type} disabled={t.implemented === false}>{t.name} ({t.type}){t.implemented === false ? ' — Not implemented' : ''}</option>)}
            </select>
            {form.type && types.find(t => t.type === form.type)?.implemented === false && (
              <div className="banner-inline err" style={{ marginTop: 6 }}>Authentication provider not implemented yet — execution will be blocked.</div>
            )}
          </label>
          {schema && !isOAuthType && Object.entries(schema.properties || {}).map(([key, prop]) => {
            const isConnStr = ['dsn','uri','connection_string','connectionString'].includes(key) || (prop.description && prop.description.toLowerCase().includes('connection string'))
            return (
            <label key={key}>{prop.title || key}{prop.description && <span className="muted"> — {prop.description}</span>}
              {prop.type === 'boolean' ? (
                <input type="checkbox" checked={Boolean(form.data[key])} onChange={e => setForm({ ...form, data: { ...form.data, [key]: e.target.checked } })} />
              ) : (
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input style={{ flex: 1 }} type={secretFields.has(key) ? 'password' : prop.type === 'number' || prop.type === 'integer' ? 'number' : 'text'} value={form.data[key] ?? ''} onChange={e => setForm({ ...form, data: { ...form.data, [key]: prop.type === 'number' || prop.type === 'integer' ? Number(e.target.value) : e.target.value } })} />
                  {isConnStr && form.data[key] && (
                    <button type="button" className="ghost small" onClick={() => setForm({ ...form, data: { ...form.data, [key]: '' } })} title="Clear connection string">🗑 Clear</button>
                  )}
                </div>
              )}
            </label>
            )
          })}
          {!isOAuthType && <button className="primary" type="submit" disabled={busy || !form.name.trim() || !form.type}>{busy ? 'Saving…' : 'Save credential'}</button>}
        </form>
      </section>

      <ConfirmDialog open={Boolean(deleteTarget)} title={`Delete “${deleteTarget?.name}”?`} description={deleteTarget && ['database','postgres','mysql','redis','mongodb'].includes(deleteTarget.type) ? 'The connection string will be permanently deleted. Workflows using this connection will fail until updated.' : 'This credential will be disconnected. Workflows referencing it will fail until updated.'} confirmLabel={deleteTarget && ['database','postgres','mysql','redis','mongodb'].includes(deleteTarget.type) ? 'Delete connection string' : 'Delete'} variant="danger" onCancel={() => setDeleteTarget(null)} onConfirm={async () => { try { await remove(deleteTarget.id); setNotice(deleteTarget && ['database','postgres','mysql','redis','mongodb'].includes(deleteTarget.type) ? 'Connection string deleted.' : 'Deleted.'); } catch(e){ setError(e.message)} finally{ setDeleteTarget(null) } }} />
    </div>
  )
}
