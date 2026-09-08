import { useEffect, useState } from 'react'
import { api, getToken } from '../api'
import PageHeader from '../components/shared/PageHeader'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'

function Section({ title, description, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="settings-section">
      <button className="settings-section-head" onClick={() => setOpen(v => !v)} aria-expanded={open}>
        <span style={{ fontSize: 13, color: '#818cf8', transition: 'transform 0.2s', display: 'inline-block', transform: open ? 'rotate(90deg)' : 'none' }}>
          ▶
        </span>
        <span className="settings-section-title">{title}</span>
      </button>
      {description && <p className="hint" style={{ margin: '4px 0 0 20px', fontSize: 12.5, lineHeight: 1.5 }}>{description}</p>}
      {open && <div className="settings-section-body">{children}</div>}
    </section>
  )
}

export default function SettingsPage() {
  const [profile, setProfile] = useState(null)
  const [workspaces, setWorkspaces] = useState([])
  const [orgs, setOrgs] = useState([])
  const [apikeys, setApikeys] = useState([])
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [newKeyName, setNewKeyName] = useState('')
  const [newKey, setNewKey] = useState(null)
  const [keyBusy, setKeyBusy] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    Promise.allSettled([
      api.getHealth().catch(() => null),
      api.getMe().catch(() => null),
      api.listWorkspaces().catch(() => []),
      api.listOrganizations().catch(() => []),
      api.listApiKeys().catch(() => []),
    ]).then(([hl, me, ws, og, ak]) => {
      if (!alive) return
      if (hl.status === 'fulfilled' && hl.value) setHealth(hl.value)
      if (ws.status === 'fulfilled') setWorkspaces(Array.isArray(ws.value) ? ws.value : [])
      if (og.status === 'fulfilled') setOrgs(Array.isArray(og.value) ? og.value : [])
      if (ak.status === 'fulfilled') setApikeys(Array.isArray(ak.value) ? ak.value : [])

      if (me.status === 'fulfilled' && me.value) {
        setProfile(me.value)
      } else {
        try {
          const token = getToken()
          if (token) {
            const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
            setProfile(payload)
          }
        } catch {}
      }
      setLoading(false)
    })
    return () => { alive = false }
  }, [])

  async function createKey(e) {
    e.preventDefault()
    if (!newKeyName.trim()) return
    setError(null)
    setKeyBusy(true)
    try {
      const res = await api.createApiKey(newKeyName.trim())
      if (res?.key) {
        setNewKey(res)
        setNewKeyName('')
      }
      const updated = await api.listApiKeys().catch(() => [])
      setApikeys(updated || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setKeyBusy(false)
    }
  }

  async function revokeKey(id) {
    if (!window.confirm('Revoke this API key? Applications using it will lose access immediately.')) return
    try {
      await api.revokeApiKey(id)
      const updated = await api.listApiKeys().catch(() => [])
      setApikeys(updated || [])
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) return <div className="page settings-page"><PageHeader title="Settings" /><LoadingSkeleton rows={6} /></div>

  return (
    <div className="page settings-page">
      <PageHeader title="Settings" description="Manage your account, workspaces, organizations, and integrations." />

      {error && <div className="banner-inline err">{error}</div>}

      <Section title="General" description="Deployment and platform configuration.">
        <div className="settings-grid">
          <div className="settings-attr">
            <div className="settings-attr-label">App Version</div>
            <div className="settings-attr-value">v{health?.version || '0.3.1'}</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">System Uptime</div>
            <div className="settings-attr-value">{Math.floor((health?.uptime_s || 0) / 60)} minutes</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">Theme</div>
            <div className="settings-attr-value">Dark (Default)</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">API Endpoint Base</div>
            <div className="settings-attr-value"><code>/api</code></div>
          </div>
        </div>
      </Section>

      <Section title="Account" description="Your authenticated identity.">
        <div className="settings-grid">
          <div className="settings-attr">
            <div className="settings-attr-label">User ID</div>
            <div className="settings-attr-value">{profile?.id || profile?.sub || profile?.user_id || '1'}</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">Email Address</div>
            <div className="settings-attr-value">{profile?.email || 'user@example.com'}</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">Account Role</div>
            <div className="settings-attr-value">
              <span className="badge" style={{ background: 'rgba(99, 102, 241, 0.15)', color: '#818cf8', border: '1px solid rgba(99, 102, 241, 0.3)', textTransform: 'capitalize' }}>
                {profile?.role || 'user'}
              </span>
            </div>
          </div>
        </div>
      </Section>

      <Section title="Workspaces" description="Workspaces scope environment variables and workflows.">
        {workspaces.length === 0 ? <p className="hint">No workspaces yet.</p> : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Name</th><th>Workspace ID</th><th>Created</th></tr></thead>
              <tbody>
                {workspaces.map(w => (
                  <tr key={w.id}>
                    <td><strong style={{ color: '#f8fafc' }}>{w.name}</strong></td>
                    <td><code className="exec-id-cell">{w.id}</code></td>
                    <td className="muted">{new Date(w.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Organizations" description="Organizations own workspaces and team collaboration.">
        {orgs.length === 0 ? <p className="hint">No organizations yet.</p> : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Name</th><th>Organization ID</th></tr></thead>
              <tbody>
                {orgs.map(o => (
                  <tr key={o.id}>
                    <td><strong style={{ color: '#f8fafc' }}>{o.name}</strong></td>
                    <td><code className="exec-id-cell">{o.id}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="API Keys" description="Programmatic API tokens. The secret key is only revealed once upon creation.">
        <form onSubmit={createKey} className="inline-form">
          <input
            placeholder="Key name (e.g. CI/CD Pipeline)"
            value={newKeyName}
            onChange={e => setNewKeyName(e.target.value)}
            style={{ maxWidth: 300 }}
          />
          <button className="primary" type="submit" disabled={!newKeyName.trim() || keyBusy}>
            {keyBusy ? 'Creating…' : '＋ Create API Key'}
          </button>
        </form>
        {newKey && (
          <div className="banner-inline ok" style={{ marginTop: 10 }}>
            New key: <code>{newKey.key}</code> — copy it now, it will not be shown again.
          </div>
        )}
        {apikeys.length === 0 ? <p className="hint" style={{ marginTop: 10 }}>No active API keys.</p> : (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table className="data-table">
              <thead><tr><th>Name</th><th>Prefix</th><th>Created</th><th>Actions</th></tr></thead>
              <tbody>
                {apikeys.map(k => (
                  <tr key={k.id}>
                    <td><strong style={{ color: '#f8fafc' }}>{k.name}</strong></td>
                    <td><code>{k.prefix}…</code></td>
                    <td className="muted">{k.created_at ? new Date(k.created_at).toLocaleDateString() : '—'}</td>
                    <td>
                      <button className="ghost small" style={{ color: '#ef4444' }} onClick={() => revokeKey(k.id)}>Revoke</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Security & Compliance" description="Security architecture and credential storage.">
        <ul className="hint" style={{ lineHeight: 1.6, paddingLeft: 18, margin: '8px 0 0' }}>
          <li>Login rate-limiting enabled per-email and client IP (with 429 Retry-After protection)</li>
          <li>All third-party credentials encrypted at rest using AES-128-CBC / Fernet envelope encryption</li>
          <li>Session authentication backed by cryptographic JWT with sliding expiration</li>
        </ul>
      </Section>

      <Section title="Execution Engine" description="Durable job queue and worker architecture.">
        <ul className="hint" style={{ lineHeight: 1.6, paddingLeft: 18, margin: '8px 0 0' }}>
          <li>Every execution is scheduled through a durable queue with atomic worker claiming</li>
          <li>Automatic crash recovery: stale heartbeats are re-queued to prevent stuck executions</li>
          <li>Real-time node step progression streamed via WebSocket with reactive UI state</li>
        </ul>
      </Section>
    </div>
  )
}
