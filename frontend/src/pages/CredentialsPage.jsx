import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useCredentialStore } from '../stores/credentialStore'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import WorkspaceTabs from '../components/shared/WorkspaceTabs'
import { NodeIcon } from '../components/NodeIcons'
import SearchableSelect from '../components/SearchableSelect'

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
  const storeCreds = useCredentialStore(s => s.credentials)
  const credentials = (storeCreds && storeCreds.length) ? storeCreds : useCredentialStore.getState().credentials
  const storeTypes = useCredentialStore(s => s.types)
  const types = (storeTypes && storeTypes.length) ? storeTypes : useCredentialStore.getState().types
  const load = useCredentialStore(s => s.load)
  const create = useCredentialStore(s => s.create)
  const remove = useCredentialStore(s => s.remove)
  const logout = useCredentialStore(s => s.logout)
  const connectOAuth = useCredentialStore(s => s.connectOAuth)

  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [form, setForm] = useState({ name: '', type: '', data: {} })
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [oauthBusy, setOauthBusy] = useState('')
  const [fallbackUrl, setFallbackUrl] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [logoutTarget, setLogoutTarget] = useState(null)
  const [loading, setLoading] = useState(!useCredentialStore.getState().loaded)
  const [providers, setProviders] = useState([])
  const [predefined, setPredefined] = useState([])
  const [reportOpen, setReportOpen] = useState(false)
  const [testingId, setTestingId] = useState(null)
  const [testResult, setTestResult] = useState(null)
  const [reconnectingId, setReconnectingId] = useState(null)
  const mountedRef = useRef(true)
  const oauthCleanupRef = useRef(null)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (oauthCleanupRef.current) {
        oauthCleanupRef.current()
        oauthCleanupRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    load().finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    setFallbackUrl('')

    // Open popup immediately on user click gesture to prevent browser popup blockers
    let popup = null
    try {
      popup = window.open('about:blank', `oauth-${c.type}`, 'width=560,height=680')
      if (popup && popup.document) {
        popup.document.write(`
          <!DOCTYPE html>
          <html>
            <head>
              <title>Reconnecting ${c.name || 'Account'}…</title>
              <style>
                body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
                .spinner { width: 36px; height: 36px; border: 3px solid rgba(255,255,255,0.15); border-top-color: #38bdf8; border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 16px; }
                @keyframes spin { to { transform: rotate(360deg); } }
                h3 { margin: 0 0 8px; font-size: 16px; }
                p { font-size: 13px; color: #94a3b8; margin: 0; }
              </style>
            </head>
            <body>
              <div class="spinner"></div>
              <h3>Reconnecting ${c.name || 'Account'}…</h3>
              <p>Checking active session or preparing authorization…</p>
            </body>
          </html>
        `)
      }
    } catch {}

    try {
      const res = await api.reconnectCredential(c.id)
      if (res && res.ok && res.refreshed) {
        if (popup && !popup.closed) {
          try { popup.close() } catch {}
        }
        setNotice(res.message || `${c.name} reconnected successfully.`)
        await load()
        return
      }
      if (res && res.ok === false && res.code === 'NOT_FOUND') {
        if (popup && !popup.closed) {
          try { popup.close() } catch {}
        }
        setError('Credential not found. Refreshing list…')
        await load()
        return
      }
      const loginUrl = res?.login_url || undefined
      // Navigate existing popup window seamlessly to provider authorization
      await handleOAuth(c.type, loginUrl, 'login', { credential_id: c.id }, popup)
    } catch (err) {
      if (popup && !popup.closed) {
        try { popup.close() } catch {}
      }
      if (err && err.status === 404) {
        setError('Credential not found. Refreshing list…')
        try { await load() } catch {}
        return
      }
      const msg = (err && err.message) || ''
      setError(msg || 'Reconnect failed.')
    } finally {
      setReconnectingId(null)
    }
  }

  async function handleOAuth(provider, loginUrl, prompt, extra = {}, popupWindow = null) {
    setOauthBusy(provider); setError(null); setNotice(null); setFallbackUrl('')
    try {
      const { authorizeUrl } = await connectOAuth(provider, loginUrl, prompt, extra)
      if (!authorizeUrl) throw new Error('Failed to get authorization URL')
      setFallbackUrl(authorizeUrl)

      let w = popupWindow
      if (w && !w.closed) {
        try {
          w.location.href = authorizeUrl
        } catch {
          w = window.open(authorizeUrl, `oauth-${provider}`, 'width=560,height=680')
        }
      } else {
        w = window.open(authorizeUrl, `oauth-${provider}`, 'width=560,height=680')
      }

      let handled = false
      const expectedOrigin = window.location.origin
      let backendOrigin = null
      try {
        const apiBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
        if (apiBase) {
          const u = new URL(apiBase)
          backendOrigin = u.origin
        }
      } catch {}

      let bc = null
      let pollClosed = null
      let timeoutTimer = null

      const cleanupListeners = () => {
        window.removeEventListener('message', messageHandler)
        window.removeEventListener('storage', storageHandler)
        if (bc) {
          try { bc.close() } catch {}
          bc = null
        }
        if (pollClosed) {
          clearInterval(pollClosed)
          pollClosed = null
        }
        if (timeoutTimer) {
          clearTimeout(timeoutTimer)
          timeoutTimer = null
        }
        oauthCleanupRef.current = null
      }
      oauthCleanupRef.current = cleanupListeners

      const processResult = (msg) => {
        if (!msg || typeof msg !== 'object') return
        const isOAuth = msg.source === 'oauth' || msg.source === 'salesforce-oauth'
        const isSuccess = msg.type === 'salesforce-oauth-success' || (msg.ok === true)
        const isError = msg.type === 'salesforce-oauth-error' || (msg.ok === false)
        if (!isOAuth || (!isSuccess && !isError)) return
        if (msg.provider && msg.provider !== provider) return
        handled = true
        if (mountedRef.current) {
          if (isSuccess || msg.ok) {
            setNotice(`${msg.provider || provider} connected successfully.`)
            setError(null)
          } else {
            setError(msg.error || 'Authorization failed.')
            setNotice(null)
          }
          setOauthBusy('')
          setFallbackUrl('')
        }
        cleanupListeners()
        load()
        if (w && !w.closed) {
          try { w.close() } catch {}
        }
      }

      const messageHandler = (event) => {
        try {
          const origin = event.origin
          const isExpected = origin === expectedOrigin || origin === backendOrigin
          if (!isExpected && origin !== 'null') {
            console.warn('OAuth message from unexpected origin', origin)
          }
        } catch {}
        processResult(event.data)
      }

      const storageHandler = (event) => {
        if (event.key === 'flowsmith_oauth_result' && event.newValue) {
          try {
            processResult(JSON.parse(event.newValue))
          } catch {}
        }
      }

      window.addEventListener('message', messageHandler)
      window.addEventListener('storage', storageHandler)
      try {
        if (typeof BroadcastChannel !== 'undefined') {
          bc = new BroadcastChannel('flowsmith_oauth')
          bc.onmessage = (event) => {
            if (event?.data) processResult(event.data)
          }
        }
      } catch {}

      if (!w) {
        if (mountedRef.current) {
          setError('Popup was blocked by your browser. Click the "Authorize in New Tab" button below to finish connecting.')
        }
        return
      }

      // Detect popup closed without success
      pollClosed = setInterval(() => {
        if (w.closed) {
          if (!handled && mountedRef.current) {
            setOauthBusy('')
            // Check if backend completed connection in the background
            setTimeout(() => { if (mountedRef.current) load() }, 1000)
          }
          cleanupListeners()
        }
      }, 500)
      timeoutTimer = setTimeout(() => {
        if (mountedRef.current) setOauthBusy('')
        cleanupListeners()
      }, 120000)
    } catch (e) {
      if (mountedRef.current) {
        const msg = e.message || ''
        setError(msg || 'Authorization failed.')
        setOauthBusy('')
        setFallbackUrl('')
      }
    }
  }

  async function handleCreate(e) {
    e.preventDefault()
    if (!form.name.trim()) {
      setError('Please enter a name for this credential before saving.')
      return
    }
    if (!form.type) {
      setError('Please select a credential type.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await create({ name: form.name.trim(), type: form.type, data: form.data })
      setForm({ name: '', type: '', data: {} })
      setNotice('Credential created.')
    } catch (err) {
      setError((err && err.message) || 'Failed to save credential.')
    } finally {
      setBusy(false)
    }
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
      {fallbackUrl && (
        <div className="banner-inline ok" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, margin: '10px 0', padding: '12px 16px', background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.3)' }}>
          <div>
            <strong>Interactive Authorization Required</strong>
            <div style={{ fontSize: 13, opacity: 0.85, marginTop: 2 }}>
              If the popup did not open automatically, click the button to complete authorization in a new tab.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <a
              href={fallbackUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="primary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 14px', borderRadius: 6, textDecoration: 'none', background: 'var(--accent, #3b82f6)', color: '#fff', fontWeight: 600 }}
            >
              Authorize in New Tab ↗
            </a>
            <button className="ghost small" onClick={() => setFallbackUrl('')}>✕</button>
          </div>
        </div>
      )}
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {!testResult.ok && credentials.some(x => x.id === testResult.id && ['salesforce','hubspot','google_calendar','google_sheets','gmail','google_drive','google_docs'].includes(x.type)) && (
              <button
                type="button"
                className="primary small"
                onClick={() => {
                  const cred = credentials.find(x => x.id === testResult.id)
                  if (cred) handleReconnect(cred)
                }}
                disabled={reconnectingId === testResult.id}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, padding: '4px 10px', background: '#f59e0b', borderColor: '#d97706', color: '#000', fontWeight: 600 }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
                </svg>
                <span>{reconnectingId === testResult.id ? 'Reconnecting…' : 'Reconnect Now'}</span>
              </button>
            )}
            <button className="ghost small" onClick={() => setTestResult(null)} aria-label="Dismiss">✕</button>
          </div>
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
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ width: 30, height: 30, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(255,255,255,0.04)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)', flexShrink: 0 }}>
                        <NodeIcon type={c.type} size={20} />
                      </div>
                      <div>
                        <strong>{c.name}</strong>
                        <div className="hint" style={{ fontSize: 11 }}>{c.id.slice(0,8)}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span
                      className="badge"
                      style={{
                        background: `${{
                          salesforce: '#00a1e0',
                          hubspot: '#ff7a59',
                          google_sheets: '#0f9d58',
                          google_drive: '#4285f4',
                          google_calendar: '#4285f4',
                          gmail: '#ea4335',
                          postgres: '#38bdf8',
                          mysql: '#00758f',
                          redis: '#f43f5e',
                          mongodb: '#10b981',
                          openai: '#10a37f',
                          slack: '#a855f7',
                          telegram: '#38bdf8',
                        }[c.type] || '#818cf8'}18`,
                        color: {
                          salesforce: '#38bdf8',
                          hubspot: '#fb923c',
                          google_sheets: '#34d399',
                          google_drive: '#60a5fa',
                          google_calendar: '#60a5fa',
                          gmail: '#f87171',
                          postgres: '#38bdf8',
                          mysql: '#38bdf8',
                          redis: '#fb7185',
                          mongodb: '#34d399',
                          openai: '#34d399',
                          slack: '#c084fc',
                          telegram: '#38bdf8',
                        }[c.type] || '#a5b4fc',
                        borderColor: 'rgba(255, 255, 255, 0.12)',
                        fontWeight: 600,
                        textTransform: 'capitalize'
                      }}
                    >
                      {c.type.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td>
                    {c.expired ? (
                      <span
                        className="status-pill status-warning"
                        title="Session expired or token revoked — click Reconnect to renew"
                        style={{
                          background: 'rgba(245, 158, 11, 0.12)',
                          borderColor: 'rgba(245, 158, 11, 0.3)',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 6
                        }}
                      >
                        <span className="dot" style={{ width: 6, height: 6, borderRadius: '50%', background: '#f59e0b' }} />
                        <span style={{ color: '#f59e0b', fontWeight: 600 }}>Session Expired</span>
                      </span>
                    ) : (
                      <span
                        className="status-pill status-success"
                        title="Active connection encrypted at rest with AES-256 / Fernet"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                      >
                        <span className="dot" style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981' }} />
                        <span style={{ color: '#34d399' }}>Connected</span>
                      </span>
                    )}
                  </td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                      <button
                        type="button"
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
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                      >
                        {testingId === c.id ? (
                          <>
                            <span className="dot status-running" style={{ width: 6, height: 6 }} />
                            <span>Testing…</span>
                          </>
                        ) : (
                          <>
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                            </svg>
                            <span>Test</span>
                          </>
                        )}
                      </button>

                      {['salesforce','hubspot','google_calendar','google_sheets','gmail','google_drive','google_docs'].includes(c.type) && (
                        <button
                          type="button"
                          className={c.expired ? 'primary small' : 'ghost small'}
                          onClick={() => handleReconnect(c)}
                          disabled={reconnectingId === c.id}
                          title={c.expired ? 'Session expired — click Reconnect to re-authenticate or refresh token' : 'Auto-reconnect or renew token'}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            ...(c.expired ? { background: '#f59e0b', borderColor: '#d97706', color: '#000', fontWeight: 600 } : {})
                          }}
                        >
                          {reconnectingId === c.id ? (
                            <>
                              <span className="dot status-running" style={{ width: 6, height: 6 }} />
                              <span>Reconnecting…</span>
                            </>
                          ) : (
                            <>
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
                              </svg>
                              <span>Reconnect</span>
                            </>
                          )}
                        </button>
                      )}

                      {['salesforce','hubspot','google_calendar','google_sheets','gmail','google_drive','google_docs'].includes(c.type) ? (
                        <button
                          type="button"
                          className="ghost small"
                          onClick={() => setLogoutTarget(c)}
                          title="Revoke session and tokens on provider and disconnect completely"
                          style={{
                            color: '#f87171',
                            borderColor: 'rgba(248, 113, 113, 0.25)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                          }}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
                          </svg>
                          <span>Logout</span>
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="ghost small"
                          onClick={() => setDeleteTarget(c)}
                          title={['database','postgres','mysql','redis','mongodb'].includes(c.type) ? 'Delete connection string' : 'Delete'}
                          style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: '#f87171' }}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="3 6 5 6 21 6" />
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          </svg>
                          <span>Delete</span>
                        </button>
                      )}
                    </div>
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
        <h2 style={{ fontSize: 14, margin: '0 0 12px' }}>New credential</h2>

        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', marginBottom: 6, fontWeight: 600, fontSize: 13 }}>Select Service / Type</label>
          <SearchableSelect
            value={form.type}
            onChange={val => {
              const selectedType = types.find(t => t.type === val)
              setForm(prev => ({
                ...prev,
                type: val,
                name: prev.name.trim() ? prev.name : (selectedType?.name ? `${selectedType.name} Credential` : ''),
                data: defaultsFromSchema(selectedType?.parameters_schema),
              }))
            }}
            options={types.map(t => ({
              value: t.type,
              label: `${t.name} (${t.type})`,
              disabled: t.implemented === false,
              disabledReason: t.implemented === false ? 'Not implemented' : undefined,
              hint: t.description || undefined,
            }))}
            placeholder="Search or select credential type…"
          />
          {form.type && types.find(t => t.type === form.type)?.implemented === false && (
            <div className="banner-inline err" style={{ marginTop: 6 }}>Authentication provider not implemented yet — execution will be blocked.</div>
          )}
        </div>

        {isOAuthType ? (
          <div className="sf-connect-box" style={{ padding: '18px', background: 'rgba(255, 255, 255, 0.02)', borderRadius: 8, border: '1px solid rgba(255, 255, 255, 0.08)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <strong style={{ textTransform: 'capitalize', fontSize: 15 }}>
                  {form.type.replace(/_/g, ' ')}
                </strong>
                <span className="badge" style={{ background: 'rgba(56, 189, 248, 0.12)', color: '#38bdf8', borderColor: 'rgba(56, 189, 248, 0.25)', fontSize: 11 }}>
                  OAuth 2.0
                </span>
              </div>
              {credentials.filter(c => c.type === form.type).length > 0 && (
                <span className="badge" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#34d399', borderColor: 'rgba(16, 185, 129, 0.3)' }}>
                  ✓ {credentials.filter(c => c.type === form.type).length} account{credentials.filter(c => c.type === form.type).length > 1 ? 's' : ''} connected
                </span>
              )}
            </div>

            <p className="hint" style={{ margin: '4px 0 12px', fontSize: 13, lineHeight: 1.5 }}>
              Authenticate securely with {form.type.replace(/_/g, ' ')} using the standard login popup. Flowsmith stores encrypted access tokens and automatically refreshes them.
            </p>

            {credentials.filter(c => c.type === form.type).length > 0 && (
              <div style={{ margin: '8px 0 14px', padding: '10px 12px', background: 'rgba(255, 255, 255, 0.03)', borderRadius: 6, border: '1px solid rgba(255, 255, 255, 0.06)' }}>
                <div className="hint" style={{ fontSize: 12, marginBottom: 6 }}>Connected accounts (available to workflows):</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {credentials.filter(c => c.type === form.type).map(acc => (
                    <span key={acc.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '4px 10px', borderRadius: 6, background: 'rgba(255,255,255,0.06)', fontSize: 12, border: '1px solid rgba(255,255,255,0.08)' }}>
                      <span className="dot" style={{ width: 6, height: 6, borderRadius: '50%', background: '#34d399' }} />
                      <strong>{acc.name}</strong>
                      <button
                        type="button"
                        className="ghost small"
                        style={{ padding: '0 4px', fontSize: 11, color: '#f87171' }}
                        onClick={() => setLogoutTarget(acc)}
                        title="Logout and revoke this account"
                      >
                        🚪 Logout
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
              <button
                className="primary"
                type="button"
                onClick={() => handleOAuth(form.type)}
                disabled={!!oauthBusy || !form.type}
                style={{ padding: '8px 18px', fontSize: 13, fontWeight: 600 }}
              >
                {oauthBusy ? 'Connecting…' : (credentials.some(c => c.type === form.type) ? `+ Connect another ${form.type.replace(/_/g, ' ')} account` : `Connect ${form.type.replace(/_/g, ' ')}`)}
              </button>
            </div>
            {fallbackUrl && (
              <div style={{ marginTop: 8, wordBreak: 'break-all' }}>
                <p className="hint">If the popup didn't open, copy this link:</p>
                <a href={fallbackUrl} target="_blank" rel="noreferrer" className="linklike" style={{ fontSize: 11 }}>{fallbackUrl.slice(0,80)}…</a>
                <button type="button" className="ghost small" onClick={() => navigator.clipboard.writeText(fallbackUrl)} style={{ marginLeft: 6 }}>Copy</button>
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={handleCreate} className="cred-form">
            <label>
              Name
              <input
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                required
                placeholder="e.g. My Database Connection"
              />
              {form.type && !form.name.trim() && (
                <span style={{ color: 'var(--amber, #f59e0b)', fontSize: 11, display: 'block', marginTop: 3 }}>
                  ⚠️ Name is required — please enter a name above to enable saving.
                </span>
              )}
            </label>
            {schema && Object.entries(schema.properties || {}).map(([key, prop]) => {
              const isConnStr = ['dsn','uri','connection_string','connectionString'].includes(key) || (prop.description && prop.description.toLowerCase().includes('connection string'))
              return (
              <label key={key}>
                {prop.title || key}
                {prop.description && (
                  <span className="muted">
                    {' — '}{prop.description}
                    {key === 'base_url' && form.type === 'llm' && (
                      <span style={{ display: 'block', marginTop: 2, color: '#38bdf8' }}>
                        💡 Tip for OpenRouter: Use <code>https://openrouter.ai/api/v1</code>
                      </span>
                    )}
                  </span>
                )}
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
            <button
              className="primary"
              type="submit"
              disabled={busy || !form.type}
              title={!form.name.trim() ? 'Please enter a name for this credential' : ''}
              style={{ marginTop: 8 }}
            >
              {busy ? 'Saving…' : 'Save credential'}
            </button>
          </form>
        )}
      </section>

      <ConfirmDialog open={Boolean(deleteTarget)} title={`Delete “${deleteTarget?.name}”?`} description={deleteTarget && ['database','postgres','mysql','redis','mongodb'].includes(deleteTarget.type) ? 'The connection string will be permanently deleted. Workflows using this connection will fail until updated.' : 'This credential will be disconnected. Workflows referencing it will fail until updated.'} confirmLabel={deleteTarget && ['database','postgres','mysql','redis','mongodb'].includes(deleteTarget.type) ? 'Delete connection string' : 'Delete'} variant="danger" onCancel={() => setDeleteTarget(null)} onConfirm={async () => { try { await remove(deleteTarget.id); setNotice(deleteTarget && ['database','postgres','mysql','redis','mongodb'].includes(deleteTarget.type) ? 'Connection string deleted.' : 'Deleted.'); } catch(e){ setError(e.message)} finally{ setDeleteTarget(null) } }} />

      <ConfirmDialog
        open={Boolean(logoutTarget)}
        title={`Total Logout: Disconnect “${logoutTarget?.name}”?`}
        description={`This will completely revoke the active OAuth session and tokens with ${logoutTarget?.type?.toUpperCase()} on their servers, and remove the connection from Flowsmith. Workflows using this account will stop working until reconnected.`}
        confirmLabel="Logout & Revoke"
        variant="danger"
        onCancel={() => setLogoutTarget(null)}
        onConfirm={async () => {
          const target = logoutTarget
          try {
            const res = await logout(target.id)
            setNotice(
              <span>
                {res?.message || `Logged out and revoked ${target.name}.`}
                {res?.logout_url && (
                  <span style={{ marginLeft: 8 }}>
                    · <a
                        href={res.logout_url}
                        target="_blank"
                        rel="noreferrer"
                        style={{ color: '#60a5fa', textDecoration: 'underline', fontWeight: 600 }}
                      >
                        Sign out of {target.type === 'salesforce' ? 'Salesforce' : 'provider'} browser session ↗
                      </a>
                  </span>
                )}
              </span>
            )
            await load()
          } catch (e) {
            setError(e.message || 'Logout failed.')
          } finally {
            setLogoutTarget(null)
          }
        }}
      />
    </div>
  )
}
