import { useState, useRef, useEffect } from 'react'
import MappingField from './MappingField'
import './CompareDatasetsEditor.css'

const DIFFERENCE_MODES = [
  {
    id: 'includeBoth',
    title: 'Include Both Versions',
    desc: 'Output contains all data (but structure more complex)',
  },
  {
    id: 'useA',
    title: 'Use Input A Version',
    desc: 'Keep the version from Input A when differences are found',
  },
  {
    id: 'useB',
    title: 'Use Input B Version',
    desc: 'Keep the version from Input B when differences are found',
  },
  {
    id: 'useMix',
    title: 'Use a Mix of Versions',
    desc: 'Output uses different inputs for different fields',
  },
]

const AVAILABLE_OPTIONS = [
  { id: 'fieldsToSkip', label: 'Fields to Skip Comparing' },
  { id: 'disableDotNotation', label: 'Disable Dot Notation' },
  { id: 'multipleMatches', label: 'Multiple Matches' },
]

function generateId() {
  return Math.random().toString(36).slice(2, 10)
}

export default function CompareDatasetsEditor({
  node,
  onParamsChange,
  mapping = [],
  onPreview,
}) {
  const params = node.parameters || {}

  // Fields to match list
  const fieldsToMatch = Array.isArray(params.fieldsToMatch) && params.fieldsToMatch.length > 0
    ? params.fieldsToMatch
    : (params.key_fields && params.key_fields.length > 0
        ? params.key_fields.map(k => ({ id: generateId(), fieldA: k, fieldB: k }))
        : [{ id: generateId(), fieldA: '', fieldB: '' }])

  const whenThereAreDifferences = params.whenThereAreDifferences || 'includeBoth'
  const fuzzyCompare = Boolean(params.fuzzyCompare)
  const options = params.options || {}

  // Collapsed state for match cards
  const [collapsedCards, setCollapsedCards] = useState({})
  // Dropdown states
  const [diffMenuOpen, setDiffMenuOpen] = useState(false)
  const [optionsMenuOpen, setOptionsMenuOpen] = useState(false)
  const [showFuzzyTooltip, setShowFuzzyTooltip] = useState(false)

  const diffMenuRef = useRef(null)
  const optionsMenuRef = useRef(null)

  // Click outside listener
  useEffect(() => {
    function handleClickOutside(e) {
      if (diffMenuRef.current && !diffMenuRef.current.contains(e.target)) {
        setDiffMenuOpen(false)
      }
      if (optionsMenuRef.current && !optionsMenuRef.current.contains(e.target)) {
        setOptionsMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function updateFieldsToMatch(next) {
    onParamsChange({
      ...params,
      fieldsToMatch: next,
      // Keep legacy key_fields synced for backwards compatibility
      key_fields: next.map(f => f.fieldA).filter(Boolean),
      merge_by: next.length > 0 ? 'key_fields' : 'all_fields',
    })
  }

  function addFieldMatch() {
    const next = [...fieldsToMatch, { id: generateId(), fieldA: '', fieldB: '' }]
    updateFieldsToMatch(next)
  }

  function removeFieldMatch(id) {
    if (fieldsToMatch.length <= 1) {
      updateFieldsToMatch([{ id: generateId(), fieldA: '', fieldB: '' }])
      return
    }
    updateFieldsToMatch(fieldsToMatch.filter(f => f.id !== id))
  }

  function updateFieldMatch(id, patch) {
    updateFieldsToMatch(fieldsToMatch.map(f => f.id === id ? { ...f, ...patch } : f))
  }

  function toggleCollapse(id) {
    setCollapsedCards(prev => ({ ...prev, [id]: !prev[id] }))
  }

  function setDiffMode(modeId) {
    onParamsChange({ ...params, whenThereAreDifferences: modeId })
    setDiffMenuOpen(false)
  }

  function toggleFuzzyCompare(val) {
    onParamsChange({ ...params, fuzzyCompare: val })
  }

  function handleOptionChange(key, val) {
    const nextOptions = { ...options, [key]: val }
    if (val === undefined) delete nextOptions[key]
    onParamsChange({ ...params, options: nextOptions })
  }

  const selectedDiffOption = DIFFERENCE_MODES.find(m => m.id === whenThereAreDifferences) || DIFFERENCE_MODES[0]

  const unusedOptions = AVAILABLE_OPTIONS.filter(opt => options[opt.id] === undefined)

  return (
    <div className="compare-editor">
      {/* Top Banner */}
      <div className="compare-info-banner">
        Items from different branches are paired together when the fields below match. If paired, the rest of the fields are compared to determine whether the items are the same or different.
      </div>

      {/* Fields to Match Section */}
      <div className="compare-section-card">
        <div className="compare-section-header">
          <h4 className="compare-section-title">Fields to Match</h4>
          <button
            type="button"
            className="compare-icon-btn"
            title="Add Fields to Match"
            onClick={addFieldMatch}
          >
            +
          </button>
        </div>

        {fieldsToMatch.map((match, idx) => {
          const isCollapsed = Boolean(collapsedCards[match.id])
          return (
            <div key={match.id} className="compare-match-card">
              <div
                className="compare-match-card-header"
                onClick={() => toggleCollapse(match.id)}
              >
                <div className="compare-match-card-title">
                  <span className={`compare-match-card-arrow ${!isCollapsed ? 'open' : ''}`}>
                    ›
                  </span>
                  <span>Values {idx + 1}</span>
                  {(match.fieldA || match.fieldB) && (
                    <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>
                      ({match.fieldA || '—'} = {match.fieldB || '—'})
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  className="filter-remove-btn"
                  title="Remove this field match"
                  onClick={(e) => {
                    e.stopPropagation()
                    removeFieldMatch(match.id)
                  }}
                >
                  ✕
                </button>
              </div>

              {!isCollapsed && (
                <>
                  <div className="compare-field-group">
                    <label className="compare-field-label">Input A Field</label>
                    <input
                      type="text"
                      className="compare-field-input"
                      placeholder="e.g. id"
                      value={match.fieldA || ''}
                      onChange={(e) => updateFieldMatch(match.id, { fieldA: e.target.value })}
                    />
                    <span className="compare-field-hint">Enter the field name as text</span>
                  </div>

                  <div className="compare-field-group">
                    <label className="compare-field-label">Input B Field</label>
                    <input
                      type="text"
                      className="compare-field-input"
                      placeholder="e.g. id"
                      value={match.fieldB || ''}
                      onChange={(e) => updateFieldMatch(match.id, { fieldB: e.target.value })}
                    />
                    <span className="compare-field-hint">Enter the field name as text</span>
                  </div>
                </>
              )}
            </div>
          )
        })}

        <button
          type="button"
          className="compare-add-btn"
          onClick={addFieldMatch}
        >
          + Add Fields to Match
        </button>
      </div>

      {/* When There Are Differences */}
      <div className="compare-field-group" ref={diffMenuRef}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <label className="compare-field-label">When There Are Differences</label>
          <span style={{ fontSize: 10, color: '#64748b' }}>Fixed</span>
        </div>

        <div className="compare-select-wrap">
          <button
            type="button"
            className={`compare-select-btn ${diffMenuOpen ? 'open' : ''}`}
            onClick={() => setDiffMenuOpen(!diffMenuOpen)}
          >
            <span>{selectedDiffOption.title}</span>
            <span style={{ fontSize: 9, color: '#94a3b8' }}>{diffMenuOpen ? '▲' : '▼'}</span>
          </button>

          {diffMenuOpen && (
            <div className="compare-select-dropdown">
              {DIFFERENCE_MODES.map((mode) => {
                const isSelected = mode.id === whenThereAreDifferences
                return (
                  <button
                    key={mode.id}
                    type="button"
                    className={`compare-select-item ${isSelected ? 'active' : ''}`}
                    onClick={() => setDiffMode(mode.id)}
                  >
                    <span className="compare-select-item-title">{mode.title}</span>
                    {mode.desc && (
                      <span className="compare-select-item-desc">{mode.desc}</span>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Fuzzy Compare Toggle */}
      <div className="compare-toggle-row" style={{ position: 'relative' }}>
        <div className="compare-toggle-label">
          <span>Fuzzy Compare</span>
          <span
            className="compare-help-icon"
            onMouseEnter={() => setShowFuzzyTooltip(true)}
            onMouseLeave={() => setShowFuzzyTooltip(false)}
          >
            ⓘ
          </span>
          {showFuzzyTooltip && (
            <div className="compare-tooltip-bubble">
              Whether to tolerate small type differences when comparing fields. E.g. the number 3 and the string &apos;3&apos; are treated as the same.
            </div>
          )}
        </div>
        <label className="filter-switch">
          <input
            type="checkbox"
            checked={fuzzyCompare}
            onChange={(e) => toggleFuzzyCompare(e.target.checked)}
          />
          <span className="filter-switch-slider" />
        </label>
      </div>

      {/* Options Section */}
      <div className="compare-section-card" ref={optionsMenuRef} style={{ position: 'relative' }}>
        <div className="compare-section-header">
          <h4 className="compare-section-title">Options</h4>
          {unusedOptions.length > 0 && (
            <button
              type="button"
              className="compare-icon-btn"
              title="Add Option"
              onClick={() => setOptionsMenuOpen(!optionsMenuOpen)}
            >
              +
            </button>
          )}
        </div>

        {/* Render Active Options */}
        {options.fieldsToSkip !== undefined && (
          <div className="compare-field-group">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <label className="compare-field-label">Fields to Skip Comparing</label>
              <button
                type="button"
                className="filter-remove-btn"
                title="Remove option"
                onClick={() => handleOptionChange('fieldsToSkip', undefined)}
              >
                ✕
              </button>
            </div>
            <input
              type="text"
              className="compare-field-input"
              placeholder="e.g. updatedAt, timestamp"
              value={options.fieldsToSkip || ''}
              onChange={(e) => handleOptionChange('fieldsToSkip', e.target.value)}
            />
            <span className="compare-field-hint">Comma-separated list of fields to ignore during comparison</span>
          </div>
        )}

        {options.disableDotNotation !== undefined && (
          <div className="compare-toggle-row">
            <div className="compare-toggle-label">
              <span>Disable Dot Notation</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <label className="filter-switch">
                <input
                  type="checkbox"
                  checked={Boolean(options.disableDotNotation)}
                  onChange={(e) => handleOptionChange('disableDotNotation', e.target.checked)}
                />
                <span className="filter-switch-slider" />
              </label>
              <button
                type="button"
                className="filter-remove-btn"
                title="Remove option"
                onClick={() => handleOptionChange('disableDotNotation', undefined)}
              >
                ✕
              </button>
            </div>
          </div>
        )}

        {options.multipleMatches !== undefined && (
          <div className="compare-field-group">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <label className="compare-field-label">Multiple Matches</label>
              <button
                type="button"
                className="filter-remove-btn"
                title="Remove option"
                onClick={() => handleOptionChange('multipleMatches', undefined)}
              >
                ✕
              </button>
            </div>
            <select
              className="compare-field-input"
              value={options.multipleMatches || 'first'}
              onChange={(e) => handleOptionChange('multipleMatches', e.target.value)}
            >
              <option value="first">Include First Match Only</option>
              <option value="all">Include All Matches</option>
            </select>
          </div>
        )}

        {/* Add Option button */}
        {unusedOptions.length > 0 && (
          <div>
            <button
              type="button"
              className="compare-add-btn"
              onClick={() => setOptionsMenuOpen(!optionsMenuOpen)}
            >
              + Add option
            </button>

            {optionsMenuOpen && (
              <div className="compare-popover-menu">
                {unusedOptions.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className="compare-popover-item"
                    onClick={() => {
                      handleOptionChange(opt.id, opt.id === 'disableDotNotation' ? false : (opt.id === 'multipleMatches' ? 'first' : ''))
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
    </div>
  )
}
