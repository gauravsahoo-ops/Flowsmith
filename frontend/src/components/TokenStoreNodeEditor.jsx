import { useState } from 'react'
import MappingField from './MappingField'
import { CollapsibleSection } from './shared/CollapsibleSection'
import { useExecutionStore } from '../stores/executionStore'

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

export default function TokenStoreNodeEditor({
  node,
  onParamsChange,
  mapping = [],
  onPreview,
}) {
  const params = node.parameters || {}
  const autoDetect = params.auto_detect !== false
  const [showManual, setShowManual] = useState(!autoDetect)
  const [showOAuthConfig, setShowOAuthConfig] = useState(
    Boolean(params.client_id || params.client_secret || params.token_url)
  )

  const results = useExecutionStore((s) => s.results)
  const nodeResult = results?.[node.id]
  const lastOutput = nodeResult?.output_items?.[0] || null

  function updateParam(key, val) {
    onParamsChange({
      ...params,
      [key]: val,
    })
  }

  function setMode(auto) {
    setShowManual(!auto)
    updateParam('auto_detect', auto)
  }

  return (
    <div className="token-store-editor" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header Banner */}
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
            <span style={{ fontSize: 18 }}>💾</span>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>Token Store Node</div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Encrypted Credential Persistence</div>
            </div>
          </div>
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              padding: '4px 10px',
              borderRadius: 12,
              color: '#22c55e',
              background: 'rgba(34, 197, 94, 0.12)',
              border: '1px solid rgba(34, 197, 94, 0.3)',
            }}
          >
            🛡️ AES-GCM Encrypted
          </span>
        </div>

        {/* Mode Selector Tabs */}
        <div
          style={{
            display: 'flex',
            background: 'var(--bg, #0f172a)',
            padding: 3,
            borderRadius: 6,
            border: '1px solid var(--border, #334155)',
          }}
        >
          <button
            type="button"
            onClick={() => setMode(true)}
            style={{
              flex: 1,
              padding: '6px 12px',
              fontSize: 12,
              fontWeight: autoDetect ? 600 : 400,
              borderRadius: 4,
              border: 'none',
              cursor: 'pointer',
              background: autoDetect ? 'var(--panel-2, #1e293b)' : 'transparent',
              color: autoDetect ? '#38bdf8' : 'var(--muted)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
            }}
          >
            <span>⚡</span> Automatic Store (Recommended)
          </button>
          <button
            type="button"
            onClick={() => setMode(false)}
            style={{
              flex: 1,
              padding: '6px 12px',
              fontSize: 12,
              fontWeight: !autoDetect ? 600 : 400,
              borderRadius: 4,
              border: 'none',
              cursor: 'pointer',
              background: !autoDetect ? 'var(--panel-2, #1e293b)' : 'transparent',
              color: !autoDetect ? '#38bdf8' : 'var(--muted)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
            }}
          >
            <span>🛠️</span> Custom Expressions
          </button>
        </div>

        {/* Automatic Info Callout */}
        {autoDetect ? (
          <div
            style={{
              background: 'rgba(56, 189, 248, 0.08)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              borderRadius: 6,
              padding: '10px 12px',
              fontSize: 12,
              lineHeight: 1.5,
              color: 'var(--text)',
            }}
          >
            <div style={{ fontWeight: 600, color: '#38bdf8', marginBottom: 2 }}>
              ✨ 100% Automatic Token Storage
            </div>
            <div>
              Automatically detects and extracts <code>access_token</code>, <code>refresh_token</code>, <code>expires_in</code>, and <code>token_type</code> directly from the incoming Login API response.
              <strong> No manual expressions or mapping required.</strong>
            </div>
          </div>
        ) : (
          <div
            style={{
              fontSize: 12,
              lineHeight: 1.45,
              color: 'var(--muted)',
              background: 'var(--bg, #0f172a)',
              padding: '8px 12px',
              borderRadius: 6,
              border: '1px solid var(--border, #334155)',
            }}
          >
            <strong>Custom Mode:</strong> Map explicit expression fields from upstream nodes.
          </div>
        )}

        {/* Live Execution Status */}
        {lastOutput && (
          <div
            style={{
              fontSize: 11.5,
              background: 'var(--bg, #0f172a)',
              padding: '8px 12px',
              borderRadius: 6,
              border: '1px solid var(--border, #334155)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span style={{ color: 'var(--muted)' }}>Last Stored Status:</span>
            <span style={{ color: '#22c55e', fontWeight: 600 }}>
              ✅ {lastOutput.updated ? 'Updated Existing Record' : 'Created New Record'} ({lastOutput.provider})
            </span>
          </div>
        )}
      </div>

      {/* Provider Selector (Always visible) */}
      <div className="form-group" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
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
                  background: (params.provider || 'salesforce') === p ? 'var(--accent, #3b82f6)' : 'transparent',
                  color: (params.provider || 'salesforce') === p ? '#fff' : 'var(--muted)',
                  cursor: 'pointer',
                }}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
        <select
          value={params.provider || 'salesforce'}
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
      </div>

      {/* Manual Mapping Fields (Only shown if user chose Custom Expressions or expands) */}
      {(!autoDetect || showManual) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Access Token */}
          <div className="form-group">
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
          </div>

          {/* Refresh Token */}
          <div className="form-group">
            <MappingField
              schema={{
                title: 'Refresh Token (Optional)',
                description: 'Leave empty for auto-extract, or map e.g. {{ $json.refresh_token }}',
              }}
              value={params.refresh_token || ''}
              onChange={(v) => updateParam('refresh_token', v)}
              placeholder="Auto-detect from upstream output"
              path="refresh_token"
              mapping={mapping}
              onPreview={onPreview}
            />
          </div>

          {/* Expiration Configuration */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group">
              <MappingField
                schema={{
                  title: 'Expires At (Optional)',
                  description: 'Epoch timestamp or ISO date',
                }}
                value={params.expires_at || ''}
                onChange={(v) => updateParam('expires_at', v)}
                placeholder="Auto-detect"
                path="expires_at"
                mapping={mapping}
                onPreview={onPreview}
              />
            </div>

            <div className="form-group">
              <MappingField
                schema={{
                  title: 'Expires In (Seconds)',
                  description: 'e.g. 3600 or 7200',
                }}
                value={params.expires_in || ''}
                onChange={(v) => updateParam('expires_in', v)}
                placeholder="Auto-detect"
                path="expires_in"
                mapping={mapping}
                onPreview={onPreview}
              />
            </div>
          </div>

          {/* Token Type & Scope */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12 }}>
            <div className="form-group">
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

            <div className="form-group">
              <MappingField
                schema={{
                  title: 'Scope (Optional)',
                  description: 'Granted permission scope string',
                }}
                value={params.scope || ''}
                onChange={(v) => updateParam('scope', v)}
                placeholder="Auto-detect"
                path="scope"
                mapping={mapping}
                onPreview={onPreview}
              />
            </div>
          </div>
        </div>
      )}

      {/* Collapsible OAuth Client Refresh Parameters */}
      <CollapsibleSection
        title="OAuth Auto-Refresh Configuration"
        defaultOpen={showOAuthConfig}
        badge={params.client_id ? 'Configured' : ''}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.4 }}>
            Optional OAuth client credentials needed when the token expires and needs background refreshing.
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
