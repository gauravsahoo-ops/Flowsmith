import { useState, useMemo, useEffect, useRef } from 'react'
import MappingField from './MappingField'
import './FilterNodeEditor.css'

import { OPERATOR_CATEGORIES, CATEGORY_OPERATORS, UNARY_OPERATORS } from '../utils/filterOperators'

function generateId() {
  return Math.random().toString(36).slice(2, 10)
}

export default function FilterNodeEditor({
  node,
  onParamsChange,
  onSettingsChange,
  mapping = [],
  onPreview,
  tab = 'parameters',
}) {
  const params = node.parameters || {}
  const settings = node.settings || {}

  // Migrate or initialize conditions
  const conditions = useMemo(() => {
    if (Array.isArray(params.conditions) && params.conditions.length > 0) {
      return params.conditions
    }
    if (params.condition) {
      return [
        {
          id: generateId(),
          left: params.condition.left || '',
          operator: params.condition.operator || 'is equal to',
          right: params.condition.right || '',
          type: 'string',
          combinator: 'AND',
        },
      ]
    }
    return [
      {
        id: generateId(),
        left: '',
        operator: 'is equal to',
        right: '',
        type: 'string',
        combinator: 'AND',
      },
    ]
  }, [params.conditions, params.condition])

  const convertTypes = Boolean(params.convertTypes)
  const options = params.options || {}

  // Operator popover state
  const [openFlyoutId, setOpenFlyoutId] = useState(null)
  const [activeSubmenuCat, setActiveSubmenuCat] = useState(null)
  const popoverRef = useRef(null)

  // Options add menu state
  const [showOptionsDropdown, setShowOptionsDropdown] = useState(false)
  const optionsDropdownRef = useRef(null)

  // Settings dropdown state
  const [showOnErrorMenu, setShowOnErrorMenu] = useState(false)
  const onErrorRef = useRef(null)

  // Close menus on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        setOpenFlyoutId(null)
        setActiveSubmenuCat(null)
      }
      if (optionsDropdownRef.current && !optionsDropdownRef.current.contains(e.target)) {
        setShowOptionsDropdown(false)
      }
      if (onErrorRef.current && !onErrorRef.current.contains(e.target)) {
        setShowOnErrorMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function updateConditions(next) {
    onParamsChange({ ...params, conditions: next, condition: undefined })
  }

  function addCondition() {
    const next = [
      ...conditions,
      {
        id: generateId(),
        left: '',
        operator: 'is equal to',
        right: '',
        type: 'string',
        combinator: 'AND',
      },
    ]
    updateConditions(next)
  }

  function removeCondition(id) {
    if (conditions.length <= 1) {
      // Reset condition rather than leave empty array
      updateConditions([
        {
          id: generateId(),
          left: '',
          operator: 'is equal to',
          right: '',
          type: 'string',
          combinator: 'AND',
        },
      ])
      return
    }
    updateConditions(conditions.filter((c) => c.id !== id))
  }

  function updateCondition(id, patch) {
    const next = conditions.map((c) => (c.id === id ? { ...c, ...patch } : c))
    updateConditions(next)
  }

  function handleConvertTypes(val) {
    onParamsChange({ ...params, convertTypes: val })
  }

  function handleOptionChange(key, val) {
    const nextOptions = { ...options, [key]: val }
    if (val === undefined) delete nextOptions[key]
    onParamsChange({ ...params, options: nextOptions })
  }

  function setSetting(key, val) {
    if (onSettingsChange) {
      onSettingsChange(key, val)
    }
  }

  // Get icon for a given condition type
  function getTypeIcon(type) {
    const cat = OPERATOR_CATEGORIES.find((c) => c.id === type)
    return cat ? cat.icon : 'T'
  }

  // Find which category an operator belongs to if condition.type isn't explicitly set
  function getCategoryForOperator(operator, fallbackType = 'string') {
    if (fallbackType && CATEGORY_OPERATORS[fallbackType]?.some((o) => o.value === operator)) {
      return fallbackType
    }
    for (const [catId, ops] of Object.entries(CATEGORY_OPERATORS)) {
      if (ops.some((o) => o.value === operator)) return catId
    }
    return 'string'
  }

  // ================= PARAMETERS TAB =================
  if (tab === 'parameters') {
    return (
      <div className="filter-editor">
        <div className="filter-info-banner">
          Filter items in the workflow data stream. Only items satisfying the conditions below continue to subsequent nodes.
        </div>
        {/* Conditions Section Card */}
        <div className="filter-section">
          <div className="filter-section-header">
            <h4 className="filter-section-title">
              <span>Conditions</span>
            </h4>
            <span style={{ fontSize: 11, color: '#71717a' }}>
              {conditions.length} rule{conditions.length !== 1 ? 's' : ''}
            </span>
          </div>

          {conditions.map((cond, idx) => {
            const currentCat = cond.type || getCategoryForOperator(cond.operator, 'string')
            const isUnary = UNARY_OPERATORS.has(cond.operator)
            const isFlyoutOpen = openFlyoutId === cond.id

            return (
              <div key={cond.id} className="filter-condition-card">
                {/* Header with Combinator (if idx > 0) and remove button */}
                <div className="filter-condition-top">
                  {idx > 0 ? (
                    <button
                      type="button"
                      className="filter-combinator-badge"
                      title="Click to toggle AND / OR"
                      onClick={() =>
                        updateCondition(cond.id, {
                          combinator: cond.combinator === 'OR' ? 'AND' : 'OR',
                        })
                      }
                    >
                      {cond.combinator || 'AND'}
                    </button>
                  ) : (
                    <span className="filter-condition-index">
                      Condition #{idx + 1}
                    </span>
                  )}

                  <button
                    type="button"
                    className="filter-remove-btn"
                    onClick={() => removeCondition(cond.id)}
                    title="Remove condition"
                  >
                    🗑
                  </button>
                </div>

                {/* value1 field */}
                <div className="filter-field-group">
                  <div className="filter-input-row">
                    <MappingField
                      schema={{
                        title: '',
                        description: '{{ $json.myVariable }}',
                      }}
                      value={cond.left}
                      onChange={(v) => updateCondition(cond.id, { left: v ?? '' })}
                      path={`left_${idx}`}
                      mapping={mapping}
                      onPreview={onPreview}
                    />
                  </div>
                </div>

                {/* Operator Selector Button with Circular Checkmark Badge */}
                <div
                  className="filter-op-selector-row"
                  ref={isFlyoutOpen ? popoverRef : null}
                >
                  <button
                    type="button"
                    className={`filter-op-btn ${isFlyoutOpen ? 'active' : ''}`}
                    onClick={() => {
                      if (isFlyoutOpen) {
                        setOpenFlyoutId(null)
                        setActiveSubmenuCat(null)
                      } else {
                        setActiveSubmenuCat(null)
                        setOpenFlyoutId(cond.id)
                      }
                    }}
                  >
                    <span className="filter-op-type-icon">{getTypeIcon(currentCat)}</span>
                    <span className="filter-op-label">{cond.operator}</span>
                    <span className="filter-op-caret">▾</span>
                  </button>

                  {/* Circular Checkmark Badge */}
                  <span className="filter-valid-badge" title="Type valid">
                    ✓
                  </span>

                  {/* Cascading 2-Column Flyout Menu */}
                  {isFlyoutOpen && (
                    <div className={`filter-op-popover ${activeSubmenuCat ? 'has-submenu' : ''}`}>
                      {/* Left Column: Data Types */}
                      <div className="filter-op-categories">
                        {OPERATOR_CATEGORIES.map((cat) => (
                          <button
                            key={cat.id}
                            type="button"
                            className={`filter-op-cat-item ${
                              activeSubmenuCat === cat.id ? 'active' : ''
                            }`}
                            onMouseEnter={() => setActiveSubmenuCat(cat.id)}
                            onClick={() => setActiveSubmenuCat(cat.id)}
                          >
                            <span className="filter-op-cat-left">
                              <span className="filter-op-type-icon">{cat.icon}</span>
                              <span>{cat.label}</span>
                            </span>
                            <span className="filter-op-cat-arrow">&gt;</span>
                          </button>
                        ))}
                      </div>

                      {/* Right Column: Operators for Selected Type (shown only after category is clicked or hovered) */}
                      {activeSubmenuCat && (
                        <div className="filter-op-list">
                          {(CATEGORY_OPERATORS[activeSubmenuCat] || []).map((op) => {
                            const isSelected =
                              cond.operator === op.value && currentCat === activeSubmenuCat

                            return (
                              <button
                                key={op.value}
                                type="button"
                                className={`filter-op-item ${isSelected ? 'active' : ''}`}
                                onClick={() => {
                                  updateCondition(cond.id, {
                                    operator: op.value,
                                    type: activeSubmenuCat,
                                    // Clear right value if unary operator
                                    ...(op.unary ? { right: '' } : {}),
                                  })
                                  setOpenFlyoutId(null)
                                  setActiveSubmenuCat(null)
                                }}
                              >
                                <span>{op.label}</span>
                                {isSelected && (
                                  <span className="filter-op-item-check">✓</span>
                                )}
                              </button>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* value2 field (Hidden when operator is unary) */}
                {!isUnary && (
                  <div className="filter-field-group">
                    <div className="filter-input-row">
                      <MappingField
                        schema={{
                          title: '',
                          description: 'value to compare',
                        }}
                        value={cond.right}
                        onChange={(v) => updateCondition(cond.id, { right: v ?? '' })}
                        path={`right_${idx}`}
                        mapping={mapping}
                        onPreview={onPreview}
                      />
                    </div>
                  </div>
                )}
              </div>
            )
          })}

          {/* + Add condition button */}
          <button type="button" className="filter-add-btn" onClick={addCondition}>
            + Add condition
          </button>
        </div>

        {/* Convert types where required Toggle */}
        <div className="filter-section">
          <div className="filter-toggle-row">
            <div className="filter-toggle-info">
              <span className="filter-toggle-title">Convert types where required</span>
              <span className="filter-toggle-desc">
                Try to convert types to match the target type, e.g. '123' to 123
              </span>
            </div>
            <label className="filter-switch">
              <input
                type="checkbox"
                checked={convertTypes}
                onChange={(e) => handleConvertTypes(e.target.checked)}
              />
              <span className="filter-switch-slider" />
            </label>
          </div>
        </div>

        {/* Hint */}
        <div className="hint" style={{ fontSize: 11, background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 10px', marginTop: 10, marginBottom: 10 }}>
          <strong>Tip:</strong> Use <code>{'{{$json.field}}'}</code> for expressions. Items pass through if all conditions match (AND) or any matches (OR).
        </div>

        {/* Options Section */}
        <div className="filter-options-card" ref={optionsDropdownRef}>
          <div className="filter-options-header">
            <h4 className="filter-section-title">Options</h4>
            <button
              type="button"
              className="filter-options-add-btn"
              title="Add Option"
              onClick={() => setShowOptionsDropdown(!showOptionsDropdown)}
            >
              +
            </button>
          </div>

          {/* If ignoreCase option is enabled */}
          {options.ignoreCase !== undefined ? (
            <div className="filter-option-item-row">
              <div className="filter-option-item-title">
                <span>Ignore Case</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <label className="filter-switch">
                  <input
                    type="checkbox"
                    checked={Boolean(options.ignoreCase)}
                    onChange={(e) => handleOptionChange('ignoreCase', e.target.checked)}
                  />
                  <span className="filter-switch-slider" />
                </label>
                <button
                  type="button"
                  className="filter-remove-btn"
                  title="Remove option"
                  onClick={() => handleOptionChange('ignoreCase', undefined)}
                >
                  ✕
                </button>
              </div>
            </div>
          ) : (
            <div style={{ position: 'relative', marginTop: 4 }}>
              <button
                type="button"
                className="filter-add-btn"
                onClick={() => setShowOptionsDropdown(!showOptionsDropdown)}
              >
                + Add option
              </button>

              {/* Options Popover Menu */}
              {showOptionsDropdown && (
                <div
                  className="filter-on-error-menu"
                  style={{ top: 'calc(100% + 4px)', minWidth: 160 }}
                >
                  <div
                    className="filter-on-error-option"
                    onClick={() => {
                      handleOptionChange('ignoreCase', true)
                      setShowOptionsDropdown(false)
                    }}
                  >
                    <span className="filter-on-error-title">Ignore Case</span>
                    <span className="filter-on-error-desc">
                      Case-insensitive string comparisons
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>


      </div>
    )
  }

  // ================= SETTINGS TAB =================
  return (
    <div className="filter-editor">
      <div className="filter-settings-card">
        {/* Always Output Data */}
        <div className="filter-toggle-row">
          <div className="filter-toggle-info">
            <span className="filter-toggle-title">Always Output Data</span>
            <span className="filter-toggle-desc">
              When active, node will produce an empty output item instead of nothing
              when there is no data to output.
            </span>
          </div>
          <label className="filter-switch">
            <input
              type="checkbox"
              checked={Boolean(settings.alwaysOutputData)}
              onChange={(e) => setSetting('alwaysOutputData', e.target.checked)}
            />
            <span className="filter-switch-slider" />
          </label>
        </div>

        {/* Execute Once */}
        <div className="filter-toggle-row" style={{ borderTop: '1px solid #27272a', paddingTop: 12 }}>
          <div className="filter-toggle-info">
            <span className="filter-toggle-title">
              Execute Once <span title="Only execute once per workflow run" style={{ cursor: 'help', color: '#71717a' }}>ⓘ</span>
            </span>
            <span className="filter-toggle-desc">
              Only execute once per workflow run.
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <label className="filter-switch">
              <input
                type="checkbox"
                checked={Boolean(settings.executeOnce)}
                onChange={(e) => setSetting('executeOnce', e.target.checked)}
              />
              <span className="filter-switch-slider" />
            </label>
            <button
              type="button"
              className="filter-options-add-btn"
              style={{ width: 18, height: 18, fontSize: 11 }}
              title="More actions"
            >
              ⋮
            </button>
          </div>
        </div>

        {/* Retry On Fail */}
        <div className="filter-toggle-row" style={{ borderTop: '1px solid #27272a', paddingTop: 12 }}>
          <div className="filter-toggle-info">
            <span className="filter-toggle-title">Retry On Fail</span>
            <span className="filter-toggle-desc">
              Retry node execution if it fails.
            </span>
          </div>
          <label className="filter-switch">
            <input
              type="checkbox"
              checked={Boolean(settings.retryOnFail)}
              onChange={(e) => setSetting('retryOnFail', e.target.checked)}
            />
            <span className="filter-switch-slider" />
          </label>
        </div>

        {settings.retryOnFail && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, padding: '4px 0' }}>
            <div className="filter-field-group">
              <label className="filter-field-label">Max Tries</label>
              <input
                type="number"
                min={1}
                max={10}
                className="filter-text-input"
                value={settings.maxTries ?? 3}
                onChange={(e) => setSetting('maxTries', Number(e.target.value))}
              />
            </div>
            <div className="filter-field-group">
              <label className="filter-field-label">Wait Between Tries (ms)</label>
              <input
                type="number"
                min={0}
                className="filter-text-input"
                value={settings.waitBetweenTries ?? 1000}
                onChange={(e) => setSetting('waitBetweenTries', Number(e.target.value))}
              />
            </div>
          </div>
        )}

        {/* On Error Custom Dropdown */}
        <div
          className="filter-on-error-wrapper"
          ref={onErrorRef}
          style={{ borderTop: '1px solid #27272a', paddingTop: 12 }}
        >
          <label className="filter-field-label" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span>On Error</span>
            <span title="Action to take when an error occurs" style={{ cursor: 'help' }}>ⓘ</span>
          </label>

          <button
            type="button"
            className={`filter-on-error-trigger ${showOnErrorMenu ? 'open' : ''}`}
            onClick={() => setShowOnErrorMenu(!showOnErrorMenu)}
          >
            <span>
              {settings.onError === 'continue'
                ? 'Continue'
                : settings.onError === 'continueWithError'
                ? 'Continue (using error output)'
                : 'Stop Workflow'}
            </span>
            <span style={{ fontSize: 10, color: '#71717a' }}>▾</span>
          </button>

          {showOnErrorMenu && (
            <div className="filter-on-error-menu">
              <div
                className={`filter-on-error-option ${
                  !settings.onError || settings.onError === 'stop' ? 'selected' : ''
                }`}
                onClick={() => {
                  setSetting('onError', 'stop')
                  setShowOnErrorMenu(false)
                }}
              >
                <span className="filter-on-error-title">Stop Workflow</span>
                <span className="filter-on-error-desc">
                  Halt execution and fail workflow
                </span>
              </div>

              <div
                className={`filter-on-error-option ${
                  settings.onError === 'continue' ? 'selected' : ''
                }`}
                onClick={() => {
                  setSetting('onError', 'continue')
                  setShowOnErrorMenu(false)
                }}
              >
                <span className="filter-on-error-title">Continue</span>
                <span className="filter-on-error-desc">
                  Pass error message as item in regular output
                </span>
              </div>

              <div
                className={`filter-on-error-option ${
                  settings.onError === 'continueWithError' ? 'selected' : ''
                }`}
                onClick={() => {
                  setSetting('onError', 'continueWithError')
                  setShowOnErrorMenu(false)
                }}
              >
                <span className="filter-on-error-title">
                  Continue (using error output)
                </span>
                <span className="filter-on-error-desc">
                  Pass item to an extra 'error' output
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Notes Textarea */}
        <div className="filter-field-group" style={{ borderTop: '1px solid #27272a', paddingTop: 12 }}>
          <label className="filter-field-label">Notes</label>
          <textarea
            className="filter-notes-textarea"
            placeholder="e.g. In charge of sending the reminder email to customer..."
            value={settings.notes || ''}
            onChange={(e) => setSetting('notes', e.target.value)}
          />
        </div>

        {/* Display Note in Flow? */}
        <div className="filter-toggle-row">
          <div className="filter-toggle-info">
            <span className="filter-toggle-title">Display Note in Flow?</span>
            <span className="filter-toggle-desc">
              When active, this note will be displayed in the workflow canvas.
            </span>
          </div>
          <label className="filter-switch">
            <input
              type="checkbox"
              checked={Boolean(settings.displayNoteInFlow)}
              onChange={(e) => setSetting('displayNoteInFlow', e.target.checked)}
            />
            <span className="filter-switch-slider" />
          </label>
        </div>

        {/* Version Footer */}
        <div className="filter-version-footer">
          <span>Filter node version 2.3 (Latest)</span>
          <a
            href="https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.filter/"
            target="_blank"
            rel="noopener noreferrer"
            className="filter-version-link"
          >
            <span>Docs</span>
            <span>↗</span>
          </a>
        </div>
      </div>
    </div>
  )
}
