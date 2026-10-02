import { useMemo } from 'react'
import { useExecutionStore } from '../stores/executionStore'
import { useWorkflowStore } from '../stores/workflowStore'

const PROVIDER_OPTIONS = [
  { value: 'salesforce', label: 'Salesforce' },
  { value: 'google', label: 'Google' },
  { value: 'shopify', label: 'Shopify' },
  { value: 'github', label: 'GitHub' },
  { value: 'slack', label: 'Slack' },
  { value: 'microsoft', label: 'Microsoft' },
  { value: 'hubspot', label: 'HubSpot' },
  { value: 'dynamics_crm', label: 'Microsoft Dynamics 365' },
  { value: 'oauth2', label: 'Custom OAuth2' },
  { value: 'custom', label: 'Custom API' },
]

export default function TokenFetchNodeEditor({
  node,
  onParamsChange,
}) {
  const params = node.parameters || {}
  const provider = params.provider || 'salesforce'
  const workflowId = params.workflow_id || ''
  const autoRefresh = params.auto_refresh !== false
  const maxRecoveryAttempts = params.max_recovery_attempts ?? 1

  const currentWorkflow = useWorkflowStore((s) => s.workflow)
  const results = useExecutionStore((s) => s.results)
  const nodeResult = results?.[node.id]
  const lastOutput = nodeResult?.output_items?.[0] || null

  function updateParam(key, val) {
    onParamsChange({
      ...params,
      [key]: val,
    })
  }

  // Safe masking helper for tokens
  const maskedAccess = useMemo(() => {
    if (!lastOutput?.accessToken) return '••••••••••••'
    const tok = String(lastOutput.accessToken)
    return tok.length > 8 ? `${tok.slice(0, 8)}...••••••••` : '••••••••••••'
  }, [lastOutput])

  const maskedRefresh = useMemo(() => {
    if (!lastOutput?.refreshToken) return lastOutput ? 'None' : '••••••••••••'
    const tok = String(lastOutput.refreshToken)
    return tok.length > 6 ? `${tok.slice(0, 6)}...••••••••` : '••••••••••••'
  }, [lastOutput])

  const statusInfo = useMemo(() => {
    if (!lastOutput) {
      return { text: 'Ready (Evaluates on Execution)', color: 'var(--muted)', bg: 'rgba(148, 163, 184, 0.1)' }
    }
    if (lastOutput.isValid) {
      return lastOutput.status === 'REFRESHED'
        ? { text: 'Token Refreshed', color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.12)' }
        : { text: 'Credentials Available (Valid)', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.12)' }
    }
    if (lastOutput.status === 'REAUTH_REQUIRED') {
      return { text: 'Re-Authentication Required', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.12)' }
    }
    return { text: 'Authentication Required (Missing)', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)' }
  }, [lastOutput])

  const displayWorkflow = workflowId || currentWorkflow?.id || 'Current Workflow'

  return (
    <div className="token-fetch-editor" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Configuration Header Card */}
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
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3"/></svg>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>Token Fetch Node</div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Auth Lifecycle & Credential Reuse</div>
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

        {/* Live Stored Credential Inspection Card */}
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
          <span style={{ color: 'var(--text)', textTransform: 'capitalize' }}>
            {provider}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Status:</span>
          <span style={{ color: statusInfo.color, fontWeight: 500 }}>
            {statusInfo.text}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Access Token:</span>
          <span style={{ fontFamily: 'var(--font-mono, monospace)', letterSpacing: '1px', color: 'var(--text)' }}>
            {maskedAccess}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Refresh Token:</span>
          <span style={{ fontFamily: 'var(--font-mono, monospace)', letterSpacing: '1px', color: 'var(--text)' }}>
            {maskedRefresh}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Expires:</span>
          <span style={{ color: 'var(--text)' }}>
            {lastOutput?.expiresAt ? new Date(lastOutput.expiresAt).toLocaleString() : 'Managed automatically'}
          </span>

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Source:</span>
          <span style={{ color: 'var(--text)' }}>
            {lastOutput?.source ? (lastOutput.source === 'stored_credentials' ? 'Stored Credentials' : lastOutput.source) : 'Stored Credentials'}
          </span>
        </div>
      </div>

      {/* Configuration Parameters */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* Provider Field */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>
            Provider / Fetch Type <span style={{ color: '#ef4444' }}>*</span>
          </label>
          <select
            value={provider}
            onChange={(e) => updateParam('provider', e.target.value)}
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
            {PROVIDER_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            The target service whose tokens should be retrieved and reused.
          </span>
        </div>

        {/* Workflow ID (Auto / Override) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>
            Workflow ID (Optional Override)
          </label>
          <input
            type="text"
            value={workflowId}
            onChange={(e) => updateParam('workflow_id', e.target.value)}
            placeholder="Auto: Current Workflow"
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
          />
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            Leave blank to automatically bind to the current workflow context.
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
            <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>Auto-Refresh Stored Token</div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>
              Automatically refresh expired access tokens using the stored refresh token.
            </div>
          </div>
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => updateParam('auto_refresh', e.target.checked)}
            style={{ width: 16, height: 16, cursor: 'pointer' }}
          />
        </div>

        {/* Recovery Attempts */}
        {autoRefresh && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>
              Max Recovery Attempts
            </label>
            <input
              type="number"
              min={0}
              max={3}
              value={maxRecoveryAttempts}
              onChange={(e) => updateParam('max_recovery_attempts', parseInt(e.target.value, 10) || 1)}
              style={{
                width: 120,
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '6px 10px',
                color: 'var(--text)',
                fontSize: 13,
                outline: 'none',
              }}
            />
          </div>
        )}
      </div>

      {/* Downstream Reference Helper Banner */}
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
        <strong>Downstream Mapping:</strong> Reference token outputs in subsequent HTTP Request / API nodes via:
        <div style={{ marginTop: 4 }}>
          <code style={{ background: 'var(--bg)', padding: '2px 6px', borderRadius: 4, color: '#38bdf8' }}>
            {'{{ $node["' + (node.name || 'Token Fetch') + '"].json.accessToken }}'}
          </code>
        </div>
      </div>
    </div>
  )
}
