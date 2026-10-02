import MappingField from './MappingField'

const OPERATOR_GROUPS = {
  string: [
    { value: 'is equal to', label: 'is equal to' },
    { value: 'is not equal to', label: 'is not equal to' },
    { value: 'contains', label: 'contains' },
    { value: 'does not contain', label: 'does not contain' },
    { value: 'starts with', label: 'starts with' },
    { value: 'does not start with', label: 'does not start with' },
    { value: 'ends with', label: 'ends with' },
    { value: 'does not end with', label: 'does not end with' },
    { value: 'matches regex', label: 'matches regex' },
    { value: 'does not match regex', label: 'does not match regex' },
    { value: 'is empty', label: 'is empty' },
    { value: 'is not empty', label: 'is not empty' },
  ],
  number: [
    { value: 'is equal to', label: 'is equal to' },
    { value: 'is not equal to', label: 'is not equal to' },
    { value: 'is greater than', label: 'is greater than' },
    { value: 'is greater than or equal to', label: 'is greater than or equal to' },
    { value: 'is less than', label: 'is less than' },
    { value: 'is less than or equal to', label: 'is less than or equal to' },
    { value: 'is empty', label: 'is empty' },
    { value: 'is not empty', label: 'is not empty' },
  ],
  boolean: [
    { value: 'is true', label: 'is true' },
    { value: 'is false', label: 'is false' },
    { value: 'is equal to', label: 'is equal to' },
    { value: 'is not equal to', label: 'is not equal to' },
  ],
  null: [
    { value: 'is null', label: 'is null' },
    { value: 'is not null', label: 'is not null' },
    { value: 'exists', label: 'exists' },
    { value: 'does not exist', label: 'does not exist' },
    { value: 'is empty', label: 'is empty' },
    { value: 'is not empty', label: 'is not empty' },
  ],
  array: [
    { value: 'contains', label: 'contains' },
    { value: 'does not contain', label: 'does not contain' },
    { value: 'is empty', label: 'is empty' },
    { value: 'is not empty', label: 'is not empty' },
  ],
  date: [
    { value: 'is equal to', label: 'is equal to' },
    { value: 'is not equal to', label: 'is not equal to' },
    { value: 'is before', label: 'is before' },
    { value: 'is after', label: 'is after' },
    { value: 'is before or equal to', label: 'is before or equal to' },
    { value: 'is after or equal to', label: 'is after or equal to' },
    { value: 'is empty', label: 'is empty' },
    { value: 'is not empty', label: 'is not empty' },
  ],
  all: []
}

// Flatten all operators for dropdown (deduplicated)
const ALL_OPERATORS = (() => {
  const seen = new Set()
  const out = []
  for (const group of Object.values(OPERATOR_GROUPS)) {
    for (const op of group) {
      if (!seen.has(op.value)) {
        seen.add(op.value)
        out.push(op)
      }
    }
  }
  // Sort for consistent UI
  return out.sort((a, b) => a.label.localeCompare(b.label))
})()

// Operators that don't need right value
const NO_RIGHT_VALUE_OPS = new Set([
  'is empty', 'is not empty',
  'is null', 'is not null', 'exists', 'does not exist',
  'is true', 'is false',
])

function newCondition(combinator = 'AND') {
  return {
    id: Math.random().toString(36).slice(2, 10),
    left: '',
    operator: 'is equal to',
    right: '',
    combinator,
  }
}

export default function IfConditionEditor({ node, onParamsChange, mapping, onPreview }) {
  const params = node.parameters || {}
  const conditions = Array.isArray(params.conditions) && params.conditions.length > 0
    ? params.conditions
    : (params.condition ? [{ id: 'legacy', left: params.condition.left || '', operator: params.condition.operator || 'is equal to', right: params.condition.right || '', combinator: 'AND' }] : [{ id: 'c1', left: '', operator: 'is equal to', right: '', combinator: 'AND' }])
  const convertTypes = Boolean(params.convertTypes)

  function updateConditions(next) {
    onParamsChange({ ...params, conditions: next, condition: undefined })
  }

  function addCondition() {
    const next = [...conditions, newCondition('AND')]
    updateConditions(next)
  }

  function removeCondition(id) {
    if (conditions.length === 1) return
    if (!confirm('Remove this condition?')) return
    updateConditions(conditions.filter(c => c.id !== id))
  }

  function updateCondition(id, patch) {
    const next = conditions.map(c => c.id === id ? { ...c, ...patch } : c)
    updateConditions(next)
  }

  function handleConvertTypes(v) {
    onParamsChange({ ...params, convertTypes: v })
  }

  return (
    <div className="if-editor" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="if-info banner-inline info" style={{ fontSize: 12, padding: '8px 10px' }}>
        Route items to TRUE or FALSE branches based on conditions. Each item is evaluated independently.
      </div>

      <div className="if-conditions">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <h4 style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>Conditions</h4>
          <span className="hint" style={{ fontSize: 11 }}>{conditions.length} condition{conditions.length !== 1 ? 's' : ''}</span>
        </div>

        {conditions.some(c => !c.left?.trim() || (!NO_RIGHT_VALUE_OPS.has(c.operator) && !c.right?.trim())) && (
          <div style={{ padding: '6px 10px', fontSize: 11.5, background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.35)', borderRadius: 6, color: '#f59e0b', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span>
            <span>Fill in required condition values before executing this step.</span>
          </div>
        )}

        {conditions.map((cond, idx) => {
          const isLeftEmpty = !cond.left || !cond.left.trim()
          const isRightRequired = !NO_RIGHT_VALUE_OPS.has(cond.operator)
          const isRightEmpty = isRightRequired && (!cond.right || !cond.right.trim())

          return (
            <div key={cond.id} className="if-condition-row" style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 10, background: 'var(--panel-2)', minWidth: 0, overflow: 'hidden' }}>
              {/* Header: Combinator (for rows after first) + Remove button */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10, minWidth: 0 }}>
                {idx > 0 ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <select
                      value={cond.combinator || 'AND'}
                      onChange={(e) => updateCondition(cond.id, { combinator: e.target.value })}
                      style={{ width: 75, fontSize: 11.5, fontWeight: 600, textAlign: 'center', background: 'var(--accent)', color: '#fff', border: '1px solid var(--accent)', borderRadius: 6, padding: '3px 6px' }}
                    >
                      <option value="AND">AND</option>
                      <option value="OR">OR</option>
                    </select>
                    <span className="hint" style={{ fontSize: 11 }}>with previous condition</span>
                  </div>
                ) : (
                  <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>Condition #{idx + 1}</span>
                )}
                {conditions.length > 1 && (
                  <button type="button" className="ghost" onClick={() => removeCondition(cond.id)} title="Remove condition" style={{ fontSize: 11, padding: "2px 8px", color: "var(--red)", marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 4 }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> Remove</button>
                )}
              </div>

              {/* Form fields: Left Value (full width), followed by Operator & Right Value */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 }}>
                {/* Left Value */}
                <div style={{ minWidth: 0, width: '100%' }}>
                  <label style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2, display: 'block' }}>Left Value</label>
                  <MappingField
                    schema={{ title: `Left ${idx + 1}`, description: 'e.g., {{$json.status}} or fixed value' }}
                    value={cond.left}
                    onChange={(v) => updateCondition(cond.id, { left: v })}
                    path={`left_${idx}`}
                    mapping={mapping}
                    onPreview={onPreview}
                  />
                  {isLeftEmpty && (
                    <span style={{ fontSize: 10.5, color: '#f59e0b', marginTop: 3, display: 'block' }}>
                      Left value required
                    </span>
                  )}
                </div>

                {/* Operator & Right Value row */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: isRightRequired ? 'repeat(auto-fit, minmax(130px, 1fr))' : '1fr',
                  gap: 10,
                  alignItems: 'start',
                  minWidth: 0,
                  width: '100%'
                }}>
                  {/* Operator */}
                  <div style={{ minWidth: 0 }}>
                    <label style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2, display: 'block' }}>Operator</label>
                    <select
                      value={cond.operator}
                      onChange={(e) => updateCondition(cond.id, { operator: e.target.value })}
                      style={{ width: '100%', fontSize: 12, minWidth: 0, height: 32, boxSizing: 'border-box' }}
                    >
                      {ALL_OPERATORS.map(o => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  </div>

                  {/* Right Value - only rendered when the operator requires it */}
                  {isRightRequired && (
                    <div style={{ minWidth: 0 }}>
                      <label style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2, display: 'block' }}>Right Value</label>
                      <MappingField
                        schema={{ title: `Right ${idx + 1}`, description: 'e.g., active or {{$json.minimumAge}}' }}
                        value={cond.right}
                        onChange={(v) => updateCondition(cond.id, { right: v })}
                        path={`right_${idx}`}
                        mapping={mapping}
                        onPreview={onPreview}
                      />
                      {isRightEmpty && (
                        <span style={{ fontSize: 10.5, color: '#f59e0b', marginTop: 3, display: 'block' }}>
                          Right value required
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}

        <button type="button" className="ghost" onClick={addCondition} style={{ width: '100%', marginTop: 4, borderStyle: 'dashed' }}>+ Add condition</button>
      </div>

      {/* Convert types */}
      <label className="check" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 6 }}>
        <input type="checkbox" checked={convertTypes} onChange={(e) => handleConvertTypes(e.target.checked)} />
        <span style={{ fontSize: 12, fontWeight: 500 }}>Convert types where required</span>
      </label>
      <span className="hint" style={{ marginTop: -8, fontSize: 11 }}>
        When ON, "10" equals 10, "true" equals true, and date strings are parsed. When OFF, strict type comparison.
      </span>

      {/* Hint */}
      <div className="hint" style={{ fontSize: 11, background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 10px' }}>
        <strong>Tip:</strong> Use <code>{'{{$json.field}}'}</code> for expressions. Items go to <span style={{ color: 'var(--green)', fontWeight: 600 }}>TRUE</span> if all conditions match (AND) or any matches (OR).
      </div>
    </div>
  )
}
