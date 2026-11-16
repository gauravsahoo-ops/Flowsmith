import { useCallback, useEffect, useState } from 'react'

import { api } from '../../api'
import { EMPTY_MCP_SERVER_FORM } from './mcpServerForm'

const EMPTY_FORM = EMPTY_MCP_SERVER_FORM

function splitTools(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function formFromServer(server) {
  return {
    name: server.name || '',
    endpoint: server.endpoint || '',
    transport: server.transport || 'http',
    auth_type: server.auth_type || 'none',
    credential_id: server.credential_id || '',
    description: server.description || '',
    trust_level: server.trust_level || 'untrusted',
    allowed_tools: (server.allowed_tools || []).join(', '),
    denied_tools: (server.denied_tools || []).join(', '),
    sandbox_backend: server.sandbox_backend || 'subprocess',
    sandbox_image: server.sandbox_image || '',
    sandbox_workspace_mode: server.sandbox_workspace_mode || 'none',
    sandbox_workspace_path: server.sandbox_workspace_path || '',
    sandbox_network: server.sandbox_network || 'none',
    sandbox_read_only: server.sandbox_read_only !== false,
  }
}

function fmtDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

export default function MCPServersPanel() {
  const [workspaces, setWorkspaces] = useState([])
  const [workspaceId, setWorkspaceId] = useState('')
  const [servers, setServers] = useState([])
  const [toolsByServer, setToolsByServer] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState('')
  const [form, setForm] = useState(EMPTY_FORM)
  const [busyId, setBusyId] = useState('')
  const [busyToolId, setBusyToolId] = useState('')

  useEffect(() => {
    let cancelled = false
    api
      .listWorkspaces()
      .then((rows) => {
        if (cancelled) return
        const list = Array.isArray(rows) ? rows : []
        setWorkspaces(list)
        setWorkspaceId((current) => current || list[0]?.id || '')
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load workspaces.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const refresh = useCallback(async () => {
    if (!workspaceId) {
      setServers([])
      return
    }
    setLoading(true)
    setError('')
    try {
      const rows = await api.listMCPServers(workspaceId)
      setServers(Array.isArray(rows) ? rows : [])
    } catch (err) {
      setError(err.message || 'Could not load MCP servers.')
    } finally {
      setLoading(false)
    }
  }, [workspaceId])

  useEffect(() => {
    refresh()
  }, [refresh])

  function updateForm(key, value) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function closeForm() {
    setShowForm(false)
    setEditingId('')
    setForm(EMPTY_FORM)
  }

  function startEdit(server) {
    setEditingId(server.id)
    setForm(formFromServer(server))
    setShowForm(true)
    setError('')
    setNotice('')
  }

  function sandboxPayload() {
    return {
      sandbox_backend: form.sandbox_backend || 'subprocess',
      sandbox_image: String(form.sandbox_image || '').trim(),
      sandbox_workspace_mode: form.sandbox_workspace_mode || 'none',
      sandbox_workspace_path:
        form.sandbox_workspace_mode === 'configured'
          ? String(form.sandbox_workspace_path || '').trim()
          : '',
      sandbox_network: String(form.sandbox_network || '').trim() || 'none',
      sandbox_read_only: Boolean(form.sandbox_read_only),
    }
  }

  async function submitServer(event) {
    event.preventDefault()
    if (!workspaceId) {
      setError('Select a workspace first.')
      return
    }
    setBusyId(editingId || 'create')
    setError('')
    setNotice('')
    const payload = {
      name: form.name.trim(),
      endpoint: form.endpoint.trim(),
      transport: form.transport,
      auth_type: form.auth_type,
      credential_id: form.credential_id.trim() || null,
      description: form.description.trim(),
      trust_level: form.trust_level,
      allowed_tools: splitTools(form.allowed_tools),
      denied_tools: splitTools(form.denied_tools),
      ...(form.transport === 'stdio' ? sandboxPayload() : {}),
    }
    try {
      if (editingId) {
        await api.updateMCPServer(editingId, payload)
        setNotice(`Updated ${payload.name}.`)
      } else {
        await api.createMCPServer({ workspace_id: workspaceId, ...payload })
        setNotice('MCP server registered.')
      }
      closeForm()
      await refresh()
    } catch (err) {
      setError(
        err.message ||
          (editingId
            ? 'Could not update MCP server.'
            : 'Could not create MCP server.'),
      )
    } finally {
      setBusyId('')
    }
  }

  async function toggleServer(server) {
    setBusyId(server.id)
    setError('')
    try {
      await api.updateMCPServer(server.id, { enabled: !server.enabled })
      await refresh()
    } catch (err) {
      setError(err.message || 'Could not update MCP server.')
    } finally {
      setBusyId('')
    }
  }

  async function deleteServer(server) {
    if (typeof window !== 'undefined' && !window.confirm(`Delete MCP server "${server.name}"?`)) {
      return
    }
    setBusyId(server.id)
    setError('')
    try {
      await api.deleteMCPServer(server.id)
      setNotice(`Deleted ${server.name}.`)
      await refresh()
    } catch (err) {
      setError(err.message || 'Could not delete MCP server.')
    } finally {
      setBusyId('')
    }
  }

  async function discoverTools(server) {
    setBusyId(server.id)
    setError('')
    setNotice('')
    try {
      const tools = await api.discoverMCPServerTools(server.id)
      setToolsByServer((current) => ({
        ...current,
        [server.id]: Array.isArray(tools) ? tools : [],
      }))
      setNotice(`Discovered tools for ${server.name}.`)
    } catch (err) {
      setError(err.message || 'Tool discovery failed.')
    } finally {
      setBusyId('')
    }
  }

  async function updateTool(server, tool, patch) {
    setBusyToolId(tool.id)
    setError('')
    try {
      const updated = await api.updateMCPTool(server.id, tool.id, patch)
      setToolsByServer((current) => ({
        ...current,
        [server.id]: (current[server.id] || []).map((row) =>
          row.id === updated.id ? updated : row,
        ),
      }))
    } catch (err) {
      setError(err.message || 'Could not update MCP tool policy.')
    } finally {
      setBusyToolId('')
    }
  }

  return (
    <section className="mcp-servers-panel" style={{ marginTop: 20 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
        <label className="hint" htmlFor="mcp-workspace">Workspace</label>
        <select
          id="mcp-workspace"
          value={workspaceId}
          onChange={(event) => setWorkspaceId(event.target.value)}
          style={{ minWidth: 240 }}
        >
          {workspaces.length === 0 && <option value="">No workspaces</option>}
          {workspaces.map((workspace) => (
            <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
          ))}
        </select>
        <button className="primary small" type="button" onClick={() => (showForm ? closeForm() : setShowForm(true))} disabled={!workspaceId}>
          {showForm ? 'Cancel' : 'Add MCP server'}
        </button>
        <button className="ghost small" type="button" onClick={refresh} disabled={loading || !workspaceId}>
          Refresh
        </button>
      </div>

      {error && <div className="banner-inline err">{error}</div>}
      {notice && <div className="banner-inline ok">{notice}</div>}

      {showForm && (
        <form onSubmit={submitServer} className="card" style={{ padding: 16, marginBottom: 16, display: 'grid', gap: 10 }}>
          <strong>{editingId ? 'Edit MCP server' : 'Register MCP server'}</strong>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
            <label>Name<input value={form.name} onChange={(e) => updateForm('name', e.target.value)} required maxLength={128} /></label>
            <label>Endpoint / command<input value={form.endpoint} onChange={(e) => updateForm('endpoint', e.target.value)} required placeholder="https://mcp.example.com or stdio command" /></label>
            <label>Transport
              <select value={form.transport} onChange={(e) => updateForm('transport', e.target.value)}>
                <option value="http">HTTP</option>
                <option value="sse">SSE</option>
                <option value="stdio">stdio</option>
              </select>
            </label>
            <label>Auth
              <select value={form.auth_type} onChange={(e) => updateForm('auth_type', e.target.value)}>
                <option value="none">None</option>
                <option value="bearer">Bearer credential</option>
                <option value="credential">Credential</option>
              </select>
            </label>
            {form.auth_type !== 'none' && (
              <label>Credential ID<input value={form.credential_id} onChange={(e) => updateForm('credential_id', e.target.value)} required placeholder="credential id" /></label>
            )}
            <label>Trust
              <select value={form.trust_level} onChange={(e) => updateForm('trust_level', e.target.value)}>
                <option value="untrusted">Untrusted</option>
                <option value="verified">Verified</option>
              </select>
            </label>
          </div>
          <label>Allowed tools (comma separated)<input value={form.allowed_tools} onChange={(e) => updateForm('allowed_tools', e.target.value)} placeholder="search, get_file" /></label>
          <label>Denied tools (comma separated)<input value={form.denied_tools} onChange={(e) => updateForm('denied_tools', e.target.value)} placeholder="delete_file" /></label>
          {form.transport === 'stdio' && (
            <div
              role="group"
              aria-label="Sandbox settings"
              style={{ display: 'grid', gap: 10, borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 10 }}
            >
              <strong style={{ fontSize: 13 }}>Sandbox</strong>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
                <label>Sandbox backend
                  <select value={form.sandbox_backend} onChange={(e) => updateForm('sandbox_backend', e.target.value)}>
                    <option value="subprocess">Subprocess (host)</option>
                    <option value="docker">Docker container</option>
                  </select>
                </label>
                {form.sandbox_backend === 'docker' && (
                  <label>Docker image
                    <input value={form.sandbox_image} onChange={(e) => updateForm('sandbox_image', e.target.value)} maxLength={255} placeholder="default from server settings" />
                  </label>
                )}
                {form.sandbox_backend === 'docker' && (
                  <label>Network
                    <input value={form.sandbox_network} onChange={(e) => updateForm('sandbox_network', e.target.value)} maxLength={64} placeholder="none" />
                  </label>
                )}
                {form.sandbox_backend === 'docker' && (
                  <label>Workspace mode
                    <select value={form.sandbox_workspace_mode} onChange={(e) => updateForm('sandbox_workspace_mode', e.target.value)}>
                      <option value="none">None</option>
                      <option value="ephemeral">Ephemeral (tmpfs)</option>
                      <option value="configured">Configured (read-only bind)</option>
                      <option value="inherit">Inherit global</option>
                    </select>
                  </label>
                )}
                {form.sandbox_backend === 'docker' && form.sandbox_workspace_mode === 'configured' && (
                  <label>Workspace path
                    <input value={form.sandbox_workspace_path} onChange={(e) => updateForm('sandbox_workspace_path', e.target.value)} required maxLength={2000} placeholder="/srv/mcp-workspace" />
                  </label>
                )}
              </div>
              {form.sandbox_backend === 'docker' && (
                <label className="hint" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                  <input
                    type="checkbox"
                    checked={Boolean(form.sandbox_read_only)}
                    onChange={(e) => updateForm('sandbox_read_only', e.target.checked)}
                  />
                  Read-only workspace
                </label>
              )}
              <p className="hint" style={{ margin: 0 }}>
                {form.sandbox_backend === 'docker'
                  ? 'Empty Docker fields fall back to the server MCP_STDIO settings. Image and network must still satisfy policy.'
                  : 'Subprocess runs on the host and requires an explicit production opt-in. Docker is never selected implicitly.'}
              </p>
            </div>
          )}
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="primary small" type="submit" disabled={busyId === (editingId || 'create')}>
              {busyId === (editingId || 'create')
                ? 'Saving…'
                : editingId
                  ? 'Save changes'
                  : 'Register'}
            </button>
            {editingId && (
              <button className="ghost small" type="button" onClick={closeForm}>
                Cancel
              </button>
            )}
          </div>
        </form>
      )}

      {!workspaceId ? (
        <p className="hint">Create a workspace before registering MCP servers.</p>
      ) : loading ? (
        <p className="hint">Loading MCP servers…</p>
      ) : servers.length === 0 ? (
        <div className="card" style={{ padding: 16 }}>
          <strong>No MCP servers registered</strong>
          <p className="hint" style={{ marginBottom: 0 }}>
            Register a server, allowlist its tools, and discover its schemas before an agent can call it.
          </p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {servers.map((server) => {
            const tools = toolsByServer[server.id]
            const busy = busyId === server.id
            return (
              <article key={server.id} className="card" style={{ padding: 16 }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                  <strong>{server.name}</strong>
                  <span className={`badge ${server.enabled ? 'ok' : 'muted'}`}>{server.enabled ? 'enabled' : 'disabled'}</span>
                  <span className="hint">{server.transport} · {server.auth_type} · {server.trust_level}</span>
                  <span className="hint" style={{ marginLeft: 'auto' }}>Updated {fmtDate(server.updated_at)}</span>
                </div>
                <p className="hint" style={{ margin: '8px 0' }}>{server.endpoint}</p>
                {server.description && <p style={{ margin: '6px 0' }}>{server.description}</p>}
                {server.transport === 'stdio' && (
                  <div className="hint" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    <span>Sandbox: {server.sandbox_backend || 'subprocess'}</span>
                    {server.sandbox_backend === 'docker' && (
                      <span>Image: {server.sandbox_image || 'server default'}</span>
                    )}
                    {server.sandbox_backend === 'docker' && (
                      <span>Workspace: {server.sandbox_workspace_mode || 'none'}</span>
                    )}
                    {server.sandbox_backend === 'docker' && (
                      <span>Network: {server.sandbox_network || 'none'}</span>
                    )}
                  </div>
                )}
                <div className="hint" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  <span>Allowed: {(server.allowed_tools || []).join(', ') || '—'}</span>
                  <span>Denied: {(server.denied_tools || []).join(', ') || '—'}</span>
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
                  <button className="ghost small" type="button" onClick={() => discoverTools(server)} disabled={busy}>
                    {busy ? 'Working…' : 'Discover tools'}
                  </button>
                  <button className="ghost small" type="button" onClick={() => startEdit(server)} disabled={busy}>
                    Edit
                  </button>
                  <button className="ghost small" type="button" onClick={() => toggleServer(server)} disabled={busy}>
                    {server.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button className="danger small" type="button" onClick={() => deleteServer(server)} disabled={busy}>
                    Delete
                  </button>
                </div>
                {Array.isArray(tools) && (
                  <div style={{ marginTop: 12, borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 10 }}>
                    <strong style={{ fontSize: 12 }}>Cached tools ({tools.length})</strong>
                    {tools.length === 0 ? (
                      <p className="hint" style={{ marginBottom: 0 }}>No tools returned.</p>
                    ) : (
                      <ul className="hint" style={{ margin: '6px 0 0 18px' }}>
                        {tools.map((tool) => (
                          <li key={tool.id || tool.tool_name} style={{ marginBottom: 6 }}>
                            <code>{tool.tool_name}</code> · {tool.risk_class}
                            {tool.enabled === false ? ' · disabled' : ''}
                            {tool.description ? ` — ${tool.description}` : ''}
                            {tool.id && (
                              <span style={{ marginLeft: 8, display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                                <label className="hint" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                                  <input
                                    type="checkbox"
                                    checked={tool.enabled !== false}
                                    disabled={busyToolId === tool.id}
                                    onChange={() => updateTool(server, tool, { enabled: tool.enabled === false })}
                                  />
                                  enabled
                                </label>
                                <select
                                  className="small"
                                  value={tool.risk_class}
                                  disabled={busyToolId === tool.id}
                                  onChange={(event) => updateTool(server, tool, { risk_class: event.target.value })}
                                  aria-label={`Risk class for ${tool.tool_name}`}
                                >
                                  <option value="read_only">read only</option>
                                  <option value="write">write</option>
                                  <option value="destructive">destructive</option>
                                  <option value="external_side_effect">external side effect</option>
                                  <option value="financial">financial</option>
                                  <option value="pii">PII</option>
                                </select>
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
