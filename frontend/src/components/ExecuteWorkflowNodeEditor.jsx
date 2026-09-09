import { useState, useRef, useEffect } from 'react'
import { api } from '../api'
import MappingField from './MappingField'
import './ExecuteWorkflowNodeEditor.css'

const SOURCES = [
  {
    id: 'database',
    title: 'Database',
    desc: 'Load the workflow from the database by ID',
  },
  {
    id: 'defineBelow',
    title: 'Define Below',
    desc: 'Pass the JSON code of a workflow',
  },
]

const WORKFLOW_SELECTORS = [
  { id: 'list', label: 'From list' },
  { id: 'id', label: 'By ID' },
]

const MODES = [
  {
    id: 'onceWithAll',
    title: 'Run once with all items',
    desc: 'Pass all items into a single execution of the sub-workflow',
  },
  {
    id: 'onceForEach',
    title: 'Run once for each item',
    desc: 'Call the sub-workflow individually for each item',
  },
]

const AVAILABLE_OPTIONS = [
  { id: 'waitForSubWorkflowCompletion', label: 'Wait For Sub-Workflow Completion' },
]

export default function ExecuteWorkflowNodeEditor({
  node,
  onParamsChange,
  mapping = [],
  onPreview,
}) {
  const params = node.parameters || {}
  const source = params.source || 'database'
  const workflowSelector = params.workflow_selector || 'list'
  const workflowId = params.workflow_id || ''
  const workflowJson = typeof params.workflow_json === 'object'
    ? JSON.stringify(params.workflow_json, null, 2)
    : (params.workflow_json || '')
  const mode = params.mode || 'onceWithAll'
  const options = params.options || {}

  // Local state
  const [workflows, setWorkflows] = useState([])
  const [loadingWfs, setLoadingWfs] = useState(false)
  const [sourceMenuOpen, setSourceMenuOpen] = useState(false)
  const [selectorMenuOpen, setSelectorMenuOpen] = useState(false)
  const [wfPickerOpen, setWfPickerOpen] = useState(false)
  const [wfSearch, setWfSearch] = useState('')
  const [modeMenuOpen, setModeMenuOpen] = useState(false)
  const [optionsMenuOpen, setOptionsMenuOpen] = useState(false)

  const sourceRef = useRef(null)
  const selectorRef = useRef(null)
  const wfPickerRef = useRef(null)
  const modeRef = useRef(null)
  const optionsRef = useRef(null)

  // Fetch workflows from workspace
  useEffect(() => {
    let alive = true
    setLoadingWfs(true)
    api.listWorkflows()
      .then((data) => {
        if (!alive) return
        setWorkflows(Array.isArray(data) ? data : [])
      })
      .catch(() => {})
      .finally(() => {
        if (alive) setLoadingWfs(false)
      })
    return () => { alive = false }
  }, [])

  // Click outside listeners
  useEffect(() => {
    function handleClickOutside(e) {
      if (sourceRef.current && !sourceRef.current.contains(e.target)) setSourceMenuOpen(false)
      if (selectorRef.current && !selectorRef.current.contains(e.target)) setSelectorMenuOpen(false)
      if (wfPickerRef.current && !wfPickerRef.current.contains(e.target)) setWfPickerOpen(false)
      if (modeRef.current && !modeRef.current.contains(e.target)) setModeMenuOpen(false)
      if (optionsRef.current && !optionsRef.current.contains(e.target)) setOptionsMenuOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function updateField(key, val) {
    onParamsChange({ ...params, [key]: val })
  }

  function handleOptionChange(key, val) {
    const nextOptions = { ...options, [key]: val }
    if (val === undefined) delete nextOptions[key]
    onParamsChange({ ...params, options: nextOptions })
  }

  const selectedSource = SOURCES.find((s) => s.id === source) || SOURCES[0]
  const selectedSelector = WORKFLOW_SELECTORS.find((s) => s.id === workflowSelector) || WORKFLOW_SELECTORS[0]
  const selectedMode = MODES.find((m) => m.id === mode) || MODES[0]
  const selectedWf = workflows.find((w) => w.id === workflowId)

  const filteredWorkflows = workflows.filter((w) =>
    (w.name || w.id).toLowerCase().includes(wfSearch.toLowerCase())
  )

  const unusedOptions = AVAILABLE_OPTIONS.filter((opt) => options[opt.id] === undefined)

  return (
    <div className="subwf-editor">
      {/* 1. Source */}
      <div className="subwf-field-group" ref={sourceRef}>
        <div className="subwf-field-header">
          <label className="subwf-field-label">Source</label>
          <span className="subwf-help-icon" title="Where to load the sub-workflow from.">?</span>
        </div>

        <div className="subwf-select-wrap">
          <button
            type="button"
            className={`subwf-select-btn ${sourceMenuOpen ? 'open' : ''}`}
            onClick={() => setSourceMenuOpen(!sourceMenuOpen)}
          >
            <div className="subwf-select-value">
              <span className="subwf-select-title">{selectedSource.title}</span>
              <span className="subwf-select-desc">{selectedSource.desc}</span>
            </div>
            <span className="subwf-select-arrow">{sourceMenuOpen ? '▴' : '▾'}</span>
          </button>

          {sourceMenuOpen && (
            <div className="subwf-select-dropdown">
              {SOURCES.map((s) => {
                const isSelected = s.id === source
                return (
                  <button
                    key={s.id}
                    type="button"
                    className={`subwf-select-item ${isSelected ? 'active' : ''}`}
                    onClick={() => {
                      updateField('source', s.id)
                      setSourceMenuOpen(false)
                    }}
                  >
                    <div className="subwf-select-item-content">
                      <span className="subwf-select-item-title">{s.title}</span>
                      <span className="subwf-select-item-desc">{s.desc}</span>
                    </div>
                    {isSelected && <span className="subwf-select-check">✓</span>}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* 2. Workflow (When source === 'database') */}
      {source === 'database' && (
        <div className="subwf-field-group">
          <div className="subwf-field-header">
            <label className="subwf-field-label">Workflow</label>
            <span className="subwf-help-icon" title="The sub-workflow to execute.">?</span>
          </div>

          <div className="subwf-workflow-input-row">
            {/* Mode Switcher: From list / By ID */}
            <div className="subwf-selector-mode-wrap" ref={selectorRef}>
              <button
                type="button"
                className="subwf-selector-mode-btn"
                onClick={() => setSelectorMenuOpen(!selectorMenuOpen)}
              >
                <span>{selectedSelector.label}</span>
                <span className="subwf-mini-arrow">{selectorMenuOpen ? '▴' : '▾'}</span>
              </button>

              {selectorMenuOpen && (
                <div className="subwf-mini-dropdown">
                  {WORKFLOW_SELECTORS.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className={`subwf-mini-item ${s.id === workflowSelector ? 'active' : ''}`}
                      onClick={() => {
                        updateField('workflow_selector', s.id)
                        setSelectorMenuOpen(false)
                      }}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Value Selector: Dropdown List OR By ID input */}
            {workflowSelector === 'list' ? (
              <div className="subwf-picker-wrap" ref={wfPickerRef}>
                <button
                  type="button"
                  className={`subwf-picker-btn ${wfPickerOpen ? 'open' : ''} ${!workflowId ? 'is-empty' : ''}`}
                  onClick={() => setWfPickerOpen(!wfPickerOpen)}
                >
                  <span className="subwf-picker-text">
                    {selectedWf ? selectedWf.name : 'Choose...'}
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {!workflowId && <span className="subwf-warning-icon" title="Required">⚠️</span>}
                    <span className="subwf-select-arrow">{wfPickerOpen ? '▴' : '▾'}</span>
                  </div>
                </button>

                {wfPickerOpen && (
                  <div className="subwf-picker-dropdown">
                    <div className="subwf-picker-search-wrap">
                      <input
                        type="text"
                        autoFocus
                        placeholder="Search workflows..."
                        value={wfSearch}
                        onChange={(e) => setWfSearch(e.target.value)}
                        className="subwf-picker-search-input"
                      />
                    </div>
                    <div className="subwf-picker-list">
                      {loadingWfs ? (
                        <div className="subwf-picker-empty">Loading workflows...</div>
                      ) : filteredWorkflows.length === 0 ? (
                        <div className="subwf-picker-empty">No workflows found</div>
                      ) : (
                        filteredWorkflows.map((w) => {
                          const isSelected = w.id === workflowId
                          return (
                            <button
                              key={w.id}
                              type="button"
                              className={`subwf-picker-item ${isSelected ? 'active' : ''}`}
                              onClick={() => {
                                updateField('workflow_id', w.id)
                                setWfPickerOpen(false)
                              }}
                            >
                              <span className="subwf-picker-item-name">{w.name}</span>
                              <span className="subwf-picker-item-id">{w.id.slice(0, 8)}</span>
                            </button>
                          )
                        })
                      )}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ flex: 1 }}>
                <MappingField
                  schema={{
                    title: '',
                    description: 'Enter the target workflow ID or expression',
                  }}
                  value={workflowId}
                  onChange={(v) => updateField('workflow_id', v)}
                  placeholder="e.g. wf_123 or {{$json.workflowId}}"
                  path="workflow_id"
                  mapping={mapping}
                  onPreview={onPreview}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* 2b. Define Below Code Editor (When source === 'defineBelow') */}
      {source === 'defineBelow' && (
        <div className="subwf-field-group">
          <label className="subwf-field-label">Workflow JSON</label>
          <textarea
            className="subwf-json-textarea"
            rows={8}
            placeholder='{ "nodes": [...], "connections": [...] }'
            value={workflowJson}
            onChange={(e) => updateField('workflow_json', e.target.value)}
          />
          <span className="subwf-field-hint">
            Provide the complete workflow definition JSON object.
          </span>
        </div>
      )}

      {/* 3. Mode */}
      <div className="subwf-field-group" ref={modeRef}>
        <div className="subwf-field-header">
          <label className="subwf-field-label">Mode</label>
          <span className="subwf-help-icon" title="How input items are passed to the sub-workflow.">?</span>
        </div>

        <div className="subwf-select-wrap">
          <button
            type="button"
            className={`subwf-select-btn ${modeMenuOpen ? 'open' : ''}`}
            onClick={() => setModeMenuOpen(!modeMenuOpen)}
          >
            <div className="subwf-select-value">
              <span className="subwf-select-title">{selectedMode.title}</span>
              <span className="subwf-select-desc">{selectedMode.desc}</span>
            </div>
            <span className="subwf-select-arrow">{modeMenuOpen ? '▴' : '▾'}</span>
          </button>

          {modeMenuOpen && (
            <div className="subwf-select-dropdown">
              {MODES.map((m) => {
                const isSelected = m.id === mode
                return (
                  <button
                    key={m.id}
                    type="button"
                    className={`subwf-select-item ${isSelected ? 'active' : ''}`}
                    onClick={() => {
                      updateField('mode', m.id)
                      setModeMenuOpen(false)
                    }}
                  >
                    <div className="subwf-select-item-content">
                      <span className="subwf-select-item-title">{m.title}</span>
                      <span className="subwf-select-item-desc">{m.desc}</span>
                    </div>
                    {isSelected && <span className="subwf-select-check">✓</span>}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* 4. Options */}
      <div className="subwf-options-section" ref={optionsRef}>
        <div className="subwf-section-header">
          <span className="subwf-options-title">Options</span>
          {unusedOptions.length > 0 && (
            <button
              type="button"
              className="subwf-icon-btn"
              title="Add Option"
              onClick={() => setOptionsMenuOpen(!optionsMenuOpen)}
            >
              +
            </button>
          )}
        </div>

        {/* Wait For Sub-Workflow Completion Option */}
        {options.waitForSubWorkflowCompletion !== undefined && (
          <div className="subwf-option-card">
            <div className="subwf-toggle-row">
              <div className="subwf-toggle-label-wrap">
                <span className="subwf-toggle-label">Wait For Sub-Workflow Completion</span>
                <span
                  className="subwf-help-icon"
                  title="Whether the node should wait for the sub-workflow to finish before continuing."
                >
                  ?
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <label className="subwf-switch">
                  <input
                    type="checkbox"
                    checked={Boolean(options.waitForSubWorkflowCompletion)}
                    onChange={(e) => handleOptionChange('waitForSubWorkflowCompletion', e.target.checked)}
                  />
                  <span className="subwf-switch-slider" />
                </label>
                <button
                  type="button"
                  className="subwf-remove-btn"
                  title="Remove option"
                  onClick={() => handleOptionChange('waitForSubWorkflowCompletion', undefined)}
                >
                  ✕
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Add option button */}
        {unusedOptions.length > 0 && (
          <div className="subwf-add-option-wrap">
            <button
              type="button"
              className="subwf-add-btn"
              onClick={() => setOptionsMenuOpen(!optionsMenuOpen)}
            >
              <span>+</span> Add option
            </button>

            {optionsMenuOpen && (
              <div className="subwf-popover-menu">
                {unusedOptions.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className="subwf-popover-item"
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
      <div className="subwf-tip-banner">
        <strong>Tip:</strong> In the sub-workflow, add the <strong>When executed by Another Workflow</strong> trigger to receive incoming items.
      </div>
    </div>
  )
}
