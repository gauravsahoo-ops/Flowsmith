import { useMemo, useState } from 'react'
import { useExecutionStore } from '../stores/executionStore'
import { useWorkflowStore } from '../stores/workflowStore'
import MappingField from './MappingField'
import { CollapsibleSection } from './shared/CollapsibleSection'

const PROVIDER_PRESETS = [
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
  const provider = params.provider || 'salesforce'
  const workflowId = params.workflow_id || ''
  const autoRefresh = params.auto_refresh !== false
  const maxRecoveryAttempts = params.max_recovery_attempts ?? 1

  const [showManualFields, setShowManualFields] = useState(
    Boolean(params.access_token || params.refresh_token || params.expires_at)
  )
  const [showOAuthConfig, setShowOAuthConfig] = useState(
    Boolean(params.client_id || params.client_secret || params.token_url)
  )

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

  // Masked token preview
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
      return { text: 'Ready (Auto-Evaluates on Run)', color: 'var(--muted)', bg: 'rgba(148, 163, 184, 0.1)' }
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
    if (lastOutput.status === 'REAUTH_REQUIRED') {
      return { text: 'Re-Authentication Required', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.12)' }
    }
    return { text: 'Authentication Required (Missing)', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)' }
  }, [lastOutput])

  const displayWorkflow = workflowId || currentWorkflow?.id || 'Current Workflow'

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

          <span style={{ color: 'var(--muted)', fontWeight: 500 }}>Storage:</span>
          <span style={{ color: '#22c55e', fontWeight: 500 }}>
            🛡️ Secure Credential Store (AES-GCM Encrypted at Rest)
          </span>
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
            { id: 'auto', label: '⚡ Automatic (Fetch & Store)', desc: 'Auto-detects whether to fetch or store' },
            { id: 'fetch', label: '📥 Fetch Stored', desc: 'Fetch & auto-refresh only' },
            { id: 'store', label: '💾 Store Only', desc: 'Persist incoming tokens' },
          ].map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => updateParam('mode', m.id)}
              style={{
                flex: 1,
                padding: '6px 10px',
                fontSize: 12,
                fontWeight: mode === m.id ? 600 : 400,
                borderRadius: 4,
                border: 'none',
                cursor: 'pointer',
                background: mode === m.id ? 'var(--panel-2, #1e293b)' : 'transparent',
                color: mode === m.id ? '#38bdf8' : 'var(--muted)',
                textAlign: 'center',
              }}
            >
              {m.label}
            </button>
          ))}
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
          {PROVIDER_PRESETS.map((p) => (
            <option key={p} value={p}>
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </option>
          ))}
        </select>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          The external service whose credentials are automatically managed.
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

      {/* Collapsible Manual Overrides */}
      <CollapsibleSection
        title="Custom Field Overrides (Optional)"
        defaultOpen={showManualFields}
        badge={params.access_token ? 'Customized' : ''}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            Leave empty for automatic detection, or map specific custom fields if needed.
          </span>

          <MappingField
            schema={{
              title: 'Access Token',
              description: 'Leave empty for auto-extract, or map e.g. {{ $json.access_token }}',
            }}
            value={params.access_token || ''}
            onChange={(v) => updateParam('access_token', v)}
            placeholder="Auto-detect from upstream output"
            path="access_token"
            mapping={mapping}
            onPreview={onPreview}
          />

          <MappingField
            schema={{
              title: 'Refresh Token',
              description: 'Leave empty for auto-extract, or map e.g. {{ $json.refresh_token }}',
            }}
            value={params.refresh_token || ''}
            onChange={(v) => updateParam('refresh_token', v)}
            placeholder="Auto-detect from upstream output"
            path="refresh_token"
            mapping={mapping}
            onPreview={onPreview}
          />

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <MappingField
              schema={{
                title: 'Expires In (Seconds)',
                description: 'e.g. 3600',
              }}
              value={params.expires_in || ''}
              onChange={(v) => updateParam('expires_in', v)}
              placeholder="Auto-detect"
              path="expires_in"
              mapping={mapping}
              onPreview={onPreview}
            />

            <MappingField
              schema={{
                title: 'Token Type',
                description: 'Default: Bearer',
              }}
              value={params.token_type || 'Bearer'}
              onChange={(v) => updateParam('token_type', v)}
              placeholder="Bearer"
              path="token_type"
              mapping={mapping}
              onPreview={onPreview}
            />
          </div>
        </div>
      </CollapsibleSection>

      {/* Collapsible OAuth Config */}
      <CollapsibleSection
        title="OAuth Client Credentials (Optional)"
        defaultOpen={showOAuthConfig}
        badge={params.client_id ? 'Configured' : ''}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            Client ID and secret required for automatic token refreshing when using OAuth 2.0.
          </span>

          <MappingField
            schema={{
              title: 'Client ID',
              description: 'OAuth Client ID / Consumer Key',
            }}
            value={params.client_id || ''}
            onChange={(v) => updateParam('client_id', v)}
            placeholder="OAuth Client ID"
            path="client_id"
            mapping={mapping}
            onPreview={onPreview}
          />

          <MappingField
            schema={{
              title: 'Client Secret',
              description: 'OAuth Client Secret (Encrypted at rest)',
              format: 'password',
            }}
            value={params.client_secret || ''}
            onChange={(v) => updateParam('client_secret', v)}
            placeholder="OAuth Client Secret"
            path="client_secret"
            mapping={mapping}
            onPreview={onPreview}
          />

          <MappingField
            schema={{
              title: 'Token URL',
              description: 'OAuth token endpoint (e.g. https://login.salesforce.com/services/oauth2/token)',
            }}
            value={params.token_url || ''}
            onChange={(v) => updateParam('token_url', v)}
            placeholder="https://provider.com/oauth/token"
            path="token_url"
            mapping={mapping}
            onPreview={onPreview}
          />
        </div>
      </CollapsibleSection>
    </div>
  )
}
