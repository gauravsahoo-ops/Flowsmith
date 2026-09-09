import { useState, useRef, useEffect } from 'react'
import './ExecuteWorkflowTriggerEditor.css'

const INPUT_MODES = [
  {
    id: 'fields',
    title: 'Define using fields below',
    desc: 'Define expected input schema fields and types',
  },
  {
    id: 'any',
    title: 'Accept any data',
    desc: 'Pass all incoming data from the calling workflow without validation',
  },
]

const DATA_TYPES = [
  { id: 'any', label: 'Allow Any Type' },
  { id: 'string', label: 'String' },
  { id: 'number', label: 'Number' },
  { id: 'boolean', label: 'Boolean' },
  { id: 'array', label: 'Array' },
  { id: 'object', label: 'Object' },
]

export default function ExecuteWorkflowTriggerEditor({
  node,
  onParamsChange,
}) {
  const params = node.parameters || {}
  const inputDataMode = params.input_data_mode || 'fields'
  const schemaFields = Array.isArray(params.schema_fields) ? params.schema_fields : []

  // UI state
  const [modeMenuOpen, setModeMenuOpen] = useState(false)
  const [openTypeIndex, setOpenTypeIndex] = useState(null)
  const [collapsedCards, setCollapsedCards] = useState({})

  const modeRef = useRef(null)

  useEffect(() => {
    function handleClickOutside(e) {
      if (modeRef.current && !modeRef.current.contains(e.target)) {
        setModeMenuOpen(false)
      }
      if (!e.target.closest('.subwf-trig-type-wrap')) {
        setOpenTypeIndex(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function updateMode(newMode) {
    onParamsChange({ ...params, input_data_mode: newMode })
    setModeMenuOpen(false)
  }

  function addField() {
    const next = [...schemaFields, { name: '', type: 'string' }]
    onParamsChange({ ...params, schema_fields: next })
  }

  function updateFieldItem(index, key, val) {
    const next = [...schemaFields]
    next[index] = { ...next[index], [key]: val }
    onParamsChange({ ...params, schema_fields: next })
  }

  function removeField(index) {
    const next = schemaFields.filter((_, i) => i !== index)
    onParamsChange({ ...params, schema_fields: next })
  }

  function toggleCollapse(index) {
    setCollapsedCards((prev) => ({ ...prev, [index]: !prev[index] }))
  }

  const selectedMode = INPUT_MODES.find((m) => m.id === inputDataMode) || INPUT_MODES[0]

  return (
    <div className="subwf-trig-editor">
      {/* 1. Input data mode */}
      <div className="subwf-trig-field-group" ref={modeRef}>
        <div className="subwf-trig-field-header">
          <label className="subwf-trig-field-label">Input data mode</label>
        </div>

        <div className="subwf-trig-select-wrap">
          <button
            type="button"
            className={`subwf-trig-select-btn ${modeMenuOpen ? 'open' : ''}`}
            onClick={() => setModeMenuOpen(!modeMenuOpen)}
          >
            <span className="subwf-trig-select-title">{selectedMode.title}</span>
            <span className="subwf-trig-select-arrow">{modeMenuOpen ? '▴' : '▾'}</span>
          </button>

          {modeMenuOpen && (
            <div className="subwf-trig-select-dropdown">
              {INPUT_MODES.map((m) => {
                const isSelected = m.id === inputDataMode
                return (
                  <button
                    key={m.id}
                    type="button"
                    className={`subwf-trig-select-item ${isSelected ? 'active' : ''}`}
                    onClick={() => updateMode(m.id)}
                  >
                    <div className="subwf-trig-select-item-content">
                      <span className="subwf-trig-select-item-title">{m.title}</span>
                      <span className="subwf-trig-select-item-desc">{m.desc}</span>
                    </div>
                    {isSelected && <span className="subwf-trig-select-check">✓</span>}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* 2. Workflow Input Schema */}
      {inputDataMode === 'fields' && (
        <div className="subwf-trig-schema-section">
          <div className="subwf-trig-schema-header">
            <span className="subwf-trig-schema-title">Workflow Input Schema</span>
            <button
              type="button"
              className="subwf-trig-icon-btn"
              title="Add Field"
              onClick={addField}
            >
              +
            </button>
          </div>

          {/* List of field cards */}
          <div className="subwf-trig-cards-list">
            {schemaFields.map((field, idx) => {
              const isCollapsed = Boolean(collapsedCards[idx])
              const fieldTypeObj = DATA_TYPES.find((t) => t.id === field.type) || DATA_TYPES[1]
              const isTypeOpen = openTypeIndex === idx

              return (
                <div key={idx} className="subwf-trig-card">
                  {/* Card Header */}
                  <div className="subwf-trig-card-head">
                    <button
                      type="button"
                      className="subwf-trig-card-toggle"
                      onClick={() => toggleCollapse(idx)}
                    >
                      <span className="subwf-trig-caret">{isCollapsed ? '▸' : '▾'}</span>
                      <span className="subwf-trig-card-idx">Values {idx + 1}</span>
                    </button>

                    <div className="subwf-trig-card-actions">
                      <button
                        type="button"
                        className="subwf-trig-action-btn"
                        title="Delete field"
                        onClick={() => removeField(idx)}
                      >
                        🗑️
                      </button>
                      <span className="subwf-trig-drag-handle" title="Reorder">
                        ⠿
                      </span>
                    </div>
                  </div>

                  {/* Card Body */}
                  {!isCollapsed && (
                    <div className="subwf-trig-card-body">
                      {/* Name Field */}
                      <div className="subwf-trig-input-group">
                        <label className="subwf-trig-input-label">Name</label>
                        <div className="subwf-trig-name-wrap">
                          <input
                            type="text"
                            className="subwf-trig-text-input"
                            placeholder="e.g. fieldName"
                            value={field.name || ''}
                            onChange={(e) => updateFieldItem(idx, 'name', e.target.value)}
                          />
                          {!field.name && (
                            <span className="subwf-trig-warning-icon" title="Field name is required">
                              ⚠️
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Type Field */}
                      <div className="subwf-trig-input-group">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <label className="subwf-trig-input-label">Type</label>
                          <span
                            className="subwf-trig-help-icon"
                            title="Expected data type for this field."
                          >
                            ?
                          </span>
                        </div>

                        <div className="subwf-trig-type-wrap">
                          <button
                            type="button"
                            className={`subwf-trig-type-btn ${isTypeOpen ? 'open' : ''}`}
                            onClick={() => setOpenTypeIndex(isTypeOpen ? null : idx)}
                          >
                            <span className="subwf-trig-type-label">{fieldTypeObj.label}</span>
                            <span className="subwf-trig-select-arrow">{isTypeOpen ? '▴' : '▾'}</span>
                          </button>

                          {isTypeOpen && (
                            <div className="subwf-trig-type-dropdown">
                              {DATA_TYPES.map((t) => {
                                const isSelected = t.id === field.type
                                return (
                                  <button
                                    key={t.id}
                                    type="button"
                                    className={`subwf-trig-type-item ${isSelected ? 'active' : ''}`}
                                    onClick={() => {
                                      updateFieldItem(idx, 'type', t.id)
                                      setOpenTypeIndex(null)
                                    }}
                                  >
                                    <span>{t.label}</span>
                                    {isSelected && <span className="subwf-trig-check">✓</span>}
                                  </button>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Add field button */}
          <div className="subwf-trig-add-field-wrap">
            <button
              type="button"
              className="subwf-trig-add-btn"
              onClick={addField}
            >
              <span>+</span> Add field
            </button>
          </div>
        </div>
      )}

      {/* Tip Banner */}
      <div className="subwf-trig-tip-banner">
        <strong>Tip:</strong> This node runs whenever an <strong>Execute Sub-workflow</strong> node calls this workflow. Values passed will match the schema above.
      </div>
    </div>
  )
}
