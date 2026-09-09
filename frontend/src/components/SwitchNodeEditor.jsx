import { useState, useRef, useEffect } from 'react'
import MappingField from './MappingField'
import { OPERATOR_CATEGORIES, CATEGORY_OPERATORS } from './FilterNodeEditor'
import './SwitchNodeEditor.css'

const MODES = [
  {
    id: 'rules',
    title: 'Rules',
    desc: 'Build a matching rule for each output',
  },
  {
    id: 'expression',
    title: 'Expression',
    desc: 'Write an expression to return the output index',
  },
]

const AVAILABLE_OPTIONS = [
  { id: 'fallbackOutput', label: 'Fallback Output' },
  { id: 'ignoreCase', label: 'Ignore Case' },
  { id: 'sendToAllMatching', label: 'Send data to all matching outputs' },
]

function generateId() {
  return Math.random().toString(36).slice(2, 10)
}

function getCategoryForOperator(operator) {
  for (const [catId, ops] of Object.entries(CATEGORY_OPERATORS)) {
    if (ops.some((o) => o.value === operator)) return catId
  }
  return 'string'
}

function getTypeIcon(catId) {
  const cat = OPERATOR_CATEGORIES.find((c) => c.id === catId)
  return cat ? cat.icon : 'T'
}

export default function SwitchNodeEditor({
  node,
  onParamsChange,
  mapping = [],
  onPreview,
}) {
  const params = node.parameters || {}
  const mode = params.mode || 'rules'
  const expression = params.expression || ''
  const convertTypes = Boolean(params.convert_types ?? params.convertTypes)
  const options = params.options || {}

  // Rules list
  const rules = Array.isArray(params.rules) && params.rules.length > 0
    ? params.rules
    : [{ id: generateId(), value1: '', operator: 'is equal to', value2: '', rename_output: false, output_name: '' }]

  // UI state
  const [modeMenuOpen, setModeMenuOpen] = useState(false)
  const [optionsMenuOpen, setOptionsMenuOpen] = useState(false)
  const [collapsedCards, setCollapsedCards] = useState({})
  const [openOperatorRuleId, setOpenOperatorRuleId] = useState(null)
  const [activeSubmenuCat, setActiveSubmenuCat] = useState('string')

  const modeMenuRef = useRef(null)
  const optionsMenuRef = useRef(null)
  const operatorMenuRef = useRef(null)

  // Click outside listeners
  useEffect(() => {
    function handleClickOutside(e) {
      if (modeMenuRef.current && !modeMenuRef.current.contains(e.target)) {
        setModeMenuOpen(false)
      }
      if (optionsMenuRef.current && !optionsMenuRef.current.contains(e.target)) {
        setOptionsMenuOpen(false)
      }
      if (operatorMenuRef.current && !operatorMenuRef.current.contains(e.target)) {
        setOpenOperatorRuleId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function updateParams(patch) {
    onParamsChange({ ...params, ...patch })
  }

  function updateRules(nextRules) {
    updateParams({ rules: nextRules })
  }

  function addRule() {
    const next = [
      ...rules,
      {
        id: generateId(),
        value1: '',
        operator: 'is equal to',
        value2: '',
        rename_output: false,
        output_name: '',
        output: `route_${rules.length}`,
      },
    ]
    updateRules(next)
  }

  function removeRule(id) {
    if (rules.length <= 1) {
      updateRules([{ id: generateId(), value1: '', operator: 'is equal to', value2: '', rename_output: false, output_name: '' }])
      return
    }
    updateRules(rules.filter((r) => r.id !== id))
  }

  function updateRule(id, patch) {
    updateRules(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  }

  function toggleCollapse(id) {
    setCollapsedCards((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  function handleOptionChange(key, val) {
    const nextOptions = { ...options, [key]: val }
    if (val === undefined) delete nextOptions[key]
    updateParams({ options: nextOptions })
  }

  const selectedMode = MODES.find((m) => m.id === mode) || MODES[0]
  const unusedOptions = AVAILABLE_OPTIONS.filter((opt) => options[opt.id] === undefined)

  return (
    <div className="switch-editor">
      {/* 1. Mode Selector Card */}
      <div className="switch-section-card" ref={modeMenuRef}>
        <div className="switch-field-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <label className="switch-field-label">Mode</label>
            <span
              className="switch-help-icon"
              title="Whether to route items using matching rules or a custom expression returning the output index."
            >
              ?
            </span>
          </div>
        </div>

        <div className="switch-select-wrap">
          <button
            type="button"
            className={`switch-select-btn ${modeMenuOpen ? 'open' : ''}`}
            onClick={() => setModeMenuOpen(!modeMenuOpen)}
          >
            <div className="switch-select-value">
              <span className="switch-select-title">{selectedMode.title}</span>
              <span className="switch-select-desc">{selectedMode.desc}</span>
            </div>
            <span className="switch-select-arrow">{modeMenuOpen ? '▴' : '▾'}</span>
          </button>

          {modeMenuOpen && (
            <div className="switch-select-dropdown">
              {MODES.map((m) => {
                const isSelected = m.id === mode
                return (
                  <button
                    key={m.id}
                    type="button"
                    className={`switch-select-item ${isSelected ? 'active' : ''}`}
                    onClick={() => {
                      updateParams({ mode: m.id })
                      setModeMenuOpen(false)
                    }}
                  >
                    <div className="switch-select-item-content">
                      <span className="switch-select-item-title">{m.title}</span>
                      <span className="switch-select-item-desc">{m.desc}</span>
                    </div>
                    {isSelected && <span className="switch-select-check">✓</span>}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* 2. Routing Rules (When mode === 'rules') */}
      {mode === 'rules' && (
        <div className="switch-section-card">
          <div className="switch-section-header">
            <div className="switch-section-title-wrap">
              <span className="switch-section-title">Routing Rules</span>
              <span className="switch-section-badge">{rules.length}</span>
            </div>
            <button
              type="button"
              className="switch-icon-btn"
              title="Add Routing Rule"
              onClick={addRule}
            >
              +
            </button>
          </div>

          <div className="switch-rules-list">
            {rules.map((rule, idx) => {
              const isCollapsed = Boolean(collapsedCards[rule.id])
              const currentCat = getCategoryForOperator(rule.operator)
              const typeIcon = getTypeIcon(currentCat)
              const opMeta = (CATEGORY_OPERATORS[currentCat] || []).find((o) => o.value === rule.operator)
              const isUnary = Boolean(opMeta?.unary)
              const ruleTitle = rule.rename_output && rule.output_name
                ? rule.output_name
                : `Routing Rule ${idx + 1}`

              return (
                <div key={rule.id} className="switch-rule-card">
                  {/* Rule Header */}
                  <div
                    className="switch-rule-card-header"
                    onClick={() => toggleCollapse(rule.id)}
                  >
                    <div className="switch-rule-card-title">
                      <span className="switch-collapse-icon">
                        {isCollapsed ? '▸' : '▾'}
                      </span>
                      <span className="switch-rule-card-label">{ruleTitle}</span>
                      {rule.value1 && (
                        <span className="switch-rule-preview">
                          ({rule.value1} {rule.operator} {isUnary ? '' : rule.value2 || '...'})
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      className="switch-remove-btn"
                      title="Remove this rule"
                      onClick={(e) => {
                        e.stopPropagation()
                        removeRule(rule.id)
                      }}
                    >
                      ✕
                    </button>
                  </div>

                  {/* Rule Body */}
                  {!isCollapsed && (
                    <div className="switch-rule-card-body">
                      {/* Value 1 */}
                      <div className="switch-field-group">
                        <MappingField
                          schema={{
                            title: 'Value 1',
                            description: 'Value or expression to compare, e.g. {{$json.type}}',
                          }}
                          value={rule.value1 ?? rule.left ?? ''}
                          onChange={(v) => updateRule(rule.id, { value1: v, left: v })}
                          placeholder="value1"
                          path={`rule_${rule.id}_val1`}
                          mapping={mapping}
                          onPreview={onPreview}
                        />
                      </div>

                      {/* Operator Category Selector Dropdown */}
                      <div
                        className="switch-field-group"
                        style={{ position: 'relative' }}
                        ref={openOperatorRuleId === rule.id ? operatorMenuRef : null}
                      >
                        <button
                          type="button"
                          className={`switch-operator-btn ${openOperatorRuleId === rule.id ? 'open' : ''}`}
                          onClick={() => {
                            setActiveSubmenuCat(currentCat)
                            setOpenOperatorRuleId(openOperatorRuleId === rule.id ? null : rule.id)
                          }}
                        >
                          <span className="switch-operator-btn-left">
                            <span className="switch-op-type-icon">{typeIcon}</span>
                            <span>{rule.operator || 'is equal to'}</span>
                          </span>
                          <span className="switch-operator-btn-arrow">▾</span>
                        </button>

                        {/* Two-Column Category Flyout Menu matching Screenshot 3 */}
                        {openOperatorRuleId === rule.id && (
                          <div className="switch-op-flyout-container">
                            {/* Left: Categories */}
                            <div className="switch-op-cats">
                              {OPERATOR_CATEGORIES.map((cat) => (
                                <button
                                  key={cat.id}
                                  type="button"
                                  className={`switch-op-cat-item ${activeSubmenuCat === cat.id ? 'active' : ''}`}
                                  onMouseEnter={() => setActiveSubmenuCat(cat.id)}
                                  onClick={() => setActiveSubmenuCat(cat.id)}
                                >
                                  <span className="switch-op-cat-left">
                                    <span className="switch-op-type-icon">{cat.icon}</span>
                                    <span>{cat.label}</span>
                                  </span>
                                  <span className="switch-op-cat-arrow">&gt;</span>
                                </button>
                              ))}
                            </div>

                            {/* Right: Operators for Selected Category */}
                            <div className="switch-op-list">
                              {(CATEGORY_OPERATORS[activeSubmenuCat] || []).map((op) => {
                                const isSelected = rule.operator === op.value && currentCat === activeSubmenuCat
                                return (
                                  <button
                                    key={op.value}
                                    type="button"
                                    className={`switch-op-item ${isSelected ? 'active' : ''}`}
                                    onClick={() => {
                                      updateRule(rule.id, {
                                        operator: op.value,
                                        ...(op.unary ? { value2: '', right: '' } : {}),
                                      })
                                      setOpenOperatorRuleId(null)
                                    }}
                                  >
                                    <span>{op.label}</span>
                                    {isSelected && <span className="switch-op-check">✓</span>}
                                  </button>
                                )
                              })}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Value 2 (hidden for unary operators like 'exists', 'is empty') */}
                      {!isUnary && (
                        <div className="switch-field-group">
                          <MappingField
                            schema={{
                              title: 'Value 2',
                              description: 'Second value or expression to compare against',
                            }}
                            value={rule.value2 ?? rule.right ?? ''}
                            onChange={(v) => updateRule(rule.id, { value2: v, right: v })}
                            placeholder="value2"
                            path={`rule_${rule.id}_val2`}
                            mapping={mapping}
                            onPreview={onPreview}
                          />
                        </div>
                      )}

                      {/* Rename Output Toggle */}
                      <div className="switch-toggle-row" style={{ marginTop: 2 }}>
                        <span className="switch-toggle-label">Rename Output</span>
                        <label className="switch-switch">
                          <input
                            type="checkbox"
                            checked={Boolean(rule.rename_output)}
                            onChange={(e) => updateRule(rule.id, { rename_output: e.target.checked })}
                          />
                          <span className="switch-switch-slider" />
                        </label>
                      </div>

                      {rule.rename_output && (
                        <div className="switch-field-group" style={{ marginTop: 4 }}>
                          <input
                            type="text"
                            className="switch-text-input"
                            placeholder="e.g. VIP Customers"
                            value={rule.output_name || ''}
                            onChange={(e) => updateRule(rule.id, { output_name: e.target.value })}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          <button
            type="button"
            className="switch-add-btn"
            onClick={addRule}
          >
            <span>+</span> Add Routing Rule
          </button>
        </div>
      )}

      {/* 3. Expression Mode Field (When mode === 'expression') */}
      {mode === 'expression' && (
        <div className="switch-section-card">
          <div className="switch-field-group">
            <MappingField
              schema={{
                title: 'Output Index Expression',
                description: 'Write an expression returning the output index (0, 1, 2, ...) or branch name',
              }}
              value={expression}
              onChange={(v) => updateParams({ expression: v })}
              placeholder="e.g. {{ $json.status === 'active' ? 0 : 1 }}"
              path="expression"
              mapping={mapping}
              onPreview={onPreview}
            />
          </div>
        </div>
      )}

      {/* 4. Convert Types Where Required */}
      <div className="switch-section-card">
        <div className="switch-toggle-row">
          <div className="switch-toggle-label-wrap">
            <span className="switch-toggle-label">Convert types where required</span>
            <span
              className="switch-help-icon"
              title="When enabled, numbers as strings ('10' == 10) or booleans ('true' == true) are coerced for comparison."
            >
              ?
            </span>
          </div>
          <label className="switch-switch">
            <input
              type="checkbox"
              checked={convertTypes}
              onChange={(e) => updateParams({ convert_types: e.target.checked, convertTypes: e.target.checked })}
            />
            <span className="switch-switch-slider" />
          </label>
        </div>
      </div>

      {/* 5. Options Section */}
      <div className="switch-section-card" ref={optionsMenuRef}>
        <div className="switch-section-header">
          <div className="switch-section-title-wrap">
            <span className="switch-section-title">Options</span>
            <span className="switch-section-badge">{Object.keys(options).length}</span>
          </div>
          {unusedOptions.length > 0 && (
            <button
              type="button"
              className="switch-icon-btn"
              title="Add Option"
              onClick={() => setOptionsMenuOpen(!optionsMenuOpen)}
            >
              +
            </button>
          )}
        </div>

        {/* Fallback Output Option */}
        {options.fallbackOutput !== undefined && (
          <div className="switch-option-item">
            <div className="switch-toggle-row">
              <div className="switch-toggle-label-wrap">
                <span className="switch-toggle-label">Fallback Output</span>
                <span
                  className="switch-help-icon"
                  title="Route unmatched items to an extra fallback output branch."
                >
                  ?
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <label className="switch-switch">
                  <input
                    type="checkbox"
                    checked={Boolean(options.fallbackOutput)}
                    onChange={(e) => handleOptionChange('fallbackOutput', e.target.checked)}
                  />
                  <span className="switch-switch-slider" />
                </label>
                <button
                  type="button"
                  className="switch-remove-btn"
                  title="Remove option"
                  onClick={() => handleOptionChange('fallbackOutput', undefined)}
                >
                  ✕
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Ignore Case Option */}
        {options.ignoreCase !== undefined && (
          <div className="switch-option-item">
            <div className="switch-toggle-row">
              <div className="switch-toggle-label-wrap">
                <span className="switch-toggle-label">Ignore Case</span>
                <span
                  className="switch-help-icon"
                  title="Case-insensitive string comparisons."
                >
                  ?
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <label className="switch-switch">
                  <input
                    type="checkbox"
                    checked={Boolean(options.ignoreCase)}
                    onChange={(e) => handleOptionChange('ignoreCase', e.target.checked)}
                  />
                  <span className="switch-switch-slider" />
                </label>
                <button
                  type="button"
                  className="switch-remove-btn"
                  title="Remove option"
                  onClick={() => handleOptionChange('ignoreCase', undefined)}
                >
                  ✕
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Send Data To All Matching Outputs Option */}
        {options.sendToAllMatching !== undefined && (
          <div className="switch-option-item">
            <div className="switch-toggle-row">
              <div className="switch-toggle-label-wrap">
                <span className="switch-toggle-label">Send data to all matching outputs</span>
                <span
                  className="switch-help-icon"
                  title="When active, items will be sent to every rule that matches instead of just the first one."
                >
                  ?
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <label className="switch-switch">
                  <input
                    type="checkbox"
                    checked={Boolean(options.sendToAllMatching)}
                    onChange={(e) => handleOptionChange('sendToAllMatching', e.target.checked)}
                  />
                  <span className="switch-switch-slider" />
                </label>
                <button
                  type="button"
                  className="switch-remove-btn"
                  title="Remove option"
                  onClick={() => handleOptionChange('sendToAllMatching', undefined)}
                >
                  ✕
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Add Option button */}
        {unusedOptions.length > 0 && (
          <div className="switch-add-option-wrap">
            <button
              type="button"
              className="switch-add-btn"
              onClick={() => setOptionsMenuOpen(!optionsMenuOpen)}
            >
              <span>+</span> Add option
            </button>

            {optionsMenuOpen && (
              <div className="switch-popover-menu">
                {unusedOptions.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className="switch-popover-item"
                    onClick={() => {
                      handleOptionChange(opt.id, true)
                      setOptionsMenuOpen(false)
                    }}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tip Banner */}
      <div className="switch-tip-banner">
        <strong>Tip:</strong> Use <code>{'{{$json.field}}'}</code> for expressions. Items are evaluated against rules and routed to the corresponding output handle.
      </div>
    </div>
  )
}
