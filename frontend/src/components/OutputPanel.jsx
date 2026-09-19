import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import JsonTree from './JsonTree'
import Status from './shared/Status'
import ErrorState from './shared/ErrorState'
import { TableView } from './DataViewer'
import BinaryDataViewModal from './BinaryDataViewModal'
import { useWorkflowStore } from '../stores/workflowStore'
import './OutputPanel.css'

function unwrapItem(item) {
  if (item == null) return item
  if (typeof item !== 'object') return { value: item }
  // n8n standard: unwrap { json: { ... } }
  if (item.json && typeof item.json === 'object' && !Array.isArray(item.json)) {
    return item.json
  }
  return item
}

function extractOutputData(data) {
  if (data == null) {
    return { hasData: false, branches: {}, defaultBranch: 'main' }
  }

  let branches = {}

  if (Array.isArray(data)) {
    // Check if 2D array: [ [ item1, item2 ] ]
    if (data.length > 0 && Array.isArray(data[0])) {
      branches.main = data[0].map(unwrapItem)
    } else {
      branches.main = data.map(unwrapItem)
    }
  } else if (typeof data === 'object') {
    const keys = Object.keys(data)
    const hasHandles = keys.some((k) =>
      ['main', 'true', 'false', '0', '1', 'default', 'success', 'error'].includes(k)
    )

    if (hasHandles) {
      for (const k of keys) {
        const val = data[k]
        if (Array.isArray(val)) {
          if (val.length > 0 && Array.isArray(val[0])) {
            branches[k] = val[0].map(unwrapItem)
          } else {
            branches[k] = val.map(unwrapItem)
          }
        } else if (val && typeof val === 'object') {
          if (Array.isArray(val.records)) {
            branches[k] = val.records.map(unwrapItem)
          } else {
            branches[k] = [unwrapItem(val)]
          }
        } else if (val != null) {
          branches[k] = [{ value: val }]
        } else {
          branches[k] = []
        }
      }
    } else if (Array.isArray(data.records)) {
      branches.main = data.records.map(unwrapItem)
    } else if (data.output && Array.isArray(data.output.records)) {
      branches.main = data.output.records.map(unwrapItem)
    } else if (data.output && Array.isArray(data.output)) {
      branches.main = data.output.map(unwrapItem)
    } else if (data.output && typeof data.output === 'object') {
      branches.main = [unwrapItem(data.output)]
    } else {
      // Single object output payload (e.g. response object, webhook payload, HTTP result)
      branches.main = [unwrapItem(data)]
    }
  } else {
    branches.main = [{ value: data }]
  }

  // Determine default branch:
  let defaultBranch = 'main'
  if (branches.main !== undefined && branches.main.length > 0) {
    defaultBranch = 'main'
  } else if (branches.true?.length > 0) {
    defaultBranch = 'true'
  } else if (branches.false?.length > 0) {
    defaultBranch = 'false'
  } else {
    const keys = Object.keys(branches)
    defaultBranch = keys.find((k) => branches[k]?.length > 0) || keys[0] || 'main'
  }

  const totalItems = Object.values(branches).reduce((acc, b) => acc + (b?.length || 0), 0)
  const hasData = totalItems > 0 || (branches[defaultBranch] && branches[defaultBranch].length > 0)

  return {
    hasData,
    branches,
    defaultBranch,
  }
}

export default function OutputPanel({
  data,
  status,
  executing,
  error,
  nodeId,
  nodeLabel,
  onExecuteStep,
}) {
  const [view, setView] = useState(() => sessionStorage.getItem(`op_view_${nodeId}`) || 'schema')
  const [showSearch, setShowSearch] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedBranch, setSelectedBranch] = useState(null)
  const [currentItemIdx, setCurrentItemIdx] = useState(0)
  const [copiedSnippet, setCopiedSnippet] = useState(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editedText, setEditedText] = useState('')
  const storePinned = useWorkflowStore((s) => s.nodes.find((n) => n.id === nodeId)?.pinned_data)
  const updateNode = useWorkflowStore((s) => s.updateNode)
  const [localPinned, setLocalPinned] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(`op_pinned_${nodeId}`) || 'null')
    } catch {
      return null
    }
  })
  const pinned = storePinned !== undefined ? storePinned : localPinned
  const [selectedBinaryModal, setSelectedBinaryModal] = useState(null)

  const binaryEntries = useMemo(() => {
    const rawList = Array.isArray(data)
      ? (Array.isArray(data[0]) ? data[0] : data)
      : (data?.records || (data ? [data] : []))

    const entries = []
    rawList.forEach((item, itemIdx) => {
      if (item && item.binary && typeof item.binary === 'object') {
        Object.entries(item.binary).forEach(([propName, binData]) => {
          if (binData && typeof binData === 'object') {
            entries.push({
              itemIndex: itemIdx,
              propertyName: propName,
              ...binData,
            })
          }
        })
      }
    })
    return entries
  }, [data])

  const prevNodeId = useRef(nodeId)

  useEffect(() => {
    if (nodeId !== prevNodeId.current) {
      const saved = sessionStorage.getItem(`op_view_${nodeId}`)
      if (saved) setView(saved)
      else setView('schema')
      prevNodeId.current = nodeId
      setSearch('')
      setShowSearch(false)
      setSelectedBranch(null)
      setCurrentItemIdx(0)
    }
  }, [nodeId])

  useEffect(() => {
    sessionStorage.setItem(`op_view_${nodeId}`, view)
  }, [view, nodeId])

  // Extract structured branch items from raw data (or pinned data)
  const effectiveRaw = pinned || data
  const extracted = useMemo(() => extractOutputData(effectiveRaw), [effectiveRaw])

  const branchKeys = Object.keys(extracted.branches)
  const activeBranch = selectedBranch && extracted.branches[selectedBranch] !== undefined
    ? selectedBranch
    : extracted.defaultBranch

  const branchItems = useMemo(
    () => extracted.branches[activeBranch] || [],
    [extracted.branches, activeBranch]
  )

  // Ensure pager index is within bounds
  const safeItemIdx = Math.min(currentItemIdx, Math.max(0, branchItems.length - 1))
  const currentItem = branchItems[safeItemIdx] || branchItems[0] || {}

  // Filter items if search is active
  const filteredItems = useMemo(() => {
    if (!search.trim()) return branchItems
    const q = search.toLowerCase()
    return branchItems.filter((item) => {
      try {
        return JSON.stringify(item).toLowerCase().includes(q)
      } catch {
        return false
      }
    })
  }, [branchItems, search])

  // Virtualization guard: cap rendered items to avoid frame drops on large outputs
  const DISPLAY_LIMIT = 200
  const [showAllItems, setShowAllItems] = useState(false)
  const displayedItems = useMemo(
    () => showAllItems ? filteredItems : filteredItems.slice(0, DISPLAY_LIMIT),
    [filteredItems, showAllItems]
  )
  const hasMoreItems = filteredItems.length > DISPLAY_LIMIT && !showAllItems

  const totalItemsCount = branchItems.length
  const isEmpty = !extracted.hasData && !executing && !error && !pinned
  const isError = !!error || status === 'error'
  const isSuccess = status === 'success' && !executing && !isError
  const execStatus = executing ? 'running' : isError ? 'failed' : isSuccess ? 'success' : 'idle'



  const handleCopyExpression = useCallback((expr) => {
    navigator.clipboard?.writeText(expr)
    setCopiedSnippet(expr)
    setTimeout(() => setCopiedSnippet(null), 2200)
  }, [])

  const handleCopyJson = useCallback(() => {
    const toCopy = search ? filteredItems : (branchItems.length === 1 ? branchItems[0] : branchItems)
    const text = JSON.stringify(toCopy, null, 2)
    navigator.clipboard.writeText(text)
    setCopiedSnippet('JSON copied')
    setTimeout(() => setCopiedSnippet(null), 2200)
  }, [search, filteredItems, branchItems])

  const handlePin = useCallback(() => {
    if (pinned) {
      localStorage.removeItem(`op_pinned_${nodeId}`)
      updateNode(nodeId, { pinned_data: null })
      setLocalPinned(null)
    } else {
      const toPin = branchItems.length === 1 ? branchItems[0] : branchItems
      localStorage.setItem(`op_pinned_${nodeId}`, JSON.stringify(toPin))
      updateNode(nodeId, { pinned_data: toPin })
      setLocalPinned(toPin)
    }
  }, [pinned, branchItems, nodeId, updateNode])

  const handleEditSave = () => {
    try {
      const parsed = JSON.parse(editedText)
      localStorage.setItem(`op_pinned_${nodeId}`, JSON.stringify(parsed))
      updateNode(nodeId, { pinned_data: parsed })
      setLocalPinned(parsed)
      setIsEditing(false)
    } catch (e) {
      alert('Invalid JSON: ' + e.message)
    }
  }

  return (
    <div className="op-container">
      {/* Top Header matching n8n Header */}
      <div className="nem-input-header">
        <div className="nem-input-title-group">
          <span className="nem-input-title">OUTPUT</span>
          <Status status={execStatus} live />
          {totalItemsCount > 0 && (
            <span className="op-count">
              {totalItemsCount} {totalItemsCount === 1 ? 'item' : 'items'}
            </span>
          )}
          {pinned && <span className="nem-upstream-badge badge-skipped">PINNED</span>}
          {copiedSnippet && (
            <span className="nem-input-copied-toast" title={copiedSnippet}>
              ✓ {copiedSnippet}
            </span>
          )}
        </div>

        <div className="nem-input-controls">
          {/* Search Toggle */}
          <button
            type="button"
            className={`nem-input-icon-btn ${showSearch ? 'active' : ''}`}
            onClick={() => setShowSearch((v) => !v)}
            title="Filter keys or values"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </button>

          {/* View Mode Tabs (Schema / Table / JSON) */}
          <div className="nem-input-tabs" role="tablist">
            <button
              type="button"
              className={`nem-input-tab ${view === 'schema' ? 'active' : ''}`}
              onClick={() => setView('schema')}
            >
              Schema
            </button>
            <button
              type="button"
              className={`nem-input-tab ${view === 'table' ? 'active' : ''}`}
              onClick={() => setView('table')}
            >
              Table
            </button>
            <button
              type="button"
              className={`nem-input-tab ${view === 'json' ? 'active' : ''}`}
              onClick={() => setView('json')}
            >
              JSON
            </button>
            {binaryEntries.length > 0 && (
              <button
                type="button"
                className={`nem-input-tab ${view === 'binary' ? 'active' : ''}`}
                onClick={() => setView('binary')}
              >
                Binary ({binaryEntries.length})
              </button>
            )}
          </div>

          {/* Quick Actions (Copy, Edit, Pin) */}
          <button
            type="button"
            className="nem-input-icon-btn"
            onClick={handleCopyJson}
            title="Copy output JSON"
            disabled={isEmpty}
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
          </button>

          <button
            type="button"
            className={`nem-input-icon-btn ${isEditing ? 'active' : ''}`}
            onClick={() => {
              setIsEditing((v) => !v)
              if (!isEditing) {
                setEditedText(JSON.stringify(branchItems.length === 1 ? branchItems[0] : branchItems, null, 2))
              }
            }}
            title="Edit output data"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
          </button>

          <button
            type="button"
            className={`nem-input-icon-btn ${pinned ? 'active' : ''}`}
            onClick={handlePin}
            title={pinned ? 'Unpin output data' : 'Pin output data'}
            disabled={isEmpty}
          >
            📌
          </button>
        </div>
      </div>

      {/* Filter Search Bar */}
      {showSearch && (
        <div className="nem-input-search-bar">
          <input
            type="text"
            className="nem-input-search-input"
            placeholder="Filter keys or values…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
          {search && (
            <button
              type="button"
              className="nem-input-search-clear"
              onClick={() => setSearch('')}
            >
              ✕
            </button>
          )}
        </div>
      )}

      {/* JSON Edit Drawer / Overlay */}
      {isEditing && (
        <div className="op-edit">
          <div className="op-edit-head">
            <span className="op-edit-label">Mock / Override Output Data</span>
            <span className="op-edit-hint">Changes will be pinned as local output</span>
          </div>
          <textarea
            className="op-edit-textarea"
            value={editedText}
            onChange={(e) => setEditedText(e.target.value)}
            rows={8}
            spellCheck={false}
          />
          <div className="op-edit-actions">
            <button className="primary op-btn small" onClick={handleEditSave}>
              Save & Pin
            </button>
            <button className="ghost op-btn small" onClick={() => setIsEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Pinned Notification Banner */}
      {pinned && !isEditing && (
        <div className="op-pinned-banner">
          <span>📌 Pinned mock/override data active</span>
          <button className="ghost op-btn small" onClick={handlePin}>
            Unpin
          </button>
        </div>
      )}

      {/* Sub-toolbar: Multi-branch Switcher & Multi-item Pager */}
      {(branchKeys.length > 1 || totalItemsCount > 1) && !isEmpty && !executing && (
        <div className="op-sub-toolbar">
          {/* Branch Selector Bar (for IF, Switch, Router nodes) */}
          {branchKeys.length > 1 && (
            <div className="nem-branch-bar" style={{ marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>
              <span className="nem-branch-title">Output:</span>
              {branchKeys.map((bKey) => {
                const count = extracted.branches[bKey]?.length || 0
                const isActive = activeBranch === bKey
                return (
                  <button
                    key={bKey}
                    type="button"
                    className={`nem-branch-pill ${isActive ? 'active' : ''}`}
                    onClick={() => {
                      setSelectedBranch(bKey)
                      setCurrentItemIdx(0)
                    }}
                  >
                    {bKey === 'true' ? '✓ true' : bKey === 'false' ? '✗ false' : bKey} ({count})
                  </button>
                )
              })}
            </div>
          )}

          {/* Multi-item Pager Bar (e.g. for Split, Search or Multi-record nodes) */}
          {totalItemsCount > 1 && (
            <div className="nem-item-pager" style={{ marginBottom: 0, paddingBottom: 0 }}>
              <button
                type="button"
                className="nem-pager-btn"
                disabled={safeItemIdx <= 0}
                onClick={() => setCurrentItemIdx((prev) => Math.max(0, prev - 1))}
                title="Previous item"
              >
                ◀
              </button>
              <span className="nem-pager-label">
                Item {safeItemIdx + 1} of {totalItemsCount}
              </span>
              <button
                type="button"
                className="nem-pager-btn"
                disabled={safeItemIdx >= totalItemsCount - 1}
                onClick={() => setCurrentItemIdx((prev) => Math.min(totalItemsCount - 1, prev + 1))}
                title="Next item"
              >
                ▶
              </button>
            </div>
          )}
        </div>
      )}

      {/* Main Body */}
      <div className="op-body">
        {executing && (
          <div className="nem-empty-state">
            <div className="nem-empty-icon-wrap output-glow">
              <span className="op-spinner" style={{ width: 22, height: 22 }} />
            </div>
            <h4>Executing Step…</h4>
            <p className="hint">Dispatching node task to worker queue.</p>
          </div>
        )}

        {!executing && isError && (
          <ErrorState
            title="Execution Failed"
            description={
              typeof error === 'object' && error !== null
                ? (error.message || (error.code ? `${error.code}: ${JSON.stringify(error.details || error)}` : JSON.stringify(error)))
                : (error || 'Unknown error')
            }
            details={typeof error === 'object' && error !== null ? (error.details || error) : undefined}
          />
        )}

        {!executing && !isError && isEmpty && (
          <div className="nem-empty-state">
            <div className="nem-empty-icon-wrap output-glow">
              <svg
                width="28"
                height="28"
                viewBox="0 0 24 24"
                fill="none"
                stroke="#38bdf8"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
            </div>
            <h4>{status === 'success' ? '0 Output Items — Workflow Stopped Here' : 'No Output Data Yet'}</h4>
            <p className="hint">
              {status === 'success'
                ? 'This node executed successfully but produced 0 items. The workflow stopped at this point and skipped connected downstream nodes because there was no data to continue.'
                : 'Execute this step or the entire workflow to inspect live return values.'}
            </p>
            {onExecuteStep && (
              <button
                className="primary small nem-empty-btn"
                onClick={onExecuteStep}
                disabled={executing}
              >
                ▶ Execute Step
              </button>
            )}
          </div>
        )}

        {!executing && !isEmpty && !isError && filteredItems.length === 0 && search && (
          <div className="nem-empty-state">
            <h4>No matching records</h4>
            <p className="hint">No fields matched query &ldquo;{search}&rdquo;</p>
            <button className="ghost small nem-empty-btn" onClick={() => setSearch('')}>
              Clear filter
            </button>
          </div>
        )}

        {!executing && !isEmpty && !isError && filteredItems.length > 0 && (
          <>
            {view === 'schema' && (
              <div className="op-schema-wrap" style={{ border: 'none', background: 'transparent' }}>
                <OutputSchemaTree
                  item={currentItem}
                  nodeLabel={nodeLabel}
                  onCopy={handleCopyExpression}
                  filter={search}
                />
              </div>
            )}
            {view === 'table' && <TableView data={displayedItems} />}
            {view === 'json' && (
              <div className="op-json-wrap">
                <div className="op-json-scroll">
                  <JsonTree
                    value={
                      search
                        ? filteredItems
                        : branchItems.length === 1
                          ? branchItems[0]
                          : branchItems
                    }
                    search={search}
                  />
                </div>
              </div>
            )}
            {hasMoreItems && view !== 'binary' && (
              <div className="op-show-more" onClick={() => setShowAllItems(true)}>
                Showing {DISPLAY_LIMIT} of {filteredItems.length} items —{" "}
                <span className="op-show-more-link">Show all {filteredItems.length}</span>
              </div>
            )}
            {view === 'binary' && (
              <div className="op-binary-wrap">
                <div className="op-binary-grid">
                  {binaryEntries.map((bin, idx) => (
                    <div key={idx} className="op-binary-card">
                      <div className="op-binary-card-icon">
                        {bin.mimeType?.startsWith('image/')
                          ? '🖼️'
                          : bin.mimeType === 'application/pdf'
                            ? '📄'
                            : bin.mimeType?.startsWith('text/')
                              ? '📝'
                              : '📁'}
                      </div>
                      <div className="op-binary-card-info">
                        <div className="op-binary-card-name" title={bin.fileName}>
                          {bin.fileName || 'file.bin'}
                        </div>
                        <div className="op-binary-card-meta">
                          <span className="op-binary-tag">{bin.fileSize || `${bin.bytes || 0} B`}</span>
                          <span className="op-binary-tag subtle">{bin.mimeType || 'binary'}</span>
                        </div>
                      </div>
                      <div className="op-binary-card-actions">
                        <button
                          type="button"
                          className="op-btn small primary"
                          onClick={() => setSelectedBinaryModal(bin)}
                          title="Preview file"
                        >
                          👁️ View
                        </button>
                        <button
                          type="button"
                          className="op-btn small ghost"
                          onClick={() => {
                            const token = localStorage.getItem('token') || ''
                            const url = bin.id
                              ? `/api/files/${bin.id}/download${token ? `?token=${encodeURIComponent(token)}` : ''}`
                              : `data:${bin.mimeType || 'application/octet-stream'};base64,${bin.data}`
                            const a = document.createElement('a')
                            a.href = url
                            a.download = bin.fileName || 'download.bin'
                            document.body.appendChild(a)
                            a.click()
                            document.body.removeChild(a)
                          }}
                          title="Download file"
                        >
                          ⬇️
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {selectedBinaryModal && (
        <BinaryDataViewModal
          binaryEntry={selectedBinaryModal}
          onClose={() => setSelectedBinaryModal(null)}
        />
      )}

      {/* Footer */}
      <div className="op-footer">
        {!isEmpty || pinned ? (
          <button
            className="ghost op-clear"
            onClick={() => {
              localStorage.removeItem(`op_pinned_${nodeId}`)
              setPinned(null)
            }}
            title="Clear output and unpin"
          >
            🗑 Clear
          </button>
        ) : (
          <span />
        )}
        <span className="op-footer-hint">
          {totalItemsCount} {totalItemsCount === 1 ? 'item' : 'items'} • {view.toUpperCase()}
        </span>
      </div>
    </div>
  )
}

// Hierarchical n8n-style Schema Tree view for Output
function OutputSchemaTree({ item, nodeLabel, onCopy, filter }) {
  if (!item || typeof item !== 'object' || Object.keys(item).length === 0) {
    return <p className="hint" style={{ padding: '8px 12px' }}>No fields found in output payload.</p>
  }

  const entries = Object.entries(item)

  return (
    <div className="nem-schema-list" style={{ padding: '6px 8px' }}>
      {entries.map(([key, val]) => (
        <OutputSchemaRow
          key={key}
          keyName={key}
          value={val}
          path={key}
          depth={0}
          nodeLabel={nodeLabel}
          onCopy={onCopy}
          filter={filter}
        />
      ))}
    </div>
  )
}

function OutputSchemaRow({
  keyName,
  value,
  path,
  depth = 0,
  nodeLabel,
  onCopy,
  filter,
}) {
  const [expanded, setExpanded] = useState(depth === 0)
  const [showAllItems, setShowAllItems] = useState(false)
  const isObj = value !== null && typeof value === 'object'
  const isArr = Array.isArray(value)

  let typeStr = typeof value
  if (value === null) typeStr = 'null'
  else if (isArr) typeStr = `array[${value.length}]`
  else if (isObj) typeStr = 'object'

  // Value preview string
  let valPreview = ''
  if (!isObj && value !== undefined && value !== null) {
    valPreview = typeof value === 'string' ? `"${value}"` : String(value)
  }

  // Expression syntax for output: {{ $json.field }} or {{ $('NodeName').item.json.field }}
  const cleanLabel = (nodeLabel || '').replace(/'/g, "\\'")
  const expr = cleanLabel ? `{{ $('${cleanLabel}').item.json.${path} }}` : `{{ $json.${path} }}`

  const matches =
    !filter ||
    keyName.toLowerCase().includes(filter.toLowerCase()) ||
    String(valPreview).toLowerCase().includes(filter.toLowerCase())

  return (
    <div className="nem-schema-field-wrap">
      {matches && (
        <div
          className="nem-schema-row"
          style={{ paddingLeft: `${depth * 14 + 6}px` }}
          onClick={(e) => {
            if (
              isObj &&
              (e.target.closest('.nem-schema-expand-btn') || !e.target.closest('.nem-schema-copy-hint'))
            ) {
              setExpanded(!expanded)
            } else {
              onCopy(expr)
            }
          }}
          title={`Click to copy: ${expr}`}
        >
          {isObj ? (
            <span
              className={`nem-schema-expand-btn ${expanded ? 'is-open' : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                setExpanded(!expanded)
              }}
            >
              <svg
                width="10"
                height="10"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
              >
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </span>
          ) : (
            <span className="nem-schema-expand-spacer" />
          )}

          <span className="nem-schema-key">{keyName}</span>
          <span className="nem-schema-colon">:</span>
          <span className={`nem-schema-type type-${isArr ? 'array' : isObj ? 'object' : typeof value}`}>
            {typeStr}
          </span>
          {valPreview && (
            <span className="nem-schema-val-preview" title={valPreview}>
              {valPreview}
            </span>
          )}
          <button
            type="button"
            className="nem-schema-copy-hint"
            onClick={(e) => {
              e.stopPropagation()
              onCopy(expr)
            }}
            tabIndex={-1}
          >
            Copy
          </button>
        </div>
      )}

      {/* Recursive children for nested objects and arrays */}
      {isObj && expanded && (
        <div className="nem-schema-children">
          {isArr
            ? (showAllItems ? value : value.slice(0, 10)).map((subItem, idx) => (
                <OutputSchemaRow
                  key={idx}
                  keyName={`[${idx}]`}
                  value={subItem}
                  path={`${path}[${idx}]`}
                  depth={depth + 1}
                  nodeLabel={nodeLabel}
                  onCopy={onCopy}
                  filter={filter}
                />
              ))
            : Object.entries(value).map(([k, v]) => (
                <OutputSchemaRow
                  key={k}
                  keyName={k}
                  value={v}
                  path={`${path}.${k}`}
                  depth={depth + 1}
                  nodeLabel={nodeLabel}
                  onCopy={onCopy}
                  filter={filter}
                />
              ))}
          {isArr && value.length > 10 && !showAllItems && (
            <div
              className="nem-schema-more-hint clickable"
              style={{
                paddingLeft: `${(depth + 1) * 14 + 20}px`,
                cursor: 'pointer',
                color: '#818cf8',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                paddingTop: 4,
                paddingBottom: 4,
                fontWeight: 500,
              }}
              onClick={(e) => {
                e.stopPropagation()
                setShowAllItems(true)
              }}
              title="Click to show all items"
            >
              <span>+ {value.length - 10} more {value.length - 10 === 1 ? 'item' : 'items'}</span>
              <span style={{ fontSize: 10, textDecoration: 'underline', color: '#a5b4fc' }}>Show all ({value.length})</span>
            </div>
          )}
          {isArr && value.length > 10 && showAllItems && (
            <div
              className="nem-schema-more-hint clickable"
              style={{
                paddingLeft: `${(depth + 1) * 14 + 20}px`,
                cursor: 'pointer',
                color: '#94a3b8',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                paddingTop: 4,
                paddingBottom: 4,
                fontSize: 11,
              }}
              onClick={(e) => {
                e.stopPropagation()
                setShowAllItems(false)
              }}
              title="Click to collapse"
            >
              <span>↑ Show less</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
