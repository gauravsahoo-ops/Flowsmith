import { useState, useCallback } from 'react'
import MappingField from './MappingField'
import Button from './shared/Button'

const TYPE_OPTIONS = [
  { value: 'string', label: 'String' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'json', label: 'JSON / Object' },
]

export default function SetVariableNodeEditor({
  node,
  onParamsChange,
  mapping = [],
  onPreview,
}) {
  const params = node.parameters || {}
  const scope = params.scope || 'workspace'

  // Ensure variables is an array
  const rawVars = params.variables
  const variables = Array.isArray(rawVars)
    ? rawVars
    : (params.key ? [{ key: params.key, value: params.value, type: params.type || 'string' }] : [{ key: '', value: '', type: 'string' }])

  const setScope = useCallback((newScope) => {
    onParamsChange({ ...params, scope: newScope })
  }, [params, onParamsChange])

  const handleVariableChange = useCallback((index, field, val) => {
    const updated = [...variables]
    updated[index] = { ...updated[index], [field]: val }
    onParamsChange({ ...params, variables: updated, key: undefined, value: undefined })
  }, [variables, params, onParamsChange])

  const handleAddVariable = useCallback(() => {
    const updated = [...variables, { key: '', value: '', type: 'string' }]
    onParamsChange({ ...params, variables: updated, key: undefined, value: undefined })
  }, [variables, params, onParamsChange])

  const handleRemoveVariable = useCallback((index) => {
    const updated = variables.filter((_, i) => i !== index)
    onParamsChange({
      ...params,
      variables: updated.length > 0 ? updated : [{ key: '', value: '', type: 'string' }],
      key: undefined,
      value: undefined,
    })
  }, [variables, params, onParamsChange])

  return (
    <div className="set-variable-editor" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* Scope Selector */}
      <div className="cfg-field-group">
        <label className="cfg-label" style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, display: 'block' }}>
          Variable Storage Scope
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div
            onClick={() => setScope('workspace')}
            style={{
              padding: '12px 14px',
              borderRadius: 8,
              border: `1px solid ${scope === 'workspace' ? 'var(--accent, #6366f1)' : 'rgba(255,255,255,0.08)'}`,
              background: scope === 'workspace' ? 'rgba(99, 102, 241, 0.12)' : 'rgba(255,255,255,0.02)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, fontSize: 13, color: '#fff' }}>
              <span>🌐</span>
              <span>Workspace Persistent</span>
            </div>
            <p style={{ margin: '6px 0 0', fontSize: 11, color: '#94a3b8', lineHeight: 1.4 }}>
              Persisted in database environment table. Shared across executions and workflow runs.
            </p>
          </div>

          <div
            onClick={() => setScope('workflow')}
            style={{
              padding: '12px 14px',
              borderRadius: 8,
              border: `1px solid ${scope === 'workflow' ? 'var(--accent, #6366f1)' : 'rgba(255,255,255,0.08)'}`,
              background: scope === 'workflow' ? 'rgba(99, 102, 241, 0.12)' : 'rgba(255,255,255,0.02)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, fontSize: 13, color: '#fff' }}>
              <span>⚡</span>
              <span>Workflow Runtime ($env)</span>
            </div>
            <p style={{ margin: '6px 0 0', fontSize: 11, color: '#94a3b8', lineHeight: 1.4 }}>
              Temporary session context for downstream nodes in this active run.
            </p>
          </div>
        </div>
      </div>

      {/* Variables List */}
      <div className="cfg-field-group">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <label className="cfg-label" style={{ fontWeight: 600, fontSize: 13 }}>
            Variables to Set
          </label>
          <span style={{ fontSize: 11, color: '#94a3b8' }}>
            Reference via <code>{`{{ $env.VAR_NAME }}`}</code>
          </span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {variables.map((item, idx) => (
            <div
              key={idx}
              style={{
                display: 'grid',
                gridTemplateColumns: '160px 110px 1fr 34px',
                gap: 8,
                alignItems: 'flex-start',
                padding: '10px 12px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: 8,
              }}
            >
              <div>
                <label style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
                  Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. AUTH_TOKEN"
                  value={item.key || ''}
                  onChange={(e) => handleVariableChange(idx, 'key', e.target.value.toUpperCase().replace(/\s+/g, '_'))}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    fontFamily: 'monospace',
                    fontSize: 12,
                    fontWeight: 600,
                  }}
                />
              </div>

              <div>
                <label style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
                  Type
                </label>
                <select
                  value={item.type || 'string'}
                  onChange={(e) => handleVariableChange(idx, 'type', e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', fontSize: 12 }}
                >
                  {TYPE_OPTIONS.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <MappingField
                  schema={{
                    title: 'Value / Expression',
                    description: item.type === 'json' ? '{"key": "value"} or {{ $json.data }}' : 'Value or {{ $json.field }}',
                  }}
                  value={item.value}
                  onChange={(val) => handleVariableChange(idx, 'value', val)}
                  path={`variables.${idx}.value`}
                  mapping={mapping}
                  onPreview={onPreview}
                />
              </div>

              <div style={{ paddingTop: 20 }}>
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => handleRemoveVariable(idx)}
                  disabled={variables.length <= 1}
                  style={{
                    width: 32,
                    height: 32,
                    padding: 0,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: variables.length <= 1 ? '#475569' : '#f87171',
                    borderRadius: 6,
                  }}
                  title="Remove variable"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>

        <button
          type="button"
          className="ghost small"
          onClick={handleAddVariable}
          style={{
            alignSelf: 'flex-start',
            marginTop: 10,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            color: '#818cf8',
            fontWeight: 600,
          }}
        >
          <span>+ Add Another Variable</span>
        </button>
      </div>

      {/* Usage Helper Callout */}
      <div
        style={{
          padding: '12px 14px',
          background: 'rgba(56, 189, 248, 0.08)',
          border: '1px solid rgba(56, 189, 248, 0.2)',
          borderRadius: 8,
          fontSize: 12,
          color: '#bae6fd',
          lineHeight: 1.5,
        }}
      >
        <strong>💡 Expression Usage in Downstream Nodes:</strong>
        <p style={{ margin: '4px 0 0' }}>
          Any downstream node (HTTP Request, Code, Switch, etc.) can access these variables via expression:{' '}
          <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 5px', borderRadius: 4, color: '#38bdf8' }}>
            {`{{ $env.VAR_NAME }}`}
          </code>
        </p>
      </div>
    </div>
  )
}
