import React, { useState, useMemo, useCallback } from 'react'
import MappingField from '../MappingField'
import { CollapsibleSection } from '../shared/CollapsibleSection'
import { validateField, groupFields } from './parameterValidation'
import './DynamicNodeConfigPanel.css'

export default function DynamicNodeConfigPanel({
  node,
  meta,
  onParamsChange,
  onSettingsChange,
  credentials = [],
  onCredentialChange,
  mapping = [],
  onPreview,
  _inputData,
  onExecuteStep,
}) {
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(node?.last_execution?.output ?? null)
  const [testError, setTestError] = useState(null)

  const params = useMemo(() => node?.parameters || {}, [node?.parameters])
  const settings = useMemo(() => node?.settings || {}, [node?.settings])

  // Required credential types — all of them are rendered, not just the first.
  const credentialTypes = useMemo(() => {
    return meta?.credential_types || node?.credential_types || []
  }, [meta, node])

  const connectedCount = useMemo(
    () => credentialTypes.filter((t) => Boolean(node?.credentials?.[t])).length,
    [credentialTypes, node],
  )

  // Matching credentials available in workspace for a given type
  const credentialsForType = useCallback(
    (credType) => {
      const wanted = (credType || '').toLowerCase()
      if (!wanted) return []
      return credentials.filter((c) => {
        const cType = (c.type || c.type_key || '').toLowerCase()
        return cType === wanted || cType.includes(wanted) || wanted.includes(cType)
      })
    },
    [credentials],
  )

  // Operations metadata. The panel gates on whichever property the node
  // declares as its selector — usually `operation`, but a node like
  // rename_keys gates on `mode` instead.
  const operationsMeta = useMemo(() => meta?.operations || {}, [meta?.operations])
  const selectorName = meta?.operation_selector || 'operation'
  const operationKeys = useMemo(() => {
    if (Object.keys(operationsMeta).length > 0) {
      return Object.keys(operationsMeta)
    }
    const opProp = meta?.parameters_schema?.properties?.[selectorName]
    if (opProp?.enum) return opProp.enum
    return []
  }, [operationsMeta, meta, selectorName])

  const currentOp = params[selectorName] || operationKeys[0] || ''
  const currentOpMeta = useMemo(() => operationsMeta[currentOp] || {}, [operationsMeta, currentOp])
  // Label for the selector control — "Operation" normally, "Mode" for a node
  // that gates on a differently-named property.
  const selectorLabel = useMemo(() => {
    const fromSchema = meta?.parameters_schema?.properties?.[selectorName]?.title
    if (fromSchema) return fromSchema
    return selectorName === 'operation'
      ? 'Operation'
      : selectorName.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  }, [meta, selectorName])

  const handleParamChange = useCallback(
    (key, val) => {
      onParamsChange({
        ...params,
        [key]: val,
      })
    },
    [params, onParamsChange],
  )

  const handleOperationChange = useCallback(
    (newOp) => {
      onParamsChange({
        ...params,
        [selectorName]: newOp,
      })
    },
    [params, onParamsChange, selectorName],
  )

  // Settings must flow through the parent handler so the canvas re-renders;
  // mutating node.settings in place would silently drop the change.
  const handleSettingChange = useCallback(
    (key, val) => {
      if (onSettingsChange) {
        onSettingsChange(key, val)
        return
      }
      node.settings = { ...(node.settings || {}), [key]: val }
    },
    [onSettingsChange, node],
  )

  // ------------------------------------------------------------------ #
  // Field model: prefer the enriched `fields[]` produced by the backend
  // ParameterSchemaBuilder; fall back to deriving plain fields from the raw
  // JSON Schema so older endpoints still render a usable form.
  // ------------------------------------------------------------------ //
  const fields = useMemo(() => {
    if (Array.isArray(meta?.fields) && meta.fields.length > 0) return meta.fields

    const props = meta?.parameters_schema?.properties || {}
    const requiredList = meta?.parameters_schema?.required || []
    const opKeys = Object.keys(operationsMeta)

    // Mirror the backend builder: a field consumed by only some operations is
    // conditionally visible for those operations.
    const operationsFor = (name) => {
      if (name === selectorName || opKeys.length === 0) return null
      const owning = opKeys.filter((k) => (operationsMeta[k]?.properties || []).includes(name))
      if (owning.length === 0 || owning.length === opKeys.length) return null
      return owning
    }

    return Object.entries(props).map(([name, def]) => {
      const owning = operationsFor(name)
      const isAdvanced = [
        'timeout_seconds',
        'retry_max_attempts',
        'retry_backoff_seconds',
        'continue_on_error',
      ].includes(name)
      return {
        name,
        title: def.title || name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
        type: Array.isArray(def.enum) && def.enum.length > 0 ? 'select' : def.type || 'string',
        default: def.default,
        description: def.description || '',
        placeholder: def.placeholder || '',
        required: requiredList.includes(name),
        enum: def.enum,
        options: Array.isArray(def.enum)
          ? def.enum.map((v) => ({
              label: String(v)
                .replace(/_/g, ' ')
                .replace(/\b\w/g, (c) => c.toUpperCase()),
              value: v,
            }))
          : null,
        show_if: owning ? { [selectorName]: owning } : null,
        group: isAdvanced ? 'advanced' : 'parameters',
        advanced: isAdvanced,
        minimum: def.minimum,
        maximum: def.maximum,
        min_length: def.minLength,
        max_length: def.maxLength,
        pattern: def.pattern,
        min_items: def.minItems,
        format: def.format,
      }
    })
  }, [meta?.fields, meta?.parameters_schema, operationsMeta, selectorName])

  // Visibility state: the selected operation plus current parameter values.
  const visibilityState = useMemo(
    () => ({ ...params, [selectorName]: currentOp }),
    [params, currentOp, selectorName],
  )

  const { main: mainFields, advanced: advancedFields } = useMemo(() => {
    // The selector (`operation`, or `mode` on rename_keys) is rendered by the
    // dedicated operation bar, not as a form field.
    const formFields = fields.filter((f) => f.name !== selectorName)
    return groupFields(formFields, visibilityState)
  }, [fields, visibilityState, selectorName])

  // ---- validation: computed for visible fields, reported inline ----
  const fieldErrors = useMemo(() => {
    const errors = {}
    for (const field of [...mainFields, ...advancedFields]) {
      const message = validateField(field, params[field.name])
      if (message) errors[field.name] = message
    }
    return errors
  }, [mainFields, advancedFields, params])

  const errorCount = Object.keys(fieldErrors).length

  // ---- expected output for the selected operation ----
  const outputPreview = useMemo(
    () => currentOpMeta.output_preview || currentOpMeta.output_schema || null,
    [currentOpMeta],
  )

  const handleTestStep = async () => {
    if (!onExecuteStep) {
      // Never fabricate a result. A preview without an execution path would be
      // a fake success signal, so the action is simply unavailable here.
      setTestResult(null)
      setTestError(
        'Preview is unavailable for this node: no step-execution endpoint is connected. Run the workflow or use Execute Step from the canvas to obtain real output.',
      )
      return
    }
    setTesting(true)
    setTestError(null)
    setTestResult(null)
    try {
      const res = await onExecuteStep()
      setTestResult(res)
    } catch (err) {
      setTestError(err.message || 'Step execution preview failed')
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="dncp-container" data-testid="dynamic-node-config-panel">
      {/* 1. CREDENTIALS SELECTION — one picker per declared credential type */}
      {credentialTypes.length > 0 && (
        <div className="dncp-credential-section" data-testid="dncp-credential-section">
          <div className="dncp-credential-header">
            <div className="dncp-credential-title">
              <span>Authentication</span>
              <span
                className={`dncp-status-badge ${connectedCount === credentialTypes.length ? 'dncp-status-connected' : 'dncp-status-missing'}`}
              >
                <span className="dncp-status-dot" />
                {connectedCount === credentialTypes.length
                  ? 'Connected'
                  : connectedCount > 0
                    ? `${connectedCount}/${credentialTypes.length} set`
                    : 'Missing'}
              </span>
            </div>
            <span style={{ fontSize: '11px', color: 'var(--text-dim, #94a3b8)' }}>
              {credentialTypes.join(', ')}
            </span>
          </div>

          {credentialTypes.map((credType) => {
            const activeId = node?.credentials?.[credType] || ''
            const available = credentialsForType(credType)
            return (
              <div className="dncp-credential-picker" key={credType}>
                <label className="dncp-field-label" htmlFor={`dncp-cred-${credType}`}>
                  Credential
                </label>
                <select
                  id={`dncp-cred-${credType}`}
                  className="dncp-credential-select"
                  value={activeId}
                  aria-label={`${credType} credential`}
                  onChange={(e) => {
                    if (onCredentialChange) onCredentialChange(credType, e.target.value)
                  }}
                  data-testid={`dncp-credential-select-${credType}`}
                >
                  <option value="">-- Select {credType} credential --</option>
                  {available.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name || `${credType} connection`}
                    </option>
                  ))}
                </select>
                {available.length === 0 && (
                  <span className="dncp-field-hint">
                    No {credType} credential exists in this workspace yet — create one from the
                    Credentials page.
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* 2. RESOURCE & OPERATION BAR */}
      {operationKeys.length > 0 && (
        <div className="dncp-op-section" data-testid="dncp-operation-section">
          <div className="dncp-op-field-row">
            <label className="dncp-op-label" htmlFor="dncp-op-select">{selectorLabel}</label>
            <select
              id="dncp-op-select"
              className="dncp-op-select"
              value={currentOp}
              onChange={(e) => handleOperationChange(e.target.value)}
              data-testid="dncp-operation-select"
            >
              {operationKeys.map((opKey) => {
                const opLabel = operationsMeta[opKey]?.display_name || opKey.replace(/_/g, ' ').toUpperCase()
                return (
                  <option key={opKey} value={opKey}>
                    {opLabel}
                  </option>
                )
              })}
            </select>
          </div>

          <div className="dncp-op-meta-row">
            <span className="dncp-op-desc">
              {currentOpMeta.description || `Execute ${currentOp.replace(/_/g, ' ')} on ${meta?.display_name || 'target'}.`}
            </span>
            <div className="dncp-badges-row">
              {currentOpMeta.idempotency === 'idempotent' && (
                <span className="dncp-badge dncp-badge-idempotent">Idempotent</span>
              )}
              {currentOpMeta.idempotency === 'conditionally_idempotent' && (
                <span className="dncp-badge dncp-badge-conditional">Conditional</span>
              )}
              {currentOpMeta.idempotency === 'non_idempotent' && (
                <span className="dncp-badge dncp-badge-non-idempotent">Non-Idempotent</span>
              )}
              {currentOpMeta.retryable && (
                <span className="dncp-badge dncp-badge-retry">Auto-Retry</span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 3. DYNAMIC PARAMETERS FORM */}
      <div className="dncp-params-form" data-testid="dncp-params-form">
        {mainFields.map((field) => {
          const propKey = field.name
          const propDef = field
          const val = params[propKey]
          const isRequired = Boolean(field.required)
          const fieldType = field.type || 'string'
          const enumVals = field.enum
          const error = fieldErrors[propKey]
          const options = field.options || (enumVals || []).map((v) => ({ label: String(v), value: v }))

          return (
            <div
              key={propKey}
              className={`dncp-field-wrapper${error ? ' dncp-field-invalid' : ''}`}
              data-testid={`dncp-field-${propKey}`}
            >
              <div className="dncp-field-label-row">
                <label className="dncp-field-label" htmlFor={`dncp-input-${propKey}`}>
                  {field.title}
                  {isRequired && <span className="dncp-required-mark">*</span>}
                </label>
              </div>

              {/* SELECT / ENUM */}
              {fieldType === 'select' && options.length > 0 ? (
                <select
                  id={`dncp-input-${propKey}`}
                  className="dncp-input"
                  aria-invalid={error ? 'true' : undefined}
                  value={val ?? field.default ?? ''}
                  onChange={(e) => handleParamChange(propKey, e.target.value)}
                >
                  <option value="">-- select --</option>
                  {options.map((opt) => (
                    <option key={String(opt.value)} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              ) : fieldType === 'boolean' ? (
                /* BOOLEAN SWITCH */
                <label className="dncp-toggle-row">
                  <input
                    type="checkbox"
                    className="dncp-toggle-input"
                    checked={Boolean(val ?? field.default)}
                    onChange={(e) => handleParamChange(propKey, e.target.checked)}
                  />
                  <span style={{ fontSize: '13px' }}>{field.description || 'Enable option'}</span>
                </label>
              ) : fieldType === 'number' ? (
                /* NUMBER */
                <input
                  type="number"
                  id={`dncp-input-${propKey}`}
                  className="dncp-input"
                  aria-invalid={error ? 'true' : undefined}
                  value={val ?? field.default ?? ''}
                  onChange={(e) => {
                    const n = e.target.value
                    handleParamChange(propKey, n === '' ? undefined : Number(n))
                  }}
                  placeholder={field.placeholder || undefined}
                  min={field.minimum ?? undefined}
                  max={field.maximum ?? undefined}
                />
              ) : fieldType === 'json' || fieldType === 'object' ? (
                /* OBJECT / JSON */
                <textarea
                  id={`dncp-input-${propKey}`}
                  className="dncp-input dncp-textarea"
                  aria-invalid={error ? 'true' : undefined}
                  value={typeof val === 'object' && val !== null ? JSON.stringify(val, null, 2) : val ?? ''}
                  onChange={(e) => {
                    try {
                      const parsed = JSON.parse(e.target.value)
                      handleParamChange(propKey, parsed)
                    } catch {
                      handleParamChange(propKey, e.target.value)
                    }
                  }}
                  placeholder={field.placeholder || (field.description || '{\n  "key": "value"\n}')}
                />
              ) : fieldType === 'list' ? (
                /* ARRAY (newline or JSON separated) */
                <textarea
                  id={`dncp-input-${propKey}`}
                  className="dncp-input dncp-textarea"
                  aria-invalid={error ? 'true' : undefined}
                  value={Array.isArray(val) ? val.join('\n') : val ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value
                    if (raw.trim() === '') {
                      handleParamChange(propKey, [])
                      return
                    }
                    try {
                      const parsed = JSON.parse(raw)
                      handleParamChange(propKey, Array.isArray(parsed) ? parsed : [parsed])
                    } catch {
                      handleParamChange(propKey, raw.split('\n').filter((line) => line.trim() !== ''))
                    }
                  }}
                  placeholder={field.placeholder || 'One item per line'}
                />
              ) : (
                /* STRING / EXPRESSION */
                <MappingField
                  schema={propDef}
                  value={val ?? field.default ?? ''}
                  onChange={(newVal) => handleParamChange(propKey, newVal)}
                  path={propKey}
                  mapping={mapping}
                  onPreview={onPreview}
                />
              )}

              {error ? (
                <span className="dncp-field-error" role="alert" data-testid={`dncp-error-${propKey}`}>
                  {error}
                </span>
              ) : (
                field.description &&
                fieldType !== 'boolean' && <span className="dncp-field-hint">{field.description}</span>
              )}
            </div>
          )
        })}

        {mainFields.length === 0 && (
          <div style={{ padding: '16px 0', textAlign: 'center', color: 'var(--muted, #64748b)', fontSize: '12px' }}>
            No additional parameters required for this operation.
          </div>
        )}
      </div>

      {/* 4. ADVANCED SETTINGS — schema-driven advanced fields + error strategy */}
      <CollapsibleSection title="Advanced Options & Error Strategy" defaultOpen={false}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '6px 0' }}>
          {advancedFields.map((field) => {
            const val = params[field.name]
            const error = fieldErrors[field.name]
            return (
              <div key={field.name} className={`dncp-field-wrapper${error ? ' dncp-field-invalid' : ''}`}>
                <label className="dncp-field-label" htmlFor={`dncp-input-${field.name}`}>
                  {field.title}
                  {field.required && <span className="dncp-required-mark">*</span>}
                </label>
                {field.type === 'boolean' ? (
                  <label className="dncp-toggle-row">
                    <input
                      type="checkbox"
                      className="dncp-toggle-input"
                      checked={Boolean(val ?? field.default)}
                      onChange={(e) => handleParamChange(field.name, e.target.checked)}
                    />
                    <span style={{ fontSize: '13px' }}>{field.description || 'Enable option'}</span>
                  </label>
                ) : field.type === 'select' && (field.options || []).length > 0 ? (
                  <select
                    id={`dncp-input-${field.name}`}
                    className="dncp-input"
                    value={val ?? field.default ?? ''}
                    onChange={(e) => handleParamChange(field.name, e.target.value)}
                  >
                    <option value="">-- select --</option>
                    {(field.options || []).map((opt) => (
                      <option key={String(opt.value)} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type === 'number' ? 'number' : 'text'}
                    id={`dncp-input-${field.name}`}
                    className="dncp-input"
                    value={val ?? field.default ?? ''}
                    placeholder={field.placeholder || undefined}
                    min={field.minimum ?? undefined}
                    max={field.maximum ?? undefined}
                    onChange={(e) =>
                      handleParamChange(
                        field.name,
                        field.type === 'number'
                          ? e.target.value === ''
                            ? undefined
                            : Number(e.target.value)
                          : e.target.value,
                      )
                    }
                  />
                )}
                {error ? (
                  <span className="dncp-field-error" role="alert" data-testid={`dncp-error-${field.name}`}>
                    {error}
                  </span>
                ) : (
                  field.description && <span className="dncp-field-hint">{field.description}</span>
                )}
              </div>
            )
          })}

          <div className="dncp-field-wrapper">
            <label className="dncp-field-label">Retry Attempts on Failure</label>
            <input
              type="number"
              className="dncp-input"
              value={settings.retry_max_attempts ?? 0}
              onChange={(e) => handleSettingChange('retry_max_attempts', Number(e.target.value) || 0)}
              min={0}
              max={10}
            />
            <span className="dncp-field-hint">Automatically retries with exponential backoff on transient errors.</span>
          </div>

          <label className="dncp-toggle-row">
            <input
              type="checkbox"
              className="dncp-toggle-input"
              checked={Boolean(settings.continue_on_error)}
              onChange={(e) => handleSettingChange('continue_on_error', e.target.checked)}
            />
            <span style={{ fontSize: '13px' }}>Continue workflow execution on step error</span>
          </label>
        </div>
      </CollapsibleSection>

      {/* 4b. EXPECTED OUTPUT SHAPE for the selected operation */}
      {outputPreview && (
        <CollapsibleSection title="Expected Output Shape" defaultOpen={false}>
          <div className="dncp-output-schema" data-testid="dncp-output-schema">
            <p className="dncp-field-hint" style={{ marginBottom: '6px' }}>
              {currentOpMeta.description
                ? `${currentOpMeta.description} Returns:`
                : 'This operation returns:'}
            </p>
            <pre>{JSON.stringify(outputPreview, null, 2)}</pre>
          </div>
        </CollapsibleSection>
      )}

      {/* 5. EXECUTION PREVIEW */}
      <div className="dncp-test-bar" data-testid="dncp-preview-bar">
        <div>
          <div style={{ fontSize: '12px', fontWeight: 600 }}>Test & Preview Output</div>
          <div style={{ fontSize: '11px', color: 'var(--muted, #64748b)' }}>
            {errorCount > 0
              ? `${errorCount} field${errorCount === 1 ? '' : 's'} need attention before this step can run.`
              : 'Run step with current parameters and inspect output items.'}
          </div>
        </div>
        <button
          type="button"
          className="dncp-test-btn"
          onClick={handleTestStep}
          disabled={testing || !onExecuteStep || errorCount > 0}
          title={
            errorCount > 0
              ? 'Fix the highlighted fields first'
              : onExecuteStep
                ? 'Run this step with the current parameters'
                : 'No execution endpoint is connected for this node'
          }
          data-testid="dncp-test-step-button"
        >
          {testing ? 'Testing...' : 'Test Step'}
        </button>
      </div>

      {testError && (
        <div style={{ color: '#f43f5e', fontSize: '12px', padding: '8px', background: 'rgba(244,63,94,0.1)', borderRadius: '6px' }}>
          {testError}
        </div>
      )}

      {testResult && (
        <div className="dncp-preview-output" data-testid="dncp-preview-output">
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--muted, #64748b)', marginBottom: '4px' }}>
            Last Output Preview
          </div>
          <pre>{JSON.stringify(testResult, null, 2)}</pre>
        </div>
      )}
    </div>
  )
}
