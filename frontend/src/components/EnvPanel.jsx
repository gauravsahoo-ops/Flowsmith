// EnvPanel: workspace-scoped environment variables (Phase 31/32).
// Values are encrypted at rest; secrets are masked in listings and only
// the workspace creator can add/change/delete them (members can read).

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

export default function EnvPanel({ open, onClose }) {
  const [workspaces, setWorkspaces] = useState([])
  const [wsId, setWsId] = useState('')
  const [vars, setVars] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [form, setForm] = useState({ key: '', value: '', is_secret: false })
  const [busy, setBusy] = useState(false)

  const loadWorkspaces = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.listWorkspaces()
      setWorkspaces(data || [])
      if (data?.length && !wsId) setWsId(data[0].id)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadVars = useCallback(async (id) => {
    if (!id) {
      setVars([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await api.listEnvVars(id)
      setVars(data || [])
    } catch (err) {
      setError(err.message)
      setVars([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) loadWorkspaces()
  }, [open, loadWorkspaces])

  useEffect(() => {
    if (open) loadVars(wsId)
  }, [open, wsId, loadVars])

  async function save(e) {
    e.preventDefault()
    if (!form.key.trim()) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await api.upsertEnvVar({
        workspace_id: wsId,
        key: form.key.trim(),
        value: form.value,
        is_secret: form.is_secret,
      })
      setNotice(`Saved “${form.key.trim()}”.`)
      setForm({ key: '', value: '', is_secret: false })
      await loadVars(wsId)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(v) {
    if (!window.confirm(`Delete variable “${v.key}”?`)) return
    setError(null)
    try {
      await api.deleteEnvVar(v.id)
      await loadVars(wsId)
    } catch (err) {
      setError(err.message)
    }
  }

  if (!open) return null

  return (
    <aside className="panel envpanel">
      <header>
        <h2>Environment</h2>
        <button className="ghost" onClick={onClose} title="Close">
          ✕
        </button>
      </header>
      <p className="hint">
        Per-workspace variables usable as <code>{'{{ $env.KEY }}'}</code> in any field.
        Secrets are encrypted at rest and never shown again.
      </p>
      <label className="env-ws-select">
        Workspace
        <select value={wsId} onChange={(e) => setWsId(e.target.value)}>
          {workspaces.length === 0 && <option value="">No workspaces yet</option>}
          {workspaces.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      </label>
      {error && <div className="banner-inline err">{error}</div>}
      {notice && <div className="banner-inline ok">{notice}</div>}

      {wsId && (
        <form className="env-form" onSubmit={save}>
          <input
            placeholder="KEY"
            value={form.key}
            onChange={(e) => setForm({ ...form, key: e.target.value.toUpperCase() })}
            disabled={busy}
          />
          <input
            placeholder="value"
            value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })}
            disabled={busy}
          />
          <label className="env-secret">
            <input
              type="checkbox"
              checked={form.is_secret}
              onChange={(e) => setForm({ ...form, is_secret: e.target.checked })}
            />
            secret
          </label>
          <button className="primary" type="submit" disabled={busy || !form.key.trim()}>
            Save
          </button>
        </form>
      )}

      {!loading && vars.length === 0 && wsId && <p className="hint">No variables in this workspace.</p>}
      <div className="env-list">
        {vars.map((v) => (
          <div key={v.id} className={`env-row ${v.is_secret ? 'is-secret' : ''}`}>
            <span className="env-key">{v.key}</span>
            <span className="env-value" title={v.is_secret ? 'masked' : v.value}>
              {v.is_secret ? '••••••' : v.value}
            </span>
            <button
              className="ghost"
              onClick={() => remove(v)}
              title="Delete variable"
              disabled={loading}
            >
              🗑
            </button>
          </div>
        ))}
      </div>
      {workspaces.length === 0 && !loading && (
        <p className="hint">Create a workspace first (API or admin), then its variables appear here.</p>
      )}
    </aside>
  )
}
