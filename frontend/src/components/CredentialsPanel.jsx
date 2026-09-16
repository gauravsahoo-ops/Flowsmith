// CredentialsPanel: manage stored credentials (spec 12). Secrets are
// entered here, stored encrypted, and never fetched back. The Salesforce
// type uses the 'Connect Salesforce' OAuth flow instead of manual entry:
// the user authorizes with their own Salesforce account and the backend
// stores the encrypted connection (client id/secret stay server-side).

import { useEffect, useRef, useState } from 'react'
import api from '../api'
import { useCredentialStore } from '../stores/credentialStore'
import ErrorState from './shared/ErrorState'
import Select from './shared/Select'

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

function isSalesforce(cred) {
  return cred.type === 'salesforce'
}

export default function CredentialsPanel({ open, onClose }) {
  const credentials = useCredentialStore((s) => s.credentials)
  const types = useCredentialStore((s) => s.types)
  const load = useCredentialStore((s) => s.load)
  const create = useCredentialStore((s) => s.create)
  const remove = useCredentialStore((s) => s.remove)
  const connectOAuth = useCredentialStore((s) => s.connectOAuth)

  const [form, setForm] = useState({ name: '', type: '', data: {} })
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [sfBusy, setSfBusy] = useState(false)
  const [hsBusy, setHsBusy] = useState(false)
  const [sfOrgUrl, setSfOrgUrl] = useState('')
  const [sfAdvExpanded, setSfAdvExpanded] = useState(false)
  const [reconnectingId, setReconnectingId] = useState(null)
  const popupRef = useRef(null)
  const msgHandlerRef = useRef(null)

  useEffect(() => {
    if (open) load()
  }, [open, load])

  useEffect(() => {
    const handler = (event) => {
      const msg = event.data
      // Legacy Salesforce marker + generic provider marker (Phase 33).
      if (!msg || (msg.source !== 'salesforce-oauth' && msg.source !== 'oauth')) return
      if (msg.ok) {
        setNotice(msg.message || `${msg.provider || 'Salesforce'} connected. Your encrypted connection is ready to use.`)
      } else {
        setError(msg.error || `${msg.provider || 'Provider'} authorization failed.`)
      }
      if (popupRef.current && !popupRef.current.closed) popupRef.current.close()
      popupRef.current = null
      setSfBusy(false)
      setHsBusy(false)
      if (msg.ok) load()
    }
    msgHandlerRef.current = handler
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [load])

  useEffect(() => {
    if (!open) {
      setError(null)
      setNotice(null)
      setSfBusy(false)
      setHsBusy(false)
      setReconnectingId(null)
    }
  }, [open])

  if (!open) return null

  const schema = types.find((t) => t.type === form.type)?.parameters_schema
  const secretFields = new Set(types.find((t) => t.type === form.type)?.secret_fields || [])

  async function handleSmartReconnect(c, provider, loginUrl) {
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
      runConnect(provider, loginUrl)
    } catch {
      runConnect(provider, loginUrl)
    } finally {
      setReconnectingId(null)
    }
  }

  async function runConnect(provider, loginUrl) {
    setError(null)
    setNotice(null)
    if (provider === 'salesforce') setSfBusy(true)
    else setHsBusy(true)
    try {
      const { authorizeUrl } = await connectOAuth(provider, loginUrl)
      const w = window.open(authorizeUrl, `oauth-${provider}`, 'width=520,height=640')
      if (!w) {
        setError('Popup blocked. Allow popups for this site, or copy the authorization link below.')
        if (provider === 'salesforce') setSfBusy(false)
        else setHsBusy(false)
        return
      }
      popupRef.current = w
    } catch (err) {
      setError(err.message || `Could not start ${provider} connection.`)
      if (provider === 'salesforce') setSfBusy(false)
      else setHsBusy(false)
    }
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await create({ name: form.name, type: form.type, data: form.data })
      setForm({ name: '', type: '', data: {} })
      setNotice('Credential saved.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const salesforceType = types.find((t) => t.type === 'salesforce')
  const hubspotType = types.find((t) => t.type === 'hubspot')
  const sfConnections = credentials.filter(isSalesforce)
  const hsConnections = credentials.filter((c) => c.type === 'hubspot')
  const formTypeIsSalesforce = form.type === 'salesforce'
  const formTypeIsHubspot = form.type === 'hubspot'

  return (
    <div className="overlay" onClick={onClose}>
      <div className="credentials-panel" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Credentials</h2>
          <button className="ghost" onClick={onClose}>
            ✕
          </button>
        </header>

        {error && <ErrorState icon="🔒" title="Credential error" description={error} />}
        {notice && <div className="banner ok">{notice}</div>}

        <div className="cred-list">
          {credentials.length === 0 && <p className="hint">No credentials yet.</p>}
          {credentials.map((c) => (
            <div key={c.id} className="cred-row">
              <div>
                <strong>{c.name}</strong>
                <span className="muted"> {c.type}</span>
                {isSalesforce(c) && (
                  <span className="sf-dot" title="Connected via OAuth">●</span>
                )}
              </div>
              <div className="cred-actions">
                {isSalesforce(c) && (
                  <button
                    className="ghost"
                    onClick={() => handleSmartReconnect(c, 'salesforce', sfOrgUrl || undefined)}
                    disabled={reconnectingId === c.id}
                    title="Reconnect"
                  >
                    {reconnectingId === c.id ? 'Reconnecting…' : '↻ Reconnect'}
                  </button>
                )}
                {c.type === 'hubspot' && (
                  <button
                    className="ghost"
                    onClick={() => handleSmartReconnect(c, 'hubspot')}
                    disabled={reconnectingId === c.id}
                    title="Reconnect"
                  >
                    {reconnectingId === c.id ? 'Reconnecting…' : '↻ Reconnect'}
                  </button>
                )}
                {c.type === 'google_calendar' && (
                  <button
                    className="ghost"
                    onClick={() => handleSmartReconnect(c, 'google_calendar')}
                    disabled={reconnectingId === c.id}
                    title="Reconnect"
                  >
                    {reconnectingId === c.id ? 'Reconnecting…' : '↻ Reconnect'}
                  </button>
                )}
                {c.type === 'google_sheets' && (
                  <button
                    className="ghost"
                    onClick={() => handleSmartReconnect(c, 'google_sheets')}
                    disabled={reconnectingId === c.id}
                    title="Reconnect"
                  >
                    {reconnectingId === c.id ? 'Reconnecting…' : '↻ Reconnect'}
                  </button>
                )}
                {c.type === 'gmail' && (
                  <button
                    className="ghost"
                    onClick={() => handleSmartReconnect(c, 'gmail')}
                    disabled={reconnectingId === c.id}
                    title="Reconnect"
                  >
                    {reconnectingId === c.id ? 'Reconnecting…' : '↻ Reconnect'}
                  </button>
                )}
                {c.type === 'google_drive' && (
                  <button
                    className="ghost"
                    onClick={() => handleSmartReconnect(c, 'google_drive')}
                    disabled={reconnectingId === c.id}
                    title="Reconnect"
                  >
                    {reconnectingId === c.id ? 'Reconnecting…' : '↻ Reconnect'}
                  </button>
                )}
                <button className="ghost" onClick={() => remove(c.id)} title={['database','postgres','mysql','redis','mongodb'].includes(c.type) ? 'Delete connection string' : 'Disconnect / delete'}>
                  {['database','postgres','mysql','redis','mongodb'].includes(c.type) ? '🗑 Delete connection string' : '🗑'}
                </button>
              </div>
            </div>
          ))}
        </div>

        <h3>New credential</h3>

        {hubspotType && formTypeIsHubspot && (
          <div className="sf-connect-box">
            <p className="hint">
              Connect your HubSpot account. You authorize with your own login — the refresh
              token is stored encrypted and app credentials stay on the server.
            </p>
            <button
              className="primary"
              onClick={() => runConnect('hubspot')}
              disabled={hsBusy}
            >
              {hsBusy ? 'Connecting…' : hsConnections.length > 0 ? '↻ Reconnect HubSpot' : 'Connect HubSpot'}
            </button>
          </div>
        )}

        {types.find((t) => t.type === 'google_calendar') && form.type === 'google_calendar' && (
          <div className="sf-connect-box">
            <p className="hint">
              Connect your Google account (offline access — refresh token stored encrypted,
              app credentials stay on the server).
            </p>
            <button
              className="primary"
              onClick={() => runConnect('google_calendar')}
              disabled={hsBusy}
            >
              {hsBusy ? 'Connecting…' : 'Connect Google Calendar'}
            </button>
          </div>
        )}

        {types.find((t) => t.type === 'google_sheets') && form.type === 'google_sheets' && (
          <div className="sf-connect-box">
            <p className="hint">
              Connect your Google account for Sheets (offline access — refresh token stored encrypted).
            </p>
            <button
              className="primary"
              onClick={() => runConnect('google_sheets')}
              disabled={hsBusy}
            >
              {hsBusy ? 'Connecting…' : 'Connect Google Sheets'}
            </button>
          </div>
        )}

        {types.find((t) => t.type === 'gmail') && form.type === 'gmail' && (
          <div className="sf-connect-box">
            <p className="hint">
              Connect Gmail with send-only permission (refresh token stored encrypted,
              app credentials stay on the server).
            </p>
            <button
              className="primary"
              onClick={() => runConnect('gmail')}
              disabled={hsBusy}
            >
              {hsBusy ? 'Connecting…' : 'Connect Gmail'}
            </button>
          </div>
        )}

        {types.find((t) => t.type === 'google_drive') && form.type === 'google_drive' && (
          <div className="sf-connect-box">
            <p className="hint">
              Connect your Google account for Drive (offline access — refresh token stored
              encrypted, app credentials stay on the server).
            </p>
            <button
              className="primary"
              onClick={() => runConnect('google_drive')}
              disabled={hsBusy}
            >
              {hsBusy ? 'Connecting…' : 'Connect Google Drive'}
            </button>
          </div>
        )}

        {salesforceType && formTypeIsSalesforce && (
          <div className="sf-connect-box">
            <p className="hint">
              Connect your Salesforce account. You will authorize with your own login —
              no app credentials needed here.
            </p>
            <button
              className="primary"
              onClick={() => runConnect('salesforce', sfOrgUrl || undefined)}
              disabled={sfBusy}
            >
              {sfBusy ? 'Connecting…' : sfConnections.length > 0 ? '↻ Reconnect Salesforce' : 'Connect Salesforce'}
            </button>
            <button
              className="ghost"
              onClick={() => setSfAdvExpanded((v) => !v)}
              style={{ marginTop: 6 }}
            >
              {sfAdvExpanded ? 'Hide' : 'Use a different org login URL'}
            </button>
            {sfAdvExpanded && (
              <div style={{ marginTop: 6 }}>
                <input
                  value={sfOrgUrl}
                  onChange={(e) => setSfOrgUrl(e.target.value)}
                  placeholder="https://login.salesforce.com"
                />
              </div>
            )}
          </div>
        )}

        <form onSubmit={submit}>
          <label>
            Name
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </label>
          <label>
            Type
            <Select
              searchable
              value={form.type}
              onChange={(v) =>
                setForm({
                  ...form,
                  type: v,
                  data: defaultsFromSchema(
                    types.find((t) => t.type === v)?.parameters_schema,
                  ),
                })
              }
              options={types.map((t) => ({ value: t.type, label: `${t.name} (${t.type})` }))}
              placeholder="Select…"
            />
          </label>

          {schema && !formTypeIsSalesforce && (
            Object.entries(schema.properties || {}).map(([key, prop]) => {
              const isConnStr = ['dsn','uri','connection_string','connectionString'].includes(key) || (prop.description && prop.description.toLowerCase().includes('connection string'))
              return (
              <label key={key}>
                {prop.title || key}
                {prop.description && <span className="muted"> — {prop.description}</span>}
                {prop.type === 'boolean' ? (
                  <input
                    type="checkbox"
                    checked={Boolean(form.data[key])}
                    onChange={(e) =>
                      setForm({ ...form, data: { ...form.data, [key]: e.target.checked } })
                    }
                  />
                ) : (
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <input
                      style={{ flex: 1 }}
                      type={
                        secretFields.has(key)
                          ? 'password'
                          : prop.type === 'number' || prop.type === 'integer'
                            ? 'number'
                            : 'text'
                      }
                      value={form.data[key] ?? ''}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          data: {
                            ...form.data,
                            [key]:
                              prop.type === 'number' || prop.type === 'integer'
                                ? Number(e.target.value)
                                : e.target.value,
                          },
                        })
                      }
                    />
                    {isConnStr && form.data[key] && (
                      <button type="button" className="ghost small" onClick={() => setForm({ ...form, data: { ...form.data, [key]: '' } })} title="Clear connection string">🗑 Clear</button>
                    )}
                  </div>
                )}
              </label>
              )
            })
          )}

          {!formTypeIsSalesforce && (
            <button className="primary" type="submit" disabled={busy}>
              Save credential
            </button>
          )}
        </form>
      </div>
    </div>
  )
}