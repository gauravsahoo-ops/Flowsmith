import { useState, useMemo, useEffect, useCallback } from 'react'
import { NodeIcon } from './NodeIcons'
import JsonTree from './JsonTree'
import { TableView } from './DataViewer'
import { ancestors } from '../utils/graphUtils'

function unwrapItem(item) {
  if (item == null) return item
  if (typeof item !== 'object') return { value: item }
  // n8n standard: unwrap { json: { ... } }
  if (item.json && typeof item.json === 'object' && !Array.isArray(item.json)) {
    return item.json
  }
  return item
}

function extractOutputs(step, incomingEdge, fallbackOutputs) {
  if (!step && !fallbackOutputs) {
    return { hasData: false, isSkipped: false, branches: {}, defaultBranch: 'main' }
  }
  if (step?.status === 'skipped') {
    return { hasData: false, isSkipped: true, branches: {}, defaultBranch: 'main' }
  }

  const raw = step?.outputs ?? fallbackOutputs
  if (raw == null) {
    return { hasData: false, isSkipped: false, branches: {}, defaultBranch: 'main' }
  }

  let branches = {}

  if (Array.isArray(raw)) {
    branches.main = raw.map(unwrapItem)
  } else if (typeof raw === 'object') {
    const keys = Object.keys(raw)
    const hasHandles = keys.some((k) =>
      ['main', 'true', 'false', '0', '1', 'default', 'success', 'error'].includes(k)
    )

    if (hasHandles) {
      for (const k of keys) {
        const val = raw[k]
        if (Array.isArray(val)) {
          // If 2D array (n8n raw format: [ [ item1, item2 ] ])
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
    } else if (Array.isArray(raw.records)) {
      branches.main = raw.records.map(unwrapItem)
    } else if (raw.output && Array.isArray(raw.output.records)) {
      branches.main = raw.output.records.map(unwrapItem)
    } else if (raw.output && Array.isArray(raw.output)) {
      branches.main = raw.output.map(unwrapItem)
    } else if (raw.output && typeof raw.output === 'object') {
      branches.main = [unwrapItem(raw.output)]
    } else {
      // Single object output payload (e.g. response object or webhook payload)
      branches.main = [unwrapItem(raw)]
    }
  } else {
    branches.main = [{ value: raw }]
  }

  // Determine default branch:
  let defaultBranch = 'main'
  if (incomingEdge?.sourceHandle && branches[incomingEdge.sourceHandle] !== undefined) {
    defaultBranch = incomingEdge.sourceHandle
  } else if (branches.main !== undefined && branches.main.length > 0) {
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
    isSkipped: false,
    stepExecuted: !!step,
    totalItems,
    branches,
    defaultBranch,
  }
}

export default function InputPanel({
  currentNodeId,
  nodes = [],
  edges = [],
  catalog = [],
  trace = [],
  results = {},
  executing = false,
  onExecutePrevious,
}) {
  const [viewMode, setViewMode] = useState('schema') // 'schema' | 'table' | 'json'
  const [showSearch, setShowSearch] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [expandedNodes, setExpandedNodes] = useState({})
  const [copiedSnippet, setCopiedSnippet] = useState(null)
  const [nodeBranches, setNodeBranches] = useState({})
  const [nodeItemIndices, setNodeItemIndices] = useState({})

  // Traverse DAG backwards from currentNodeId to find all ancestor nodes
  const upstreamNodes = useMemo(() => {
    if (!currentNodeId || !nodes || !edges) return []
    const ancestorIds = ancestors(edges, currentNodeId)
    return ancestorIds
      .map((id) => nodes.find((n) => n.id === id))
      .filter(Boolean)
  }, [currentNodeId, nodes, edges])

  // Extract execution data, items count, and labels for each upstream node
  const detailedUpstreamNodes = useMemo(() => {
    return upstreamNodes.map((flowNode, idx) => {
      const node = flowNode.data?.node || flowNode
      const step = trace?.find((s) => s.node_id === flowNode.id)
      const fallbackOutputs = results?.outputs?.[flowNode.id]
      const directEdge = edges.find((e) => e.source === flowNode.id && e.target === currentNodeId)
      const anyEdge = directEdge || edges.find((e) => e.source === flowNode.id)
      const extracted = extractOutputs(step, anyEdge, fallbackOutputs)

      const meta = catalog?.find((c) => c.type === node.type)
      const label =
        node.settings?.label ||
        node.name ||
        flowNode.data?.label ||
        meta?.display_name ||
        node.type

      const isTrigger =
        node.type?.includes('trigger') ||
        node.type === 'webhook' ||
        node.type === 'schedule'

      return {
        id: flowNode.id,
        node,
        meta,
        label,
        isTrigger,
        isDirectParent: idx === 0,
        hasData: extracted.hasData,
        isSkipped: extracted.isSkipped,
        stepExecuted: extracted.stepExecuted,
        totalItems: extracted.totalItems,
        skipNote: step?.note,
        branches: extracted.branches,
        defaultBranch: extracted.defaultBranch,
      }
    })
  }, [upstreamNodes, trace, edges, currentNodeId, catalog])

  // Auto-expand the immediate direct parent by default
  useEffect(() => {
    if (detailedUpstreamNodes.length > 0) {
      setExpandedNodes((prev) => {
        if (Object.keys(prev).length === 0) {
          return { [detailedUpstreamNodes[0].id]: true }
        }
        return prev
      })
    }
  }, [detailedUpstreamNodes])

  const toggleNode = useCallback((id) => {
    setExpandedNodes((prev) => ({
      ...prev,
      [id]: !prev[id],
    }))
  }, [])

  const handleCopyExpression = useCallback((expr) => {
    navigator.clipboard?.writeText(expr)
    setCopiedSnippet(expr)
    setTimeout(() => setCopiedSnippet(null), 2200)
  }, [])

  const filteredNodes = useMemo(() => {
    if (!searchTerm.trim()) return detailedUpstreamNodes
    const q = searchTerm.toLowerCase()
    return detailedUpstreamNodes.filter(
      (n) =>
        n.label.toLowerCase().includes(q) ||
        n.node.type.toLowerCase().includes(q)
    )
  }, [detailedUpstreamNodes, searchTerm])

  return (
    <div className="nem-input-panel">
      {/* Top Header matching n8n */}
      <div className="nem-input-header">
        <div className="nem-input-title-group">
          <span className="nem-input-title">INPUT</span>
          {copiedSnippet && (
            <span className="nem-input-copied-toast" title={copiedSnippet}>
              ✓ Copied: {copiedSnippet}
            </span>
          )}
        </div>

        <div className="nem-input-controls">
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

          <div className="nem-input-tabs">
            <button
              type="button"
              className={`nem-input-tab ${viewMode === 'schema' ? 'active' : ''}`}
              onClick={() => setViewMode('schema')}
            >
              Schema
            </button>
            <button
              type="button"
              className={`nem-input-tab ${viewMode === 'table' ? 'active' : ''}`}
              onClick={() => setViewMode('table')}
            >
              Table
            </button>
            <button
              type="button"
              className={`nem-input-tab ${viewMode === 'json' ? 'active' : ''}`}
              onClick={() => setViewMode('json')}
            >
              JSON
            </button>
          </div>
        </div>
      </div>

      {/* Search Input Bar (collapsible) */}
      {showSearch && (
        <div className="nem-input-search-bar">
          <input
            type="text"
            className="nem-input-search-input"
            placeholder="Filter keys or values…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            autoFocus
          />
          {searchTerm && (
            <button
              type="button"
              className="nem-input-search-clear"
              onClick={() => setSearchTerm('')}
            >
              ✕
            </button>
          )}
        </div>
      )}

      {/* Body List of Previous Nodes */}
      <div className="nem-input-body">
        {detailedUpstreamNodes.length === 0 ? (
          <div className="nem-empty-state">
            <div className="nem-empty-icon-wrap">
              <svg
                width="26"
                height="26"
                viewBox="0 0 24 24"
                fill="none"
                stroke="#818cf8"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
                <path d="M20 21H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2" />
              </svg>
            </div>
            <h4>Initial Node</h4>
            <p className="hint">
              This trigger or root node has no previous steps feeding into it.
            </p>
          </div>
        ) : (
          <>
            {filteredNodes.map((up) => {
              const isOpen = !!expandedNodes[up.id]
              const branchKeys = Object.keys(up.branches || {})
              const currentBranch = nodeBranches[up.id] || up.defaultBranch || 'main'
              const items = up.branches?.[currentBranch] || []
              const currentItemIdx = Math.min(
                nodeItemIndices[up.id] || 0,
                Math.max(0, items.length - 1)
              )
              const currentItem = items[currentItemIdx] || items[0] || {}

              return (
                <div
                  key={up.id}
                  className={`nem-upstream-node-card ${isOpen ? 'is-open' : 'is-collapsed'}`}
                >
                  {/* Node Accordion Header Row */}
                  <div
                    className="nem-upstream-node-header"
                    onClick={() => toggleNode(up.id)}
                    title={isOpen ? 'Click to collapse' : 'Click to expand'}
                  >
                    <span className={`nem-upstream-arrow ${isOpen ? 'open' : ''}`}>
                      <svg
                        width="12"
                        height="12"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <polyline points="9 18 15 12 9 6" />
                      </svg>
                    </span>

                    <span className="nem-upstream-icon">
                      <NodeIcon type={up.node.type} size={15} />
                    </span>

                    <span className="nem-upstream-label" title={up.label}>
                      {up.label}
                    </span>

                    {up.isSkipped ? (
                      <span className="nem-upstream-badge badge-skipped">Skipped</span>
                    ) : up.stepExecuted && up.totalItems === 0 ? (
                      <span className="nem-upstream-badge">0 items</span>
                    ) : (
                      <span className="nem-upstream-badge">
                        {up.hasData
                          ? `${items.length} ${items.length === 1 ? 'item' : 'items'}`
                          : 'No data'}
                      </span>
                    )}
                  </div>

                  {/* Expanded Content View */}
                  {isOpen && (
                    <div className="nem-upstream-node-content">
                      {up.isSkipped ? (
                        <div className="nem-upstream-no-data">
                          <p className="hint" style={{ color: '#fbbf24' }}>
                            ⚠️ {up.skipNote || 'This node was skipped in the execution flow.'}
                          </p>
                        </div>
                      ) : up.stepExecuted && up.totalItems === 0 ? (
                        <div className="nem-upstream-no-data">
                          <p className="hint" style={{ color: '#a1a1aa' }}>
                            ℹ️ This node executed and returned 0 items. Downstream nodes were not executed.
                          </p>
                        </div>
                      ) : up.hasData ? (
                        <div className="nem-upstream-data-viewer">
                          {/* Branch Selector (if multiple output channels, e.g. IF or Router) */}
                          {branchKeys.length > 1 && (
                            <div className="nem-branch-bar">
                              <span className="nem-branch-title">Output:</span>
                              {branchKeys.map((bKey) => {
                                const count = up.branches[bKey]?.length || 0
                                const isActive = currentBranch === bKey
                                return (
                                  <button
                                    key={bKey}
                                    type="button"
                                    className={`nem-branch-pill ${isActive ? 'active' : ''}`}
                                    onClick={() =>
                                      setNodeBranches((prev) => ({ ...prev, [up.id]: bKey }))
                                    }
                                  >
                                    {bKey === 'true'
                                      ? '✓ true'
                                      : bKey === 'false'
                                        ? '✗ false'
                                        : bKey}{' '}
                                    ({count})
                                  </button>
                                )
                              })}
                            </div>
                          )}

                          {/* Multi-item Pager (if node output has multiple items) */}
                          {items.length > 1 && (
                            <div className="nem-item-pager">
                              <button
                                type="button"
                                className="nem-pager-btn"
                                disabled={currentItemIdx <= 0}
                                onClick={() =>
                                  setNodeItemIndices((prev) => ({
                                    ...prev,
                                    [up.id]: currentItemIdx - 1,
                                  }))
                                }
                                title="Previous item"
                              >
                                ◀
                              </button>
                              <span className="nem-pager-label">
                                Item {currentItemIdx + 1} of {items.length}
                              </span>
                              <button
                                type="button"
                                className="nem-pager-btn"
                                disabled={currentItemIdx >= items.length - 1}
                                onClick={() =>
                                  setNodeItemIndices((prev) => ({
                                    ...prev,
                                    [up.id]: currentItemIdx + 1,
                                  }))
                                }
                                title="Next item"
                              >
                                ▶
                              </button>
                            </div>
                          )}

                          {viewMode === 'schema' && (
                            <SchemaNodeView
                              item={currentItem}
                              nodeLabel={up.label}
                              isDirectParent={up.isDirectParent}
                              onCopy={handleCopyExpression}
                              filter={searchTerm}
                            />
                          )}
                          {viewMode === 'table' && <TableView data={items} />}
                          {viewMode === 'json' && (
                            <JsonTree
                              value={items.length === 1 ? items[0] : items}
                              search={searchTerm}
                            />
                          )}
                        </div>
                      ) : (
                        <div className="nem-upstream-no-data">
                          <p className="hint">
                            No execution data captured for this step yet.
                          </p>
                          {onExecutePrevious && (
                            <button
                              type="button"
                              className="ghost small"
                              onClick={onExecutePrevious}
                              disabled={executing}
                              style={{ marginTop: 6 }}
                            >
                              {executing ? 'Executing…' : '▶ Execute Previous Nodes'}
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}

            {/* Variables and Context Accordion Section */}
            <div
              className={`nem-upstream-node-card variables-card ${
                expandedNodes['vars'] ? 'is-open' : 'is-collapsed'
              }`}
            >
              <div
                className="nem-upstream-node-header"
                onClick={() => toggleNode('vars')}
              >
                <span
                  className={`nem-upstream-arrow ${
                    expandedNodes['vars'] ? 'open' : ''
                  }`}
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </span>
                <span className="nem-upstream-label">Variables and context</span>
              </div>

              {expandedNodes['vars'] && (
                <div className="nem-upstream-node-content variables-content">
                  <div className="nem-vars-list">
                    <div
                      className="nem-var-row"
                      onClick={() => handleCopyExpression('{{ $env }}')}
                      title="Click to copy {{ $env }}"
                    >
                      <span className="nem-var-key">$env</span>
                      <span className="nem-var-desc">
                        Workspace environment variables
                      </span>
                    </div>
                    <div
                      className="nem-var-row"
                      onClick={() => handleCopyExpression('{{ $workflow }}')}
                      title="Click to copy {{ $workflow }}"
                    >
                      <span className="nem-var-key">$workflow</span>
                      <span className="nem-var-desc">
                        Current workflow metadata
                      </span>
                    </div>
                    <div
                      className="nem-var-row"
                      onClick={() => handleCopyExpression('{{ $execution }}')}
                      title="Click to copy {{ $execution }}"
                    >
                      <span className="nem-var-key">$execution</span>
                      <span className="nem-var-desc">
                        Current execution context & ID
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// Hierarchical n8n-style Schema Tree view with sample values & copy expressions
function SchemaNodeView({ item, nodeLabel, isDirectParent, onCopy, filter }) {
  if (!item || typeof item !== 'object' || Object.keys(item).length === 0) {
    return <p className="hint" style={{ padding: '8px 4px' }}>No fields found in output payload.</p>
  }

  const entries = Object.entries(item)

  return (
    <div className="nem-schema-list">
      {entries.map(([key, val]) => (
        <SchemaFieldRow
          key={key}
          keyName={key}
          value={val}
          path={key}
          depth={0}
          nodeLabel={nodeLabel}
          isDirectParent={isDirectParent}
          onCopy={onCopy}
          filter={filter}
        />
      ))}
    </div>
  )
}

function SchemaFieldRow({
  keyName,
  value,
  path,
  depth = 0,
  nodeLabel,
  isDirectParent,
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

  // Expression syntax
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
            if (isObj && (e.target.closest('.nem-schema-expand-btn') || !e.target.closest('.nem-schema-copy-hint'))) {
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
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
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

      {/* Recursive children for objects and arrays */}
      {isObj && expanded && (
        <div className="nem-schema-children">
          {isArr
            ? (showAllItems ? value : value.slice(0, 10)).map((subItem, idx) => (
                <SchemaFieldRow
                  key={idx}
                  keyName={`[${idx}]`}
                  value={subItem}
                  path={`${path}[${idx}]`}
                  depth={depth + 1}
                  nodeLabel={nodeLabel}
                  isDirectParent={isDirectParent}
                  onCopy={onCopy}
                  filter={filter}
                />
              ))
            : Object.entries(value).map(([k, v]) => (
                <SchemaFieldRow
                  key={k}
                  keyName={k}
                  value={v}
                  path={`${path}.${k}`}
                  depth={depth + 1}
                  nodeLabel={nodeLabel}
                  isDirectParent={isDirectParent}
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
                color: 'var(--muted)',
                fontSize: 11,
                paddingTop: 4,
                paddingBottom: 4,
              }}
              onClick={(e) => {
                e.stopPropagation()
                setShowAllItems(false)
              }}
            >
              ↑ Show less
            </div>
          )}
        </div>
      )}
    </div>
  )
}
