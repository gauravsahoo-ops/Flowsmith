import { useState, useRef, useEffect, useMemo } from 'react'
import MappingInput from './MappingField'

const INCLUDE_OPTIONS = [
  { value: 'noOtherFields', label: 'No Other Fields' },
  { value: 'allOtherFields', label: 'All Other Fields' },
  { value: 'selectedOtherFields', label: 'Selected Other Fields' },
]

const AVAILABLE_OPTIONS = [
  { id: 'disableDotNotation', label: 'Disable Dot Notation' },
  { id: 'destinationFieldName', label: 'Destination Field Name' },
  { id: 'includeBinary', label: 'Include Binary' },
]

export default function SplitNodeEditor({ node, onParamsChange, mapping, onPreview }) {
  const params = node.parameters || {}
  const fieldToSplitOut = params.fieldToSplitOut ?? params.field ?? 'data'
  const include = params.include ?? 'noOtherFields'
  const fieldsToInclude = Array.isArray(params.fieldsToInclude)
    ? params.fieldsToInclude
    : (typeof params.fieldsToInclude === 'string' && params.fieldsToInclude
        ? params.fieldsToInclude.split(',').map(s => s.trim()).filter(Boolean)
        : [])

  const availableFields = useMemo(() => {
    if (!Array.isArray(mapping)) return []
    const set = new Set()
    for (const m of mapping) {
      if (m?.path) {
        const clean = m.path.replace(/^(json\.|items\[\d+\]\.)/, '')
        if (clean && !clean.startsWith('$') && clean !== fieldToSplitOut) {
          set.add(clean)
        }
      }
    }
    return Array.from(set).slice(0, 10)
  }, [mapping, fieldToSplitOut])

  const options = params.options || {}
  const [optionsMenuOpen, setOptionsMenuOpen] = useState(false)
  const menuRef = useRef(null)

  // Track active options
  const activeOptionKeys = Object.keys(options).filter(k => {
    if (k === 'destinationFieldName') return options[k] !== undefined && options[k] !== null
    if (k === 'disableDotNotation') return options[k] !== undefined
    if (k === 'includeBinary') return options[k] !== undefined
    return false
  })

  const remainingOptions = AVAILABLE_OPTIONS.filter(o => !activeOptionKeys.includes(o.id))

  // Close menu on click outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOptionsMenuOpen(false)
      }
    }
    if (optionsMenuOpen) {
      window.addEventListener('pointerdown', handleClickOutside, true)
      window.addEventListener('touchstart', handleClickOutside, true)
      return () => {
        window.removeEventListener('pointerdown', handleClickOutside, true)
        window.removeEventListener('touchstart', handleClickOutside, true)
      }
    }
  }, [optionsMenuOpen])

  function updateField(key, val) {
    onParamsChange({
      ...params,
      [key]: val,
    })
  }

  function updateOption(key, val) {
    onParamsChange({
      ...params,
      options: {
        ...(params.options || {}),
        [key]: val,
      },
    })
  }

  function addOption(optId) {
    setOptionsMenuOpen(false)
    const defaults = {
      destinationFieldName: '',
      disableDotNotation: false,
      includeBinary: false,
    }
    updateOption(optId, defaults[optId])
  }

  function removeOption(optId) {
    const nextOpts = { ...(params.options || {}) }
    delete nextOpts[optId]
    onParamsChange({
      ...params,
      options: nextOpts,
    })
  }

  function addFieldToInclude() {
    const next = [...fieldsToInclude, '']
    updateField('fieldsToInclude', next)
  }

  function updateFieldToInclude(index, value) {
    const next = [...fieldsToInclude]
    next[index] = value
    updateField('fieldsToInclude', next)
  }

  function removeFieldToInclude(index) {
    const next = fieldsToInclude.filter((_, i) => i !== index)
    updateField('fieldsToInclude', next)
  }

  return (
    <div className="split-node-editor" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* 1. Fields To Split Out */}
      <div className="split-field-group">
        <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <span style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>
            Fields To Split Out
          </span>
          <MappingInput
            value={fieldToSplitOut}
            onChange={(v) => {
              onParamsChange({
                ...params,
                fieldToSplitOut: v,
                field: v,
              })
            }}
            placeholder="data"
            path="fieldToSplitOut"
            mapping={mapping}
            onPreview={onPreview}
          />
        </label>
        <span className="hint" style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, display: 'block' }}>
          Use $binary to split out the input item by binary data
        </span>
      </div>

      {/* 2. Include Dropdown */}
      <div className="split-field-group">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5 }}>
          <label style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 4 }}>
            Include
            <span
              title="Which fields from the input item should be copied into each split item."
              style={{ fontSize: 11, color: 'var(--muted)', cursor: 'help' }}
            >
              ⓘ
            </span>
          </label>
        </div>

        <select
          value={include}
          onChange={(e) => updateField('include', e.target.value)}
          style={{ width: '100%', fontSize: 13, padding: '7px 10px', borderRadius: 6, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)' }}
        >
          {INCLUDE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* 2b. Selected Other Fields List */}
      {include === 'selectedOtherFields' && (
        <div
          className="split-selected-fields"
          style={{
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: 10,
            background: 'var(--panel-2)',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
              Fields To Include
            </span>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>
              {fieldsToInclude.length} {fieldsToInclude.length === 1 ? 'field' : 'fields'}
            </span>
          </div>

          {availableFields.length > 0 && availableFields.some(f => !fieldsToInclude.includes(f)) && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center', margin: '2px 0 4px 0' }}>
              <span style={{ fontSize: 10.5, color: 'var(--muted)' }}>Suggested:</span>
              {availableFields.filter(f => !fieldsToInclude.includes(f)).map(f => (
                <button
                  key={f}
                  type="button"
                  className="ghost small"
                  onClick={() => updateField('fieldsToInclude', [...fieldsToInclude, f])}
                  style={{ fontSize: 10.5, padding: '1px 6px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', cursor: 'pointer' }}
                  title={`Add ${f}`}
                >
                  + {f}
                </button>
              ))}
            </div>
          )}

          {fieldsToInclude.map((fieldName, idx) => (
            <div key={idx} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input
                type="text"
                value={fieldName}
                onChange={(e) => updateFieldToInclude(idx, e.target.value)}
                placeholder="Field name (e.g. email or user.id)"
                style={{ flex: 1, fontSize: 12.5, padding: '5px 8px', borderRadius: 4, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)' }}
              />
              <button
                type="button"
                className="ghost"
                onClick={() => removeFieldToInclude(idx)}
                title="Remove field"
                style={{ padding: '2px 6px', color: 'var(--muted)', fontSize: 12 }}
              >
                ✕
              </button>
            </div>
          ))}

          <button
            type="button"
            className="ghost small"
            onClick={addFieldToInclude}
            style={{ alignSelf: 'flex-start', marginTop: 2, fontSize: 12, padding: '4px 10px' }}
          >
            + Add Field
          </button>
        </div>
      )}

      {/* 3. Options Header and Add Button */}
      <div
        className="split-options-section"
        style={{
          border: '1px solid var(--border)',
          borderRadius: 6,
          padding: 10,
          background: 'var(--panel-2)',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', position: 'relative' }}>
          <span style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text)' }}>
            Options
          </span>

          <div ref={menuRef} style={{ position: 'relative' }}>
            <button
              type="button"
              className="ghost small"
              onClick={() => setOptionsMenuOpen(v => !v)}
              title="Add Option"
              style={{
                width: 26,
                height: 26,
                padding: 0,
                display: 'grid',
                placeItems: 'center',
                fontSize: 14,
                borderRadius: 5,
                border: '1px solid var(--border)',
                background: 'var(--bg)',
              }}
            >
              +
            </button>

            {/* n8n style popup menu */}
            {optionsMenuOpen && (
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: '100%',
                  marginTop: 4,
                  zIndex: 100,
                  background: 'var(--panel)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                  minWidth: 180,
                  overflow: 'hidden',
                }}
              >
                {remainingOptions.length === 0 ? (
                  <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--muted)' }}>
                    All options added
                  </div>
                ) : (
                  remainingOptions.map(opt => (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => addOption(opt.id)}
                      style={{
                        width: '100%',
                        textAlign: 'left',
                        padding: '8px 12px',
                        background: 'none',
                        border: 'none',
                        color: 'var(--text)',
                        fontSize: 12.5,
                        cursor: 'pointer',
                        transition: 'background 0.12s ease',
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.06)' }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = 'none' }}
                    >
                      {opt.label}
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        </div>

        {/* Render Active Options */}
        {activeOptionKeys.length === 0 ? (
          <span className="hint" style={{ fontSize: 11, color: 'var(--muted)' }}>
            No options selected
          </span>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {/* Destination Field Name */}
            {activeOptionKeys.includes('destinationFieldName') && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
                    Destination Field Name
                  </span>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => removeOption('destinationFieldName')}
                    title="Remove Destination Field Name"
                    style={{ padding: '1px 5px', fontSize: 11, color: 'var(--muted)' }}
                  >
                    ✕
                  </button>
                </div>
                <input
                  type="text"
                  value={options.destinationFieldName ?? ''}
                  onChange={(e) => updateOption('destinationFieldName', e.target.value)}
                  placeholder="e.g. myField"
                  style={{ width: '100%', fontSize: 12.5, padding: '5px 8px', borderRadius: 4, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)' }}
                />
              </div>
            )}

            {/* Disable Dot Notation */}
            {activeOptionKeys.includes('disableDotNotation') && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 0' }}>
                <label className="check" style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, margin: 0, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={Boolean(options.disableDotNotation)}
                    onChange={(e) => updateOption('disableDotNotation', e.target.checked)}
                  />
                  <span>Disable Dot Notation</span>
                </label>
                <button
                  type="button"
                  className="ghost"
                  onClick={() => removeOption('disableDotNotation')}
                  title="Remove Disable Dot Notation"
                  style={{ padding: '1px 5px', fontSize: 11, color: 'var(--muted)' }}
                >
                  ✕
                </button>
              </div>
            )}

            {/* Include Binary */}
            {activeOptionKeys.includes('includeBinary') && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 0' }}>
                <label className="check" style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, margin: 0, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={Boolean(options.includeBinary)}
                    onChange={(e) => updateOption('includeBinary', e.target.checked)}
                  />
                  <span>Include Binary</span>
                </label>
                <button
                  type="button"
                  className="ghost"
                  onClick={() => removeOption('includeBinary')}
                  title="Remove Include Binary"
                  style={{ padding: '1px 5px', fontSize: 11, color: 'var(--muted)' }}
                >
                  ✕
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
