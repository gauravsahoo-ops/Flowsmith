// LogsPanel: docked bottom execution logs panel
// Displays live execution logs, node status, duration, item counts,
// Input/Output data inspection with Schema / Table / JSON segmented views,
// syncs selection with the canvas on click, and can pop out into the full console.

import { useState, useRef, useEffect, useMemo } from 'react'
import { useExecutionStore } from '../stores/executionStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import { NodeIcon } from './NodeIcons'
import { TableView, SchemaView } from './DataViewer'
import JsonTree from './JsonTree'

function fmtTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

function fmtDuration(ms) {
  if (ms == null) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function unrollItems(data) {
  if (data == null) return []
  if (Array.isArray(data)) {
    return data.map((item) => {
      if (item && typeof item === 'object' && 'json' in item) {
        return item.json
      }
      return item
    })
  }
  if (typeof data === 'object') {
    if (Array.isArray(data.main)) {
      return unrollItems(data.main)
    }
    if (Array.isArray(data.records)) {
      return data.records
    }
    if ('json' in data && typeof data.json === 'object') {
      return [data.json]
    }
    return [data]
  }
  return [{ value: data }]
}

export default function LogsPanel({ onOpenConsole, onOpenDebugger }) {
  const handleOpenConsole = onOpenConsole || onOpenDebugger
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem('workflow_logs_open') === 'true'
    } catch {
      return false
    }
  })

  const [panelHeight, setPanelHeight] = useState(() => {
    try {
      const saved = Number(localStorage.getItem('workflow_logs_height'))
      return saved && saved >= 120 && saved <= 700 ? saved : 240
    } catch {
      return 240
    }
  })

  const [isResizing, setIsResizing] = useState(false)

  const [syncWithCanvas, setSyncWithCanvas] = useState(() => {
    try {
      const v = localStorage.getItem('workflow_logs_sync')
      return v === null ? true : v === 'true'
    } catch {
      return true
    }
  })

  // 'logs' | 'input' | 'output'
  const [activeTab, setActiveTab] = useState('logs')

  // 'schema' | 'table' | 'json'
  const [viewMode, setViewMode] = useState(() => {
    try {
      return localStorage.getItem('workflow_logs_view_mode') || 'schema'
    } catch {
      return 'schema'
    }
  })

  const [search, setSearch] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)
  const logListRef = useRef(null)

  const trace = useExecutionStore((s) => s.trace)
  const executionStatus = useExecutionStore((s) => s.status)
  const running = useExecutionStore((s) => s.running)
  const executionError = useExecutionStore((s) => s.error)
  const clearExecution = useExecutionStore((s) => s.clear)

  const nodes = useWorkflowStore((s) => s.nodes)
  const selectNode = useUiStore((s) => s.selectNode)
  const selectedNodeId = useUiStore((s) => s.selectedNodeId)

  // Map node_id -> canvas node object
  const nodeMap = useMemo(() => {
    const m = new Map()
    for (const n of nodes) {
      m.set(n.id, n.data?.node || n)
    }
    return m
  }, [nodes])

  function toggleOpen() {
    setOpen((prev) => {
      const next = !prev
      try {
        localStorage.setItem('workflow_logs_open', String(next))
      } catch {}
      return next
    })
  }

  function handleTabClick(tab) {
    if (!open) {
      // If collapsed, clicking any tab automatically expands the panel and switches to that tab
      setOpen(true)
      try {
        localStorage.setItem('workflow_logs_open', 'true')
      } catch {}
      setActiveTab(tab)
    } else if (activeTab === tab) {
      // If already open on this tab, clicking toggles it closed
      setOpen(false)
      try {
        localStorage.setItem('workflow_logs_open', 'false')
      } catch {}
    } else {
      // If open on a different tab, immediately switch to the target tab
      setActiveTab(tab)
    }
  }

  function toggleSync() {
    setSyncWithCanvas((prev) => {
      const next = !prev
      try {
        localStorage.setItem('workflow_logs_sync', String(next))
      } catch {}
      return next
    })
    setMenuOpen(false)
  }

  function handleSelectViewMode(mode) {
    setViewMode(mode)
    try {
      localStorage.setItem('workflow_logs_view_mode', mode)
    } catch {}
  }

  // Close menu on click outside
  useEffect(() => {
    if (!menuOpen) return
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
      }
    }
    window.addEventListener('pointerdown', handleClick, true)
    return () => window.removeEventListener('pointerdown', handleClick, true)
  }, [menuOpen])

  // Auto-scroll to bottom of logs when running
  useEffect(() => {
    if (open && activeTab === 'logs' && logListRef.current && running) {
      logListRef.current.scrollTop = logListRef.current.scrollHeight
    }
  }, [open, activeTab, trace, running])

  function handleRowClick(step) {
    if (syncWithCanvas && step.node_id) {
      selectNode(step.node_id)
    }
  }

  function handleRowDoubleClick(step) {
    if (step.node_id) {
      selectNode(step.node_id)
      setActiveTab('output')
    }
  }

  function startResize(e) {
    e.preventDefault()
    e.stopPropagation()
    setIsResizing(true)
    const startY = e.clientY
    const startH = panelHeight

    function onPointerMove(ev) {
      const delta = startY - ev.clientY
      const nextH = Math.max(120, Math.min(window.innerHeight * 0.75, startH + delta))
      setPanelHeight(nextH)
    }

    function onPointerUp(ev) {
      setIsResizing(false)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      const delta = startY - ev.clientY
      const finalH = Math.max(120, Math.min(window.innerHeight * 0.75, startH + delta))
      try {
        localStorage.setItem('workflow_logs_height', String(Math.round(finalH)))
      } catch {}
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
  }

  const hasLogs = Array.isArray(trace) && trace.length > 0

  // Active step for Input/Output inspection
  const activeStep = useMemo(() => {
    if (selectedNodeId) {
      const found = trace.find((s) => s.node_id === selectedNodeId)
      if (found) return found
    }
    return trace.length > 0 ? trace[trace.length - 1] : null
  }, [trace, selectedNodeId])

  // Active data for Input or Output
  const stepData = useMemo(() => {
    if (!activeStep) return { raw: null, items: [] }
    const raw = activeTab === 'input' ? activeStep.inputs : activeStep.outputs
    const items = unrollItems(raw)
    return { raw, items }
  }, [activeStep, activeTab])

  // Filter items by search query
  const displayItems = useMemo(() => {
    if (!search.trim()) return stepData.items
    const q = search.trim().toLowerCase()
    return stepData.items.filter((item) => {
      try {
        return JSON.stringify(item).toLowerCase().includes(q)
      } catch {
        return false
      }
    })
  }, [stepData.items, search])

  const activeNode = activeStep ? nodeMap.get(activeStep.node_id) || {} : {}
  const activeNodeName = activeNode.name || activeNode.display_name || activeStep?.node_id || 'Node'

  return (
    <div
      className={`logs-dock ${open ? 'expanded' : 'collapsed'} ${isResizing ? 'resizing' : ''}`}
      style={open ? { height: `${panelHeight}px` } : undefined}
    >
      {/* Top resize handle when expanded */}
      {open && (
        <div
          className="logs-resizer"
          onPointerDown={startResize}
          title="Drag to resize logs panel"
        />
      )}

      {/* Dock Bar / Header */}
      <div className="logs-header" onClick={toggleOpen}>
        <div className="logs-header-left" onClick={(e) => e.stopPropagation()}>
          {/* Main Logs View Button */}
          <button
            type="button"
            className={`logs-tab-btn ${open && activeTab === 'logs' ? 'active' : ''}`}
            onClick={(e) => {
              e.stopPropagation()
              handleTabClick('logs')
            }}
            title="All execution logs"
          >
            <span className="logs-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </span>
            <span className="logs-title">Logs</span>
            {hasLogs && <span className="logs-count-chip">{trace.length}</span>}
          </button>

          {/* Input Tab */}
          <button
            type="button"
            className={`logs-tab-btn input ${open && activeTab === 'input' ? 'active' : ''}`}
            onClick={(e) => {
              e.stopPropagation()
              handleTabClick('input')
            }}
            title="Inspect Input data for the active node"
          >
            Input
          </button>

          {/* Output Tab */}
          <button
            type="button"
            className={`logs-tab-btn output ${open && activeTab === 'output' ? 'active' : ''}`}
            onClick={(e) => {
              e.stopPropagation()
              handleTabClick('output')
            }}
            title="Inspect Output data for the active node"
          >
            Output
          </button>

          {/* Step Selector dropdown when looking at Input or Output */}
          {hasLogs && (activeTab === 'input' || activeTab === 'output') && (
            <div className="logs-step-picker">
              <select
                className="logs-step-select"
                value={activeStep?.node_id || ''}
                onChange={(e) => selectNode(e.target.value)}
                title="Select node to inspect"
              >
                {trace.map((s, idx) => {
                  const n = nodeMap.get(s.node_id) || {}
                  const dName = n.name || n.display_name || s.node_id
                  return (
                    <option key={s.node_id || idx} value={s.node_id}>
                      {dName}
                    </option>
                  )
                })}
              </select>
            </div>
          )}

          {running && (
            <span className="logs-status-pill running">
              <span className="pulse-dot" />
              Executing...
            </span>
          )}

          {!running && executionStatus && activeTab === 'logs' && (
            <span className={`logs-status-pill ${executionStatus}`}>
              {executionStatus === 'success' ? '✓ Finished' : executionStatus === 'failed' || executionStatus === 'error' ? '✕ Failed' : executionStatus}
            </span>
          )}
        </div>

        <div className="logs-header-right" onClick={(e) => e.stopPropagation()}>
          {open && hasLogs && activeTab === 'logs' && (
            <button
              type="button"
              className="ghost small logs-tool-btn"
              onClick={clearExecution}
              title="Clear execution logs"
            >
              Clear
            </button>
          )}

          {open && (
            <div ref={menuRef} style={{ position: 'relative' }}>
              <button
                type="button"
                className="ghost small logs-tool-btn"
                onClick={() => setMenuOpen((v) => !v)}
                title="Options"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="12" cy="12" r="2" />
                  <circle cx="19" cy="12" r="2" />
                  <circle cx="5" cy="12" r="2" />
                </svg>
              </button>

              {menuOpen && (
                <div className="logs-options-menu">
                  <button
                    type="button"
                    className="logs-menu-item"
                    onClick={toggleSync}
                  >
                    <span className="logs-check">{syncWithCanvas ? '✓' : ''}</span>
                    <span>Sync selection with canvas</span>
                  </button>
                  <button
                    type="button"
                    className="logs-menu-item"
                    onClick={() => {
                      setMenuOpen(false)
                      handleOpenConsole?.()
                    }}
                  >
                    <span className="logs-check" />
                    <span>Open in Console</span>
                  </button>
                </div>
              )}
            </div>
          )}

          {!open && (
            <span className="logs-mini-right-icon" title="Logs panel">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </span>
          )}

          <button
            type="button"
            className="ghost small logs-toggle-btn"
            onClick={toggleOpen}
            title={open ? 'Collapse logs' : 'Expand logs'}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ transform: open ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.15s ease' }}
            >
              <polyline points="18 15 12 9 6 15" />
            </svg>
          </button>
        </div>
      </div>

      {/* Sub-toolbar row for Input / Output mode (matches screenshot) */}
      {open && (activeTab === 'input' || activeTab === 'output') && (
        <div className="logs-sub-toolbar">
          <div className="logs-sub-left">
            {/* Search Icon / Toggle */}
            <div className="logs-search-wrap">
              <button
                type="button"
                className={`logs-search-toggle ${searchOpen || search ? 'active' : ''}`}
                onClick={() => setSearchOpen((v) => !v)}
                title="Search properties & values"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
              </button>
              {(searchOpen || search) && (
                <input
                  type="text"
                  className="logs-search-input"
                  placeholder="Filter keys or values…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  autoFocus
                />
              )}
            </div>

            {/* Segmented control: [ Schema | Table | JSON ] (exact match to screenshot) */}
            <div className="logs-segmented-group" role="group" aria-label="View mode">
              <button
                type="button"
                className={`logs-segmented-btn ${viewMode === 'schema' ? 'active' : ''}`}
                onClick={() => handleSelectViewMode('schema')}
                title="Schema / Tree view"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="4" width="7" height="4" rx="1.5" />
                  <rect x="9" y="10" width="7" height="4" rx="1.5" />
                  <rect x="9" y="16" width="7" height="4" rx="1.5" />
                  <path d="M3 6v12h6" />
                  <line x1="3" y1="12" x2="9" y2="12" />
                </svg>
              </button>
              <button
                type="button"
                className={`logs-segmented-btn ${viewMode === 'table' ? 'active' : ''}`}
                onClick={() => handleSelectViewMode('table')}
                title="Table view"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <line x1="3" y1="9" x2="21" y2="9" />
                  <line x1="3" y1="15" x2="21" y2="15" />
                  <line x1="9" y1="3" x2="9" y2="21" />
                  <line x1="15" y1="3" x2="15" y2="21" />
                </svg>
              </button>
              <button
                type="button"
                className={`logs-segmented-btn ${viewMode === 'json' ? 'active' : ''}`}
                onClick={() => handleSelectViewMode('json')}
                title="JSON view"
              >
                <span className="logs-json-glyph">{'{ }'}</span>
              </button>
            </div>

            {/* Item count text (exact match to screenshot) */}
            <span className="logs-item-count">
              {stepData.items.length} {stepData.items.length === 1 ? 'item' : 'items'}
            </span>
          </div>

          <div className="logs-sub-right">
            {activeStep && (
              <span className="logs-sub-node-badge">
                <NodeIcon type={activeNode.type} icon={activeNode.icon} size={14} />
                <span>{activeNodeName}</span>
              </span>
            )}
          </div>
        </div>
      )}

      {/* Expanded Logs Body */}
      {open && (
        <div className="logs-body">
          {activeTab === 'logs' ? (
            /* Execution logs list */
            !hasLogs && !running ? (
              <div className="logs-empty-state">
                <span>Nothing to display yet. Execute the workflow to see execution logs.</span>
              </div>
            ) : (
              <div ref={logListRef} className="logs-stream">
                {trace.map((step, idx) => {
                  const node = nodeMap.get(step.node_id) || {}
                  const displayName = node.name || node.display_name || step.node_id
                  const isSelected = selectedNodeId === step.node_id
                  const status = step.status || 'running'

                  return (
                    <div
                      key={step.id || `${step.node_id}_${idx}`}
                      className={`logs-row ${status} ${isSelected ? 'selected' : ''}`}
                      onClick={() => handleRowClick(step)}
                      onDoubleClick={() => handleRowDoubleClick(step)}
                      title="Click to select on canvas, double-click to view output"
                    >
                      <span className="logs-col-time">{fmtTime(step.started_at)}</span>

                      <span className={`logs-col-status status-${status}`}>
                        {status === 'success' && '✓ Success'}
                        {status === 'running' && '● Running'}
                        {(status === 'failed' || status === 'error') && '✕ Error'}
                        {status === 'skipped' && '— Skipped'}
                        {status === 'waiting_approval' && '⏸ Waiting'}
                      </span>

                      <span className="logs-col-node">
                        <NodeIcon type={node.type} icon={node.icon} size={15} />
                        <span className="logs-node-name">{displayName}</span>
                      </span>

                      <span className="logs-col-duration">{fmtDuration(step.duration_ms)}</span>

                      <span className="logs-col-items">
                        {Array.isArray(step.outputs) ? `${step.outputs.length} items` : (step.output_count != null ? `${step.output_count} items` : '')}
                      </span>

                      <span className="logs-col-msg">
                        {step.error ? (
                          <span className="logs-error-text">
                            {typeof step.error === 'string' ? step.error : (step.error.message || JSON.stringify(step.error))}
                          </span>
                        ) : (
                          status === 'success' ? 'Finished successfully' : ''
                        )}
                      </span>
                    </div>
                  )
                })}

                {executionError && (
                  <div className="logs-row error execution-fatal">
                    <span className="logs-col-time" />
                    <span className="logs-col-status status-error">✕ Run Error</span>
                    <span className="logs-col-node" />
                    <span className="logs-col-duration" />
                    <span className="logs-col-items" />
                    <span className="logs-col-msg logs-error-text">
                      {typeof executionError === 'string' ? executionError : (executionError.message || JSON.stringify(executionError))}
                    </span>
                  </div>
                )}
              </div>
            )
          ) : (
            /* Input or Output Data Inspector */
            <div className="logs-data-body">
              {stepData.items.length === 0 && !running ? (
                <div className="logs-empty-state">
                  <span>No {activeTab} data for this step yet. Execute the workflow to inspect data.</span>
                </div>
              ) : (
                <>
                  {viewMode === 'table' && <TableView data={displayItems} />}
                  {viewMode === 'schema' && <SchemaView data={displayItems} />}
                  {viewMode === 'json' && (
                    <div className="logs-json-wrap">
                      <JsonTree
                        value={search ? displayItems : (stepData.raw || stepData.items)}
                        search={search}
                      />
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
