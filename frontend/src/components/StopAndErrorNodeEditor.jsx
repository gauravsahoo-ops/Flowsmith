import MappingField from './MappingField'

export default function StopAndErrorNodeEditor({
  node,
  onParamsChange,
  mapping = [],
  onPreview,
}) {
  const params = node.parameters || {}
  const errorType = params.error_type || params.errorType || 'errorMessage'
  const errorMessage = params.error_message ?? params.errorMessage ?? 'An error occurred!'
  const errorObject = params.error_object ?? params.errorObject ?? ''

  function updateField(key, val) {
    onParamsChange({
      ...params,
      [key]: val,
      ...(key === 'error_type' ? { errorType: val } : {}),
      ...(key === 'error_message' ? { errorMessage: val } : {}),
      ...(key === 'error_object' ? { errorObject: val } : {}),
    })
  }

  return (
    <div className="stop-and-error-editor" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* 1. Error Type Select */}
      <div className="form-group" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <label style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>
            Error Type
          </label>
        </div>
        <select
          value={errorType}
          onChange={(e) => updateField('error_type', e.target.value)}
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
          <option value="errorMessage">Error Message</option>
          <option value="errorObject">Error Object</option>
        </select>
      </div>

      {/* 2. Error Message or Error Object */}
      {errorType === 'errorMessage' ? (
        <div className="form-group" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <MappingField
            schema={{
              title: 'Error Message',
              description: 'The error message to throw when this node is executed',
            }}
            value={errorMessage}
            onChange={(v) => updateField('error_message', v)}
            placeholder="An error occurred!"
            path="error_message"
            mapping={mapping}
            onPreview={onPreview}
          />
        </div>
      ) : (
        <div className="form-group" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <MappingField
            schema={{
              title: 'Error Object',
              description: 'The error object to throw (JSON or expression, e.g. {{ $json }})',
            }}
            value={typeof errorObject === 'object' ? JSON.stringify(errorObject, null, 2) : errorObject}
            onChange={(v) => updateField('error_object', v)}
            placeholder="{{ $json }}"
            path="error_object"
            mapping={mapping}
            onPreview={onPreview}
          />
        </div>
      )}

      {/* Tip Banner */}
      <div
        className="hint"
        style={{
          fontSize: 11,
          background: 'var(--panel-2)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          padding: '8px 10px',
          marginTop: 4,
          lineHeight: 1.45,
        }}
      >
        <strong>Tip:</strong> Use <code>{'{{$json.field}}'}</code> for expressions. When execution reaches this node, the workflow halts immediately with this error.
      </div>
    </div>
  )
}
