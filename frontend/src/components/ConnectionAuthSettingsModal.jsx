import { useEffect, useState } from 'react'
import { api } from '../api'

export default function ConnectionAuthSettingsModal({ isOpen, onClose, credential, onReconnected, onTested }) {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [recovering, setRecovering] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [policy, setPolicy] = useState(null)
  const [history, setHistory] = useState([])
  const [activeTab, setActiveTab] = useState('policy') // 'policy' | 'history'

  const [mode, setMode] = useState('automatic')
  const [notifyInApp, setNotifyInApp] = useState(true)
  const [notifyEmail, setNotifyEmail] = useState(true)
  const [notifyOnFailure, setNotifyOnFailure] = useState(true)
  const [notifyOnExpiry, setNotifyOnExpiry] = useState(true)

  useEffect(() => {
    if (!isOpen || !credential) return
    let alive = true
    setLoading(true)
    setError(null)
    setNotice(null)

    Promise.allSettled([
      api.getCredentialPolicy(credential.id),
      api.getCredentialHistory(credential.id),
    ]).then(([polRes, histRes]) => {
      if (!alive) return
      if (polRes.status === 'fulfilled' && polRes.value) {
        const p = polRes.value
        setPolicy(p)
        setMode(p.mode || 'automatic')
        setNotifyInApp(p.notify_in_app ?? true)
        setNotifyEmail(p.notify_email ?? true)
        setNotifyOnFailure(p.notify_on_recovery_failure ?? true)
        setNotifyOnExpiry(p.notify_on_upcoming_expiry ?? true)
      }
      if (histRes.status === 'fulfilled' && histRes.value?.history) {
        setHistory(histRes.value.history)
      }
      setLoading(false)
    })

    return () => {
      alive = false
    }
  }, [isOpen, credential])

  if (!isOpen || !credential) return null

  async function handleSave(e) {
    e?.preventDefault()
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const updated = await api.updateCredentialPolicy(credential.id, {
        mode,
        notify_in_app: notifyInApp,
        notify_email: notifyEmail,
        notify_on_recovery_failure: notifyOnFailure,
        notify_on_upcoming_expiry: notifyOnExpiry,
      })
      setPolicy(p => ({ ...p, ...updated }))
      setNotice('Authentication recovery settings saved successfully.')
      setTimeout(() => setNotice(null), 3000)
    } catch (err) {
      setError(err.message || 'Failed to update settings')
    } finally {
      setSaving(false)
    }
  }

  async function handleTestConnection() {
    setTesting(true)
    setError(null)
    setNotice(null)
    try {
      const res = await api.testCredential(credential.id)
      if (res.ok) {
        setNotice(`Connection verified: ${res.message || 'Authentication valid and healthy.'}`)
        if (onTested) onTested(res)
      } else {
        setError(`Connection test failed: ${res.message || 'Invalid authentication.'}`)
      }
    } catch (err) {
      setError(err.message || 'Test failed')
    } finally {
      setTesting(false)
    }
  }

  async function handleRecoverNow() {
    setRecovering(true)
    setError(null)
    setNotice(null)
    try {
      const res = await api.recoverCredential(credential.id)
      if (res.ok) {
        setNotice(`Credential renewed successfully. State: ${res.state}`)
        // Refresh policy & history
        const p = await api.getCredentialPolicy(credential.id).catch(() => null)
        if (p) setPolicy(p)
        const h = await api.getCredentialHistory(credential.id).catch(() => null)
        if (h?.history) setHistory(h.history)
        if (onReconnected) onReconnected()
      } else {
        setError(`Recovery attempt: ${res.message} (${res.code || res.state})`)
      }
    } catch (err) {
      setError(err.message || 'Recovery failed')
    } finally {
      setRecovering(false)
    }
  }

  const caps = policy?.capabilities || {}

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card"
        style={{ maxWidth: 680, width: '92%', maxHeight: '90vh', overflowY: 'auto' }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border, #334155)', paddingBottom: 14, marginBottom: 16 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 18, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: 10 }}>
              <span>Authentication &amp; Recovery Settings</span>
              <span className="badge" style={{ fontSize: 11, background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}>
                {credential.type}
              </span>
            </h3>
            <p className="hint" style={{ margin: '4px 0 0 0', fontSize: 12 }}>
              Connection: <strong style={{ color: '#e2e8f0' }}>{credential.name}</strong>
            </p>
          </div>
          <button type="button" className="ghost small" onClick={onClose} style={{ fontSize: 18, lineHeight: 1 }}>
            ✕
          </button>
        </div>

        {error && <div className="banner-inline err" style={{ marginBottom: 14 }}>{error}</div>}
        {notice && <div className="banner-inline ok" style={{ marginBottom: 14 }}>{notice}</div>}

        {/* Tab selection */}
        <div style={{ display: 'flex', gap: 8, borderBottom: '1px solid rgba(255,255,255,0.06)', marginBottom: 16 }}>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'policy' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('policy')}
            style={{
              padding: '8px 16px',
              border: 'none',
              background: 'transparent',
              color: activeTab === 'policy' ? '#818cf8' : '#94a3b8',
              borderBottom: activeTab === 'policy' ? '2px solid #818cf8' : '2px solid transparent',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            Recovery Policy
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'history' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('history')}
            style={{
              padding: '8px 16px',
              border: 'none',
              background: 'transparent',
              color: activeTab === 'history' ? '#818cf8' : '#94a3b8',
              borderBottom: activeTab === 'history' ? '2px solid #818cf8' : '2px solid transparent',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: 13,
            }}
          >
            Audit Trail ({history.length})
          </button>
        </div>

        {loading ? (
          <div style={{ padding: '30px', textAlign: 'center', color: '#94a3b8' }}>Loading policy…</div>
        ) : activeTab === 'policy' ? (
          <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            {/* Health & State Summary Box */}
            <div
              style={{
                borderRadius: 8,
                background: 'rgba(255,255,255,0.02)',
                border: '1px solid rgba(255,255,255,0.06)',
                padding: '12px 16px',
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: 12,
              }}
            >
              <div>
                <div style={{ fontSize: 11, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Current State</div>
                <div style={{ fontSize: 13.5, fontWeight: 700, marginTop: 3, color: '#f8fafc' }}>
                  {policy?.state || 'CONNECTED'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Last Authenticated</div>
                <div style={{ fontSize: 12, color: '#cbd5e1', marginTop: 3 }}>
                  {policy?.last_authenticated_at ? new Date(policy.last_authenticated_at).toLocaleTimeString() : 'Recently'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Consecutive Failures</div>
                <div style={{ fontSize: 13.5, fontWeight: 700, marginTop: 3, color: policy?.consecutive_failures > 0 ? '#f87171' : '#34d399' }}>
                  {policy?.consecutive_failures || 0}
                </div>
              </div>
            </div>

            {/* Recovery Mode Selector */}
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>
                Authentication Recovery Mode
              </label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {/* 1. Automatic recovery */}
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 12,
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: mode === 'automatic' ? 'rgba(99,102,241,0.08)' : 'rgba(255,255,255,0.02)',
                    border: mode === 'automatic' ? '1px solid rgba(99,102,241,0.4)' : '1px solid rgba(255,255,255,0.06)',
                    cursor: 'pointer',
                  }}
                >
                  <input
                    type="radio"
                    name="recovery_mode"
                    value="automatic"
                    checked={mode === 'automatic'}
                    onChange={() => setMode('automatic')}
                    style={{ marginTop: 2, accentColor: '#6366f1' }}
                  />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 13, color: '#f8fafc' }}>
                      Automatic Recovery (Recommended)
                    </div>
                    <div className="hint" style={{ fontSize: 11.5, marginTop: 2 }}>
                      Automatically refresh access tokens and reacquire credentials in the background before workflows fail, even if Flowsmith is closed.
                    </div>
                  </div>
                </label>

                {/* 2. Automatic with notifications */}
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 12,
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: mode === 'automatic_with_notifications' ? 'rgba(99,102,241,0.08)' : 'rgba(255,255,255,0.02)',
                    border: mode === 'automatic_with_notifications' ? '1px solid rgba(99,102,241,0.4)' : '1px solid rgba(255,255,255,0.06)',
                    cursor: 'pointer',
                  }}
                >
                  <input
                    type="radio"
                    name="recovery_mode"
                    value="automatic_with_notifications"
                    checked={mode === 'automatic_with_notifications'}
                    onChange={() => setMode('automatic_with_notifications')}
                    style={{ marginTop: 2, accentColor: '#6366f1' }}
                  />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 13, color: '#f8fafc' }}>
                      Automatic Recovery with Notifications
                    </div>
                    <div className="hint" style={{ fontSize: 11.5, marginTop: 2 }}>
                      Attempt background recovery silently; send in-app and email alerts if provider outage or user consent is required.
                    </div>
                  </div>
                </label>

                {/* 3. Manual authentication */}
                <label
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 12,
                    padding: '12px 14px',
                    borderRadius: 8,
                    background: mode === 'manual' ? 'rgba(249,115,22,0.08)' : 'rgba(255,255,255,0.02)',
                    border: mode === 'manual' ? '1px solid rgba(249,115,22,0.4)' : '1px solid rgba(255,255,255,0.06)',
                    cursor: 'pointer',
                  }}
                >
                  <input
                    type="radio"
                    name="recovery_mode"
                    value="manual"
                    checked={mode === 'manual'}
                    onChange={() => setMode('manual')}
                    style={{ marginTop: 2, accentColor: '#f97316' }}
                  />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 13, color: '#f8fafc' }}>
                      Manual Authentication Only
                    </div>
                    <div className="hint" style={{ fontSize: 11.5, marginTop: 2 }}>
                      Strict security mode: Never automatically refresh credentials in background. Workflows pause safely in <code>waiting_auth</code> until you explicitly reconnect.
                    </div>
                  </div>
                </label>
              </div>
            </div>

            {/* Notification Preferences */}
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 700, color: '#e2e8f0', marginBottom: 8 }}>
                Notification Preferences
              </label>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: '#cbd5e1', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={notifyInApp}
                    onChange={e => setNotifyInApp(e.target.checked)}
                    style={{ accentColor: '#6366f1' }}
                  />
                  <span>In-app notifications</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: '#cbd5e1', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={notifyEmail}
                    onChange={e => setNotifyEmail(e.target.checked)}
                    style={{ accentColor: '#6366f1' }}
                  />
                  <span>Email notifications</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: '#cbd5e1', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={notifyOnFailure}
                    onChange={e => setNotifyOnFailure(e.target.checked)}
                    style={{ accentColor: '#6366f1' }}
                  />
                  <span>Alert on recovery failure</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: '#cbd5e1', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={notifyOnExpiry}
                    onChange={e => setNotifyOnExpiry(e.target.checked)}
                    style={{ accentColor: '#6366f1' }}
                  />
                  <span>Alert on upcoming expiry</span>
                </label>
              </div>
            </div>

            {/* Provider Capabilities Summary */}
            <div style={{ padding: '12px 14px', borderRadius: 8, background: 'rgba(255,255,255,0.015)', border: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#94a3b8', marginBottom: 8 }}>
                Provider Capabilities ({credential.type})
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                <span className="badge" style={{ fontSize: 11, background: caps.supports_refresh ? 'rgba(16,185,129,0.1)' : 'rgba(148,163,184,0.1)', color: caps.supports_refresh ? '#34d399' : '#94a3b8' }}>
                  {caps.supports_refresh ? '✓ OAuth Refresh' : '✗ No Refresh Token'}
                </span>
                <span className="badge" style={{ fontSize: 11, background: caps.supports_rotation ? 'rgba(16,185,129,0.1)' : 'rgba(148,163,184,0.1)', color: caps.supports_rotation ? '#34d399' : '#94a3b8' }}>
                  {caps.supports_rotation ? '✓ Refresh Token Rotation' : '✗ No Rotation'}
                </span>
                <span className="badge" style={{ fontSize: 11, background: caps.supports_client_credentials ? 'rgba(56,189,248,0.1)' : 'rgba(148,163,184,0.1)', color: caps.supports_client_credentials ? '#38bdf8' : '#94a3b8' }}>
                  {caps.supports_client_credentials ? '✓ S2S Service Principal' : '✗ Interactive User Flow'}
                </span>
              </div>
            </div>

            {/* Action Buttons */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  className="secondary small"
                  onClick={handleTestConnection}
                  disabled={testing || recovering || saving}
                >
                  {testing ? 'Testing…' : 'Test Connection'}
                </button>
                <button
                  type="button"
                  className="secondary small"
                  onClick={handleRecoverNow}
                  disabled={testing || recovering || saving}
                  title="Force immediate token refresh and recovery test"
                >
                  {recovering ? 'Recovering…' : 'Force Recover Token'}
                </button>
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" className="ghost small" onClick={onClose}>
                  Cancel
                </button>
                <button type="submit" className="primary small" disabled={saving}>
                  {saving ? 'Saving…' : 'Save Settings'}
                </button>
              </div>
            </div>
          </form>
        ) : (
          /* Audit History Tab */
          <div>
            {history.length === 0 ? (
              <p className="hint" style={{ textAlign: 'center', padding: '30px' }}>No recovery events recorded yet.</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table" style={{ fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Event</th>
                      <th>Transition</th>
                      <th>Actor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map(ev => (
                      <tr key={ev.id}>
                        <td className="muted">
                          {ev.created_at ? new Date(ev.created_at).toLocaleTimeString() : '—'}
                        </td>
                        <td>
                          <strong style={{ color: '#f8fafc' }}>{ev.event_type}</strong>
                        </td>
                        <td>
                          <code>{ev.previous_state || 'none'} → {ev.new_state}</code>
                        </td>
                        <td className="muted">{ev.actor}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
