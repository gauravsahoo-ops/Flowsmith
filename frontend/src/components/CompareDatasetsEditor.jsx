import { useState, useRef, useEffect } from 'react'
import MappingField from './MappingField'
import './CompareDatasetsEditor.css'

const DIFFERENCE_MODES = [
  {
    id: 'includeBoth',
    title: 'Include Both Versions',
    desc: 'Output contains all data from both Input A and Input B',
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
      {/* Top Banner - Flowsmith Design System */}
      <div className="compare-info-banner">
        <span className="compare-info-icon">ℹ</span>
        <span>
          Items from different input branches are paired together when the match fields are equal. The remaining fields are then compared to determine whether records match or differ.
        </span>
      </div>

      {/* Fields to Match Section */}
      <div className="compare-section-card">
        <div className="compare-section-header">
          <div className="compare-section-title-wrap">
            <span className="compare-section-title">Fields to Match</span>
            <span className="compare-section-badge">{fieldsToMatch.length}</span>
          </div>
          <button
            type="button"
            className="compare-icon-btn"
            title="Add Fields to Match"
            onClick={addFieldMatch}
          >
            +
          </button>
        </div>

        <div className="compare-match-list">
          {fieldsToMatch.map((match, idx) => {
            const isCollapsed = Boolean(collapsedCards[match.id])
            return (
              <div key={match.id} className="compare-match-card">
                <div
                  className="compare-match-card-header"
                  onClick={() => toggleCollapse(match.id)}
                >
                  <div className="compare-match-card-title">
                    <span className="compare-collapse-icon">
                      {isCollapsed ? '▸' : '▾'}
                    </span>
                    <span className="compare-match-card-label">Values {idx + 1}</span>
                    {(match.fieldA || match.fieldB) && (
                      <span className="compare-match-card-preview">
                        ({match.fieldA || '—'} = {match.fieldB || '—'})
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    className="compare-remove-btn"
                    title="Remove this field match"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeFieldMatch(match.id)
                    }}
                   style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                </div>

                {!isCollapsed && (
                  <div className="compare-match-card-body">
                    <div className="compare-field-group">
                      <MappingField
                        schema={{
                          title: 'Input A Field',
                          description: 'Field name or expression from Input A',
                        }}
                        value={match.fieldA || ''}
                        onChange={(v) => updateFieldMatch(match.id, { fieldA: v })}
                        path={`fieldA_${match.id}`}
                        mapping={mapping}
                        onPreview={onPreview}
                      />
                    </div>

                    <div className="compare-field-group">
                      <MappingField
                        schema={{
                          title: 'Input B Field',
                          description: 'Field name or expression from Input B',
                        }}
                        value={match.fieldB || ''}
                        onChange={(v) => updateFieldMatch(match.id, { fieldB: v })}
                        path={`fieldB_${match.id}`}
                        mapping={mapping}
                        onPreview={onPreview}
                      />
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        <button
          type="button"
          className="compare-add-btn"
          onClick={addFieldMatch}
        >
          <span>+</span> Add Fields to Match
        </button>
      </div>

      {/* When There Are Differences */}
      <div className="compare-section-card" ref={diffMenuRef}>
        <div className="compare-field-header">
          <label className="compare-field-label">When There Are Differences</label>
        </div>

        <div className="compare-select-wrap">
          <button
            type="button"
            className={`compare-select-btn ${diffMenuOpen ? 'open' : ''}`}
            onClick={() => setDiffMenuOpen(!diffMenuOpen)}
          >
            <div className="compare-select-value">
              <span className="compare-select-title">{selectedDiffOption.title}</span>
              <span className="compare-select-desc">{selectedDiffOption.desc}</span>
            </div>
            <span className="compare-select-arrow">{diffMenuOpen ? '▴' : '▾'}</span>
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
                    <div className="compare-select-item-content">
                      <span className="compare-select-item-title">{mode.title}</span>
                      {mode.desc && (
                        <span className="compare-select-item-desc">{mode.desc}</span>
                      )}
                    </div>
                    {isSelected && <span className="compare-select-check"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg></span>}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Fuzzy Compare Toggle */}
      <div className="compare-section-card">
        <div className="compare-toggle-row">
          <div className="compare-toggle-label-wrap">
            <span className="compare-toggle-label">Fuzzy Compare</span>
            <span
              className="compare-help-icon"
              onMouseEnter={() => setShowFuzzyTooltip(true)}
              onMouseLeave={() => setShowFuzzyTooltip(false)}
            >
              ?
            </span>
            {showFuzzyTooltip && (
              <div className="compare-tooltip-bubble">
                Tolerate minor type differences when comparing fields (e.g. number 3 and string &apos;3&apos; are treated as equal).
              </div>
            )}
          </div>
          <label className="compare-switch">
            <input
              type="checkbox"
              checked={fuzzyCompare}
              onChange={(e) => toggleFuzzyCompare(e.target.checked)}
            />
            <span className="compare-switch-slider" />
          </label>
        </div>
      </div>

      {/* Options Section */}
      <div className="compare-section-card" ref={optionsMenuRef}>
        <div className="compare-section-header">
          <div className="compare-section-title-wrap">
            <span className="compare-section-title">Options</span>
            <span className="compare-section-badge">{Object.keys(options).length}</span>
          </div>
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
          <div className="compare-option-item">
            <div className="compare-option-item-header">
              <span className="compare-option-label">Fields to Skip Comparing</span>
              <button
                type="button"
                className="compare-remove-btn"
                title="Remove option"
                onClick={() => handleOptionChange('fieldsToSkip', undefined)}
               style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
            <MappingField
              schema={{
                title: 'Fields to Skip',
                description: 'Comma-separated list of fields to ignore (e.g. updatedAt, id)',
              }}
              value={options.fieldsToSkip || ''}
              onChange={(v) => handleOptionChange('fieldsToSkip', v)}
              path="options_fieldsToSkip"
              mapping={mapping}
              onPreview={onPreview}
            />
          </div>
        )}

        {options.disableDotNotation !== undefined && (
          <div className="compare-option-item">
            <div className="compare-toggle-row">
              <div className="compare-toggle-label-wrap">
                <span className="compare-toggle-label">Disable Dot Notation</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <label className="compare-switch">
                  <input
                    type="checkbox"
                    checked={Boolean(options.disableDotNotation)}
                    onChange={(e) => handleOptionChange('disableDotNotation', e.target.checked)}
                  />
                  <span className="compare-switch-slider" />
                </label>
                <button
                  type="button"
                  className="compare-remove-btn"
                  title="Remove option"
                  onClick={() => handleOptionChange('disableDotNotation', undefined)}
                 style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
              </div>
            </div>
          </div>
        )}

        {options.multipleMatches !== undefined && (
          <div className="compare-option-item">
            <div className="compare-option-item-header">
              <span className="compare-option-label">Multiple Matches</span>
              <button
                type="button"
                className="compare-remove-btn"
                title="Remove option"
                onClick={() => handleOptionChange('multipleMatches', undefined)}
               style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
            <select
              className="compare-native-select"
              value={options.multipleMatches || 'first'}
              onChange={(e) => handleOptionChange('multipleMatches', e.target.value)}
            >
              <option value="first">Include First Match Only</option>
              <option value="all">Include All Matches</option>
            </select>
          </div>
        )}

        {/* Hint */}
        <div className="hint" style={{ fontSize: 11, background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 10px', marginTop: 10, marginBottom: 10 }}>
          <strong>Tip:</strong> Use <code>{'{{$json.field}}'}</code> for expressions. Items from different branches are paired when match fields are equal.
        </div>

        {/* Add Option button */}
        {unusedOptions.length > 0 && (
          <div className="compare-add-option-wrap">
            <button
              type="button"
              className="compare-add-btn"
              onClick={() => setOptionsMenuOpen(!optionsMenuOpen)}
            >
              <span>+</span> Add Option
            </button>

            {optionsMenuOpen && (
              <div className="compare-popover-menu">
                {unusedOptions.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className="compare-popover-item"
                    onClick={() => {
                      handleOptionChange(
                        opt.id,
                        opt.id === 'disableDotNotation'
                          ? false
                          : opt.id === 'multipleMatches'
                          ? 'first'
                          : ''
                      )
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
