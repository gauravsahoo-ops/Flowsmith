import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useExecutionStore } from '../stores/executionStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { CollapsibleSection } from './shared/CollapsibleSection'

const PROVIDER_PRESETS = [
  'convertalogic',
  'salesforce',
  'google',
  'shopify',
  'github',
  'slack',
  'microsoft',
  'hubspot',
  'oauth2',
  'custom',
]

export default function TokenManagerNodeEditor({
  node,
  onParamsChange,
  mapping = [],
  onPreview,
}) {
  const params = node.parameters || {}
  const mode = params.mode || 'auto'
  const provider = params.provider || 'convertalogic'
  const workflowId = params.workflow_id || ''
  const autoRefresh = params.auto_refresh !== false
  const showAutoLogin = Boolean(params.login_url || params.login_body)
  const showManualRefresh = Boolean(params.refresh_url || params.refresh_body)
  const [liveDbAuth, setLiveDbAuth] = useState(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState('')
  const [refreshSuccess, setRefreshSuccess] = useState('')

  const isCustomPreset = !PROVIDER_PRESETS.filter((p) => p !== 'custom').includes((provider || '').toLowerCase())

  const currentWorkflow = useWorkflowStore((s) => s.workflow)
  const displayWorkflow = workflowId || currentWorkflow?.id || ''

  async function handleManualRefresh() {
    if (!displayWorkflow) {
      setRefreshError('No workflow context found')
      return
    }
    setIsRefreshing(true)
    setRefreshError('')
    setRefreshSuccess('')
    try {
      const res = await api.refreshWorkflowAuthState(displayWorkflow, provider, true)
      if (res?.data) {
        setLiveDbAuth(res.data)
        setRefreshSuccess('Token refreshed successfully!')
        setTimeout(() => setRefreshSuccess(''), 4000)
      }
    } catch (err) {
      const msg = err?.response?.data?.message || err?.message || 'Manual token refresh failed'
      setRefreshError(msg)
      setTimeout(() => setRefreshError(''), 6000)
    } finally {
      setIsRefreshing(false)
    }
  }

  // Query live database auth state so credentials stored by store node or previous run are visible immediately
  useEffect(() => {
    if (!displayWorkflow) return
    let alive = true
    api.getWorkflowAuthState(displayWorkflow, provider)
      .then((res) => {
        if (!alive) return
        if (res?.data && (res.data.is_valid || res.data.has_refresh_token || res.data.access_token_masked)) {
          setLiveDbAuth(res.data)
        } else {
          setLiveDbAuth(null)
        }
      })
      .catch(() => {})
    return () => { alive = false }
  }, [displayWorkflow, provider])

  const results = useExecutionStore((s) => s.results)
  const trace = useExecutionStore((s) => s.trace)

  // Extract this specific node's execution result from results (by handle: main, login, valid) or trace
  const directOutput = useMemo(() => {
    const r = results?.[node.id] || results?.outputs?.[node.id]
    if (r) {
      if (Array.isArray(r) && r.length > 0) return r[0]
      if (Array.isArray(r.main) && r.main.length > 0) return r.main[0]
      if (Array.isArray(r.login) && r.login.length > 0) return r.login[0]
      if (Array.isArray(r.valid) && r.valid.length > 0) return r.valid[0]
      if (Array.isArray(r.output_items) && r.output_items.length > 0) return r.output_items[0]
      if (typeof r === 'object' && !r.main && !r.login && !r.valid) return r
    }

    const step = trace?.find((s) => s.node_id === node.id)
    if (step?.outputs) {
      const o = step.outputs
      if (Array.isArray(o) && o.length > 0) return o[0]
      if (Array.isArray(o.main) && o.main.length > 0) return o.main[0]
      if (Array.isArray(o.login) && o.login.length > 0) return o.login[0]
      if (Array.isArray(o.valid) && o.valid.length > 0) return o.valid[0]
      if (typeof o === 'object' && !o.main && !o.login && !o.valid) return o
    }

    return null
  }, [results, trace, node.id])

  // Resolve output for Live Inspection Card:
  // 1. If this node has an execution result from the current trace, ALWAYS use it directly
  // 2. If live DB auth exists, display stored or expired credentials
  const lastOutput = useMemo(() => {
    if (directOutput) return directOutput

    if (liveDbAuth) {
      if (liveDbAuth.is_valid) {
        return {
          workflowId: liveDbAuth.workflow_id,
          provider: liveDbAuth.provider,
          accessToken: liveDbAuth.access_token_masked,
          refreshToken: liveDbAuth.has_refresh_token ? '••••••••••••' : null,
          expiresAt: liveDbAuth.expires_at,
          isValid: true,
          status: mode === 'store' ? 'STORED' : 'VALID',
          source: 'stored_credentials',
        }
      } else if (liveDbAuth.has_refresh_token || liveDbAuth.access_token_masked) {
        return {
          workflowId: liveDbAuth.workflow_id,
          provider: liveDbAuth.provider,
          accessToken: liveDbAuth.access_token_masked,
          refreshToken: liveDbAuth.has_refresh_token ? '••••••••••••' : null,
          expiresAt: liveDbAuth.expires_at,
          isValid: false,
          status: 'EXPIRED',
          source: 'stored_credentials',
        }
      }
    }

    return null
  }, [directOutput, liveDbAuth, mode])

  function updateParam(key, val) {
    onParamsChange({
      ...params,
      [key]: val,
    })
  }

  // Masked token preview — shows 'null' when no token is present
  const maskedAccess = useMemo(() => {
    const tok = lastOutput?.accessToken || lastOutput?.access_token
    if (!tok) return 'null'
    const str = String(tok)
    return str.length > 8 ? `${str.slice(0, 8)}...••••••••` : '••••••••••••'
  }, [lastOutput])

  const maskedRefresh = useMemo(() => {
    const tok = lastOutput?.refreshToken || lastOutput?.refresh_token
    if (!tok) return 'null'
    const str = String(tok)
    return str.length > 6 ? `${str.slice(0, 6)}...••••••••` : '••••••••••••'
  }, [lastOutput])

  const statusInfo = useMemo(() => {
    if (!lastOutput) {
      return { text: 'null', color: 'var(--muted, #94a3b8)', bg: 'rgba(148, 163, 184, 0.1)' }
    }
    if (lastOutput.isValid) {
      if (lastOutput.status === 'STORED') {
        return { text: lastOutput.updated ? 'Updated in Database' : 'Saved to Database', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.12)' }
      }
      if (lastOutput.status === 'REFRESHED') {
        return { text: 'Token Auto-Refreshed', color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.12)' }
      }
      return { text: 'Credentials Available (Valid)', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.12)' }
    }
    if (lastOutput.status === 'EXPIRED') {
      return { text: 'Access Token Expired (Refresh Ready)', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)' }
    }
    if (lastOutput.status === 'REAUTH_REQUIRED') {
      return { text: 'Re-Authentication Required', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.12)' }
    }
    return { text: 'Auth Required', color: 'var(--muted, #94a3b8)', bg: 'rgba(148, 163, 184, 0.1)' }
  }, [lastOutput])

  return (
    <div className="token-manager-editor" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header Banner & Live Inspection Card */}
      <div
        style={{
          background: 'var(--panel-2, #1e293b)',
          border: '1px solid var(--border, #334155)',
          borderRadius: 8,
          padding: '14px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 20 }}>🔑</span>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text)' }}>Token Manager</div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>One Universal Authentication Lifecycle Node</div>
            </div>
          </div>
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              padding: '4px 10px',
              borderRadius: 12,
              color: statusInfo.color,
              background: statusInfo.bg,
              border: `1px solid ${statusInfo.color}40`,
            }}
          >
            {statusInfo.text}
          </span>
        </div>

        {/* Live Authentication Card */}
        <div
          style={{
            background: 'var(--bg, #0f172a)',
            border: '1px solid var(--border, #334155)',
            borderRadius: 6,
            padding: '10px 12px',
            display: 'grid',
            gridTemplateColumns: '110px 1fr',
            rowGap: 8,
            columnGap: 12,
            fontSize: 12,
            alignItems: 'center',
          }}
        >
          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Workflow:</span>
          <span style={{ color: 'var(--text)', fontFamily: 'var(--font-mono, monospace)' }}>
            {displayWorkflow}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Provider:</span>
          <span
            style={{
              color: (lastOutput?.isValid && (lastOutput.provider || provider)) ? 'var(--text)' : 'var(--muted, #94a3b8)',
              fontStyle: (lastOutput?.isValid && (lastOutput.provider || provider)) ? 'normal' : 'italic',
              fontFamily: (lastOutput?.isValid && (lastOutput.provider || provider)) ? 'inherit' : 'var(--font-mono, monospace)',
              textTransform: (lastOutput?.isValid && (lastOutput.provider || provider)) ? 'capitalize' : 'none',
            }}
          >
            {(lastOutput?.isValid && (lastOutput.provider || provider)) ? (lastOutput.provider || provider) : 'null'}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Status:</span>
          <span style={{ color: statusInfo.color, fontWeight: 500 }}>
            {statusInfo.text}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Access Token:</span>
          <span
            style={{
              fontFamily: 'var(--font-mono, monospace)',
              letterSpacing: maskedAccess === 'null' ? 'normal' : '1px',
              color: maskedAccess === 'null' ? 'var(--muted, #94a3b8)' : 'var(--text)',
              fontStyle: maskedAccess === 'null' ? 'italic' : 'normal',
            }}
          >
            {maskedAccess}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Refresh Token:</span>
          <span
            style={{
              fontFamily: 'var(--font-mono, monospace)',
              letterSpacing: maskedRefresh === 'null' ? 'normal' : '1px',
              color: maskedRefresh === 'null' ? 'var(--muted, #94a3b8)' : 'var(--text)',
              fontStyle: maskedRefresh === 'null' ? 'italic' : 'normal',
            }}
          >
            {maskedRefresh}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Expires:</span>
          <span
            style={{
              color: (lastOutput?.isValid && lastOutput?.expiresAt) ? 'var(--text)' : 'var(--muted, #94a3b8)',
              fontStyle: (lastOutput?.isValid && lastOutput?.expiresAt) ? 'normal' : 'italic',
              fontFamily: (lastOutput?.isValid && lastOutput?.expiresAt) ? 'inherit' : 'var(--font-mono, monospace)',
            }}
          >
            {(lastOutput?.isValid && lastOutput?.expiresAt) ? new Date(lastOutput.expiresAt).toLocaleString() : 'null'}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Storage:</span>
          <span
            style={{
              color: lastOutput?.isValid ? '#22c55e' : 'var(--muted, #94a3b8)',
              fontWeight: 500,
              fontStyle: lastOutput?.isValid ? 'normal' : 'italic',
              fontFamily: lastOutput?.isValid ? 'inherit' : 'var(--font-mono, monospace)',
            }}
          >
            {lastOutput?.isValid ? '🛡️ Secure Credential Store (AES-GCM Encrypted at Rest)' : 'null'}
          </span>
        </div>

        {/* Manual Refresh Action Bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
            paddingTop: 8,
            borderTop: '1px solid var(--border, #334155)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
            {refreshSuccess && (
              <span style={{ fontSize: 11.5, color: '#22c55e', fontWeight: 500 }}>
                ✅ {refreshSuccess}
              </span>
            )}
            {refreshError && (
              <span
                style={{ fontSize: 11, color: '#ef4444', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                title={refreshError}
              >
                ⚠️ {refreshError}
              </span>
            )}
            {!refreshSuccess && !refreshError && (
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                Rotate or test token directly:
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={handleManualRefresh}
            disabled={isRefreshing || !displayWorkflow}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '5px 12px',
              fontSize: 11.5,
              fontWeight: 600,
              borderRadius: 6,
              border: '1px solid #38bdf8',
              background: isRefreshing ? 'var(--panel-2, #1e293b)' : 'rgba(56, 189, 248, 0.12)',
              color: '#38bdf8',
              cursor: isRefreshing || !displayWorkflow ? 'not-allowed' : 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <span style={{ display: 'inline-block', transform: isRefreshing ? 'rotate(360deg)' : 'none', transition: 'transform 0.5s ease' }}>
              🔄
            </span>
            {isRefreshing ? 'Refreshing...' : 'Manual Refresh Now'}
          </button>
        </div>
      </div>

      {/* Mode Selector Tabs */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <label style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>
          Operation Mode
        </label>
        <div
          style={{
            display: 'flex',
            background: 'var(--bg, #0f172a)',
            padding: 3,
            borderRadius: 6,
            border: '1px solid var(--border, #334155)',
          }}
        >
          {[
            { id: 'auto', label: '⚡ Automatic', desc: 'Auto-detects whether to fetch or store' },
            { id: 'fetch', label: '📥 Fetch Stored', desc: 'Fetch stored credentials from database' },
            { id: 'store', label: '💾 Store Only', desc: 'Persist incoming tokens to database' },
            { id: 'refresh', label: '🔄 Refresh Token', desc: 'Use refresh token to create new access token if expired or invalid' },
          ].map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => updateParam('mode', m.id)}
              style={{
                flex: 1,
                padding: '6px 8px',
                fontSize: 12,
                fontWeight: mode === m.id ? 600 : 400,
                borderRadius: 4,
                border: 'none',
                cursor: 'pointer',
                background: mode === m.id ? 'var(--panel-2, #1e293b)' : 'transparent',
                color: mode === m.id ? '#38bdf8' : 'var(--muted)',
                textAlign: 'center',
                whiteSpace: 'nowrap',
              }}
              title={m.desc}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2, lineHeight: 1.4 }}>
          {mode === 'auto' && '⚡ Automatically detects whether to fetch stored credentials or save incoming tokens.'}
          {mode === 'fetch' && '📥 Fetches stored credentials from database (outputs null on first run before login).'}
          {mode === 'store' && '💾 Saves incoming tokens from the Login API directly to the encrypted database store.'}
          {mode === 'refresh' && '🔄 Uses stored refresh token to create a new access token if current token is expired or invalid.'}
        </div>
      </div>

      {/* Provider Selector */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <label style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>
            Provider / Service <span style={{ color: '#ef4444' }}>*</span>
          </label>
          <div style={{ display: 'flex', gap: 4 }}>
            {PROVIDER_PRESETS.slice(0, 4).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => updateParam('provider', p)}
                style={{
                  fontSize: 10,
                  padding: '2px 6px',
                  borderRadius: 4,
                  border: '1px solid var(--border)',
                  background: provider === p ? 'var(--accent, #3b82f6)' : 'transparent',
                  color: provider === p ? '#fff' : 'var(--muted)',
                  cursor: 'pointer',
                }}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
        <select
          value={isCustomPreset ? 'custom' : provider}
          onChange={(e) => {
            const val = e.target.value
            if (val === 'custom') {
              updateParam('provider', 'custom')
            } else {
              updateParam('provider', val)
            }
          }}
          style={{
            width: '100%',
            background: 'var(--bg)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '8px 12px',
            color: 'var(--text)',
            fontSize: 13,
            outline: 'none',
          }}
        >
          {PROVIDER_PRESETS.map((p) => (
            <option key={p} value={p}>
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </option>
          ))}
        </select>
        {(provider === 'custom' || isCustomPreset) && (
          <div style={{ marginTop: 4 }}>
            <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 3 }}>
              Custom Provider Identifier:
            </label>
            <input
              type="text"
              placeholder="e.g. my_custom_service"
              value={provider === 'custom' ? '' : provider}
              onChange={(e) => updateParam('provider', e.target.value.trim().toLowerCase() || 'custom')}
              style={{
                width: '100%',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '7px 10px',
                color: 'var(--text)',
                fontSize: 12,
                fontFamily: 'var(--font-mono, monospace)',
              }}
            />
          </div>
        )}
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          The external service whose credentials are automatically managed in the database.
        </span>
      </div>

      {/* Auto-Refresh Toggle */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 12px',
          background: 'var(--panel-2, #1e293b)',
          border: '1px solid var(--border, #334155)',
          borderRadius: 6,
        }}
      >
        <div>
          <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Auto-Refresh Expired Tokens</div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>
            When access token expires, automatically refresh it in the background and update database.
          </div>
        </div>
        <input
          type="checkbox"
          checked={autoRefresh}
          onChange={(e) => updateParam('auto_refresh', e.target.checked)}
          style={{ width: 16, height: 16, cursor: 'pointer' }}
        />
      </div>

      {/* Collapsible Auto-Login Configuration */}
      <CollapsibleSection
        title="Initial Auto-Login Configuration (Solves First-Run Nulls)"
        defaultOpen={showAutoLogin}
        badge={params.login_url ? 'Configured' : 'Auto-Detects'}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
          <div style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.45 }}>
            Optionally specify the Login API / Token endpoint to call when no credentials exist in database. 
            On the very first run, Token Manager executes this request, saves the token, and outputs populated credentials so <strong>fields are never null</strong>.
            <div style={{ marginTop: 4, color: '#38bdf8' }}>
              💡 <em>If left blank, Token Manager automatically detects and runs any Login API node connected to its <code>login</code> handle!</em>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ width: 110 }}>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Method</label>
              <select
                value={params.login_method || 'POST'}
                onChange={(e) => updateParam('login_method', e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '7px 10px',
                  color: 'var(--text)',
                  fontSize: 12,
                }}
              >
                <option value="POST">POST</option>
                <option value="GET">GET</option>
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Login Endpoint URL</label>
              <input
                type="text"
                placeholder="https://api.example.com/api/v1/auth/token"
                value={params.login_url || ''}
                onChange={(e) => updateParam('login_url', e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '7px 10px',
                  color: 'var(--text)',
                  fontSize: 12,
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Login Body / Payload (JSON)</label>
            <textarea
              rows={3}
              placeholder='{"app_id": "...", "secret": "..."}'
              value={typeof params.login_body === 'object' && params.login_body ? JSON.stringify(params.login_body, null, 2) : (params.login_body || '')}
              onChange={(e) => {
                const val = e.target.value
                try {
                  const parsed = JSON.parse(val)
                  updateParam('login_body', parsed)
                } catch {
                  updateParam('login_body', val)
                }
              }}
              style={{
                width: '100%',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '7px 10px',
                color: 'var(--text)',
                fontFamily: 'var(--font-mono, monospace)',
                fontSize: 11.5,
              }}
            />
          </div>
        </div>
      </CollapsibleSection>

      {/* Force Refresh (Manual Mode) Toggle */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 12px',
          background: 'var(--panel-2, #1e293b)',
          border: '1px solid var(--border, #334155)',
          borderRadius: 6,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Force Manual Refresh on Run</div>
            <span style={{ fontSize: 9.5, padding: '1px 6px', borderRadius: 4, background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', fontWeight: 600 }}>MANUAL</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>
            Always trigger token refresh using the stored refresh token on every workflow execution, even if the current access token is not expired.
          </div>
        </div>
        <input
          type="checkbox"
          checked={Boolean(params.force_refresh)}
          onChange={(e) => updateParam('force_refresh', e.target.checked)}
          style={{ width: 16, height: 16, cursor: 'pointer' }}
        />
      </div>

      {/* Collapsible Manual Refresh Configuration */}
      <CollapsibleSection
        title="Manual Token Refresh Configuration (Custom Endpoint / Payload)"
        defaultOpen={showManualRefresh}
        badge={params.refresh_url ? 'Custom Configured' : 'Preset Provider'}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
          <div style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.45 }}>
            Optionally specify a custom OAuth refresh endpoint URL and payload. If configured, Token Manager will send the refresh request here instead of using the standard provider endpoint.
            <div style={{ marginTop: 4, color: '#38bdf8' }}>
              💡 <em>Use <code>{'{'}{'{'}refreshToken{'}'}{'}'}</code> in the body to inject the stored refresh token.</em>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ width: 110 }}>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Method</label>
              <select
                value={params.refresh_method || 'POST'}
                onChange={(e) => updateParam('refresh_method', e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '7px 10px',
                  color: 'var(--text)',
                  fontSize: 12,
                }}
              >
                <option value="POST">POST</option>
                <option value="GET">GET</option>
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Refresh Endpoint URL</label>
              <input
                type="text"
                placeholder="https://api.example.com/api/v1/auth/refresh"
                value={params.refresh_url || ''}
                onChange={(e) => updateParam('refresh_url', e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: '7px 10px',
                  color: 'var(--text)',
                  fontSize: 12,
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>
              Refresh Body / Payload (JSON)
            </label>
            <textarea
              rows={3}
              placeholder='{"refresh_token": "{{refreshToken}}"}'
              value={typeof params.refresh_body === 'object' && params.refresh_body ? JSON.stringify(params.refresh_body, null, 2) : (params.refresh_body || '')}
              onChange={(e) => {
                const val = e.target.value
                try {
                  const parsed = JSON.parse(val)
                  updateParam('refresh_body', parsed)
                } catch {
                  updateParam('refresh_body', val)
                }
              }}
              style={{
                width: '100%',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '7px 10px',
                color: 'var(--text)',
                fontFamily: 'var(--font-mono, monospace)',
                fontSize: 11.5,
              }}
            />
          </div>
        </div>
      </CollapsibleSection>

      {/* Downstream Reference Banner */}
      <div
        className="hint"
        style={{
          fontSize: 11.5,
          background: 'var(--panel-2, #1e293b)',
          border: '1px solid var(--border, #334155)',
          borderRadius: 6,
          padding: '10px 12px',
          lineHeight: 1.5,
        }}
      >
        <strong>Downstream Node Reference:</strong> In subsequent HTTP Request or API nodes, reference the token via:
        <div style={{ marginTop: 4 }}>
          <code style={{ background: 'var(--bg)', padding: '3px 8px', borderRadius: 4, color: '#38bdf8' }}>
            {'{{ $node["' + (node.name || 'Token Manager') + '"].json.accessToken }}'}
          </code>
        </div>
      </div>
    </div>
  )
}
