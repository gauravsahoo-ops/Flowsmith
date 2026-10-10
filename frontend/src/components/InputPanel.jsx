import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import { NodeIcon } from './NodeIcons'
import JsonTree from './JsonTree'
import { TableView } from './DataViewer'
import { ancestors } from '../utils/graphUtils'

function unwrapItem(item) {
  if (item == null) return item
  if (typeof item !== 'object') return { value: item }
  // Standard: unwrap { json: { ... } }
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

  const raw = step?.full_outputs ?? fallbackOutputs ?? step?.outputs
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
          // If 2D array (raw format: [ [ item1, item2 ] ])
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
  const [directItemIdx, setDirectItemIdx] = useState(0)

  // Current node reference and direct step inputs (e.g. trigger seeds, webhook payloads, or executed node inputs)
  const currentNode = useMemo(() => {
    const raw = nodes.find((n) => n.id === currentNodeId)
    return raw?.data?.node || raw || {}
  }, [nodes, currentNodeId])

  const currentStep = useMemo(() => {
    return trace?.find((s) => s.node_id === currentNodeId)
  }, [trace, currentNodeId])

  const directInputsRaw = currentStep?.full_inputs ?? results?.inputs?.[currentNodeId] ?? currentStep?.inputs
  const directInputItems = useMemo(() => {
    if (directInputsRaw == null) return []
    if (Array.isArray(directInputsRaw)) {
      return directInputsRaw.map(unwrapItem)
    }
    if (typeof directInputsRaw === 'object') {
      return [unwrapItem(directInputsRaw)]
    }
    return [{ value: directInputsRaw }]
  }, [directInputsRaw])

  const safeDirectItemIdx = Math.min(
    directItemIdx,
    Math.max(0, directInputItems.length - 1)
  )
  const currentDirectItem = directInputItems[safeDirectItemIdx] || directInputItems[0] || {}

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
  }, [upstreamNodes, trace, edges, currentNodeId, catalog, results])

  // Auto-expand the immediate direct parent by default when currentNodeId changes
  const prevNodeIdRef = useRef(currentNodeId)
  useEffect(() => {
    if (prevNodeIdRef.current !== currentNodeId) {
      prevNodeIdRef.current = currentNodeId
      setDirectItemIdx(0)
      if (detailedUpstreamNodes.length > 0) {
        setExpandedNodes({ [detailedUpstreamNodes[0].id]: true })
      } else {
        setExpandedNodes({ direct_inputs: true })
      }
    } else if (detailedUpstreamNodes.length > 0) {
      setExpandedNodes((prev) => {
        if (Object.keys(prev).length === 0) {
          return { [detailedUpstreamNodes[0].id]: true }
        }
        return prev
      })
    }
  }, [currentNodeId, detailedUpstreamNodes])

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
      {/* Top Header */}
      <div className="nem-input-header">
        <div className="nem-input-title-group">
          <span className="nem-input-title">INPUT</span>
          {copiedSnippet && (
            <span className="nem-input-copied-toast" title={copiedSnippet} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>Copied: {copiedSnippet}</span>
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
              aria-label="Clear search"
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          )}
        </div>
      )}

      {/* Body List of Previous Nodes & Step Inputs */}
      <div className="nem-input-body">
        {/* If current step has direct inputs (e.g. trigger seed payload, webhook body, or executed step inputs) */}
        {directInputItems.length > 0 && (
          <div
            className={`nem-upstream-node-card direct-inputs-card ${
              expandedNodes['direct_inputs'] !== false ? 'is-open' : 'is-collapsed'
            }`}
          >
            <div
              className="nem-upstream-node-header"
              onClick={() => toggleNode('direct_inputs')}
              title={expandedNodes['direct_inputs'] !== false ? 'Click to collapse' : 'Click to expand'}
            >
              <span className={`nem-upstream-arrow ${expandedNodes['direct_inputs'] !== false ? 'open' : ''}`}>
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
                <NodeIcon type={currentNode.type || 'webhook'} size={15} />
              </span>

              <span className="nem-upstream-label" title={detailedUpstreamNodes.length === 0 ? 'Trigger / Initial Input Payload' : 'Direct Step Inputs'}>
                {detailedUpstreamNodes.length === 0
                  ? (currentNode.settings?.label || currentNode.name || 'Trigger / Initial Input Payload')
                  : 'Direct Step Inputs'}
              </span>

              <span className="nem-upstream-badge">
                {directInputItems.length} {directInputItems.length === 1 ? 'item' : 'items'}
              </span>
            </div>

            {expandedNodes['direct_inputs'] !== false && (
              <div className="nem-upstream-node-content">
                <div className="nem-upstream-data-viewer">
                  {directInputItems.length > 1 && (
                    <div className="nem-item-pager" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <button
                        type="button"
                        className="nem-pager-btn"
                        disabled={safeDirectItemIdx <= 0}
                        onClick={() => setDirectItemIdx(0)}
                        title="First item"
                        aria-label="First item"
                        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                      >
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="11 18 5 12 11 6"/><line x1="19" y1="6" x2="19" y2="18"/></svg>
                      </button>
                      <button
                        type="button"
                        className="nem-pager-btn"
                        disabled={safeDirectItemIdx <= 0}
                        onClick={() => setDirectItemIdx((p) => Math.max(0, p - 1))}
                        title="Previous item"
                        aria-label="Previous item"
                        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                      >
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="15 18 9 12 15 6"/></svg>
                      </button>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        <span className="nem-pager-label">Item</span>
                        <input
                          type="number"
                          min={1}
                          max={directInputItems.length}
                          value={safeDirectItemIdx + 1}
                          onChange={(e) => {
                            const val = parseInt(e.target.value, 10)
                            if (!isNaN(val) && val >= 1 && val <= directInputItems.length) {
                              setDirectItemIdx(val - 1)
                            }
                          }}
                          style={{
                            width: Math.max(38, String(directInputItems.length).length * 9 + 18),
                            textAlign: 'center',
                            padding: '2px 4px',
                            fontSize: 11.5,
                            fontFamily: 'ui-monospace, monospace',
                            background: 'var(--panel-2, #181c24)',
                            border: '1px solid var(--border)',
                            borderRadius: 4,
                            color: 'var(--text)',
                          }}
                          title="Type item number to jump directly"
                        />
                        <span className="nem-pager-label">of {directInputItems.length}</span>
                      </div>
                      <button
                        type="button"
                        className="nem-pager-btn"
                        disabled={safeDirectItemIdx >= directInputItems.length - 1}
                        onClick={() => setDirectItemIdx((p) => Math.min(directInputItems.length - 1, p + 1))}
                        title="Next item"
                        aria-label="Next item"
                        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                      >
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="9 18 15 12 9 6"/></svg>
                      </button>
                      <button
                        type="button"
                        className="nem-pager-btn"
                        disabled={safeDirectItemIdx >= directInputItems.length - 1}
                        onClick={() => setDirectItemIdx(directInputItems.length - 1)}
                        title="Last item"
                        aria-label="Last item"
                        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                      >
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="13 18 19 12 13 6"/><line x1="5" y1="6" x2="5" y2="18"/></svg>
                      </button>
                    </div>
                  )}
                  {viewMode === 'schema' && (
                    <SchemaNodeView
                      item={currentDirectItem}
                      nodeLabel={currentNode.settings?.label || currentNode.name || 'Input'}
                      isDirectParent={true}
                      onCopy={handleCopyExpression}
                      filter={searchTerm}
                    />
                  )}
                  {viewMode === 'table' && <TableView data={directInputItems} />}
                  {viewMode === 'json' && (
                    <JsonTree
                      value={directInputItems.length === 1 ? directInputItems[0] : directInputItems}
                      search={searchTerm}
                    />
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {detailedUpstreamNodes.length === 0 && directInputItems.length === 0 && (
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
        )}

        {detailedUpstreamNodes.length > 0 && (
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
                          <p className="hint" style={{ color: '#fbbf24', display: 'flex', alignItems: 'center', gap: 6 }}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                            <span>{up.skipNote || 'This node was skipped in the execution flow.'}</span>
                          </p>
                        </div>
                      ) : up.stepExecuted && up.totalItems === 0 ? (
                        <div className="nem-upstream-no-data">
                          <p className="hint" style={{ color: '#a1a1aa', display: 'flex', alignItems: 'center', gap: 6 }}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                            <span>This node executed and returned 0 items. Downstream nodes were not executed.</span>
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
                                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                                  >
                                    {bKey === 'true' ? (
                                       <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                                    ) : bKey === 'false' ? (
                                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                                    ) : null}
                                    <span>{bKey} ({count})</span>
                                  </button>
                                )
                              })}
                            </div>
                          )}

                          {/* Multi-item Pager (if node output has multiple items) */}
                          {items.length > 1 && (
                            <div className="nem-item-pager" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <button
                                type="button"
                                className="nem-pager-btn"
                                disabled={currentItemIdx <= 0}
                                onClick={() =>
                                  setNodeItemIndices((prev) => ({
                                    ...prev,
                                    [up.id]: 0,
                                  }))
                                }
                                title="First item"
                                aria-label="First item"
                                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                              >
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="11 18 5 12 11 6"/><line x1="19" y1="6" x2="19" y2="18"/></svg>
                              </button>
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
                                aria-label="Previous item"
                                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                              >
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="15 18 9 12 15 6"/></svg>
                              </button>

                              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                <span className="nem-pager-label">Item</span>
                                <input
                                  type="number"
                                  min={1}
                                  max={items.length}
                                  value={currentItemIdx + 1}
                                  onChange={(e) => {
                                    const val = parseInt(e.target.value, 10)
                                    if (!isNaN(val) && val >= 1 && val <= items.length) {
                                      setNodeItemIndices((prev) => ({
                                        ...prev,
                                        [up.id]: val - 1,
                                      }))
                                    }
                                  }}
                                  style={{
                                    width: Math.max(38, String(items.length).length * 9 + 18),
                                    textAlign: 'center',
                                    padding: '2px 4px',
                                    fontSize: 11.5,
                                    fontFamily: 'ui-monospace, monospace',
                                    background: 'var(--panel-2, #181c24)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 4,
                                    color: 'var(--text)',
                                  }}
                                  title="Type item number to jump directly"
                                />
                                <span className="nem-pager-label">of {items.length}</span>
                              </div>

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
                                aria-label="Next item"
                                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                              >
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="9 18 15 12 9 6"/></svg>
                              </button>
                              <button
                                type="button"
                                className="nem-pager-btn"
                                disabled={currentItemIdx >= items.length - 1}
                                onClick={() =>
                                  setNodeItemIndices((prev) => ({
                                    ...prev,
                                    [up.id]: items.length - 1,
                                  }))
                                }
                                title="Last item"
                                aria-label="Last item"
                                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                              >
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="13 18 19 12 13 6"/><line x1="5" y1="6" x2="5" y2="18"/></svg>
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
                              onClick={() => onExecutePrevious(up.id)}
                              disabled={executing}
                              style={{ marginTop: 6, display: 'inline-flex', alignItems: 'center', gap: 5 }}
                              title="Execute this upstream node to capture live test data"
                            >
                              {executing ? (
                                'Executing…'
                              ) : (
                                <>
                                  <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                                  <span>Execute Previous Node</span>
                                </>
                              )}
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </>
        )}

        {/* Variables and Context Accordion Section — Always available */}
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
                {[
                  { key: '$env', desc: 'Workspace environment variables' },
                  { key: '$workflow', desc: 'Current workflow metadata' },
                  { key: '$execution', desc: 'Current execution context & ID' },
                  { key: '$now', desc: 'Current UTC timestamp / ISO string' },
                ].map((item) => (
                  <div
                    key={item.key}
                    className="nem-var-row draggable-variable"
                    draggable={true}
                    onDragStart={(e) => {
                      e.stopPropagation()
                      const expr = `{{ ${item.key} }}`
                      e.dataTransfer.setData('text/plain', expr)
                      e.dataTransfer.setData('application/flowsmith-variable', JSON.stringify({ expr, path: item.key, key: item.key }))
                      e.dataTransfer.effectAllowed = 'copy'
                      e.currentTarget.classList.add('is-dragging')
                    }}
                    onDragEnd={(e) => {
                      e.currentTarget.classList.remove('is-dragging')
                    }}
                    onClick={() => handleCopyExpression(`{{ ${item.key} }}`)}
                    title={`Drag into parameter input or click to copy {{ ${item.key} }}`}
                  >
                    <span className="nem-schema-drag-handle" title="Drag variable into parameter fields">
                      <svg width="8" height="12" viewBox="0 0 8 12" fill="currentColor">
                        <circle cx="2" cy="2" r="1.2" />
                        <circle cx="6" cy="2" r="1.2" />
                        <circle cx="2" cy="6" r="1.2" />
                        <circle cx="6" cy="6" r="1.2" />
                        <circle cx="2" cy="10" r="1.2" />
                        <circle cx="6" cy="10" r="1.2" />
                      </svg>
                    </span>
                    <div className="nem-var-info">
                      <span className="nem-var-key">{item.key}</span>
                      <span className="nem-var-desc">{item.desc}</span>
                    </div>
                    <button
                      type="button"
                      className={`nem-schema-copy-hint ${copiedSnippet === `{{ ${item.key} }}` ? 'is-copied' : ''}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleCopyExpression(`{{ ${item.key} }}`)
                      }}
                      tabIndex={-1}
                      title={`Copy {{ ${item.key} }}`}
                    >
                      {copiedSnippet === `{{ ${item.key} }}` ? (
                        <>
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>
                          <span>Copied</span>
                        </>
                      ) : (
                        <>
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></svg>
                          <span>Copy</span>
                        </>
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// Hierarchical Schema Tree view with sample values & copy expressions
function SchemaNodeView({ item, nodeLabel, isDirectParent, onCopy, filter }) {
  if (!item || typeof item !== 'object' || Object.keys(item).length === 0) {
    return <p className="hint" style={{ padding: '8px 4px' }}>No fields found in output payload.</p>
  }

  const entries = Object.entries(item)

  return (
    <div className="nem-schema-list">
      {entries.map(([key, val]) => {
        const rootPath = /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(key) ? key : `['${key.replace(/'/g, "\\'")}']`
        return (
          <SchemaFieldRow
            key={key}
            keyName={key}
            value={val}
            path={rootPath}
            depth={0}
            nodeLabel={nodeLabel}
            isDirectParent={isDirectParent}
            onCopy={onCopy}
            filter={filter}
          />
        )
      })}
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
  const [chunkLimit, setChunkLimit] = useState(25)
  const [copied, setCopied] = useState(false)
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

  // Expression syntax: direct upstream parent can simply use $json.path
  const cleanLabel = (nodeLabel || '').replace(/'/g, "\\'")
  const pathExpr = path.startsWith('[') ? path : `.${path}`
  const expr = (!isDirectParent && cleanLabel) ? `{{ $('${cleanLabel}').item.json${pathExpr} }}` : `{{ $json${pathExpr} }}`

  const matches =
    !filter ||
    keyName.toLowerCase().includes(filter.toLowerCase()) ||
    String(valPreview).toLowerCase().includes(filter.toLowerCase())

  const handleCopy = (e) => {
    e?.stopPropagation()
    onCopy(expr)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="nem-schema-field-wrap">
      {matches && (
        <div
          className="nem-schema-row draggable-variable"
          draggable={true}
          onDragStart={(e) => {
            e.stopPropagation()
            e.dataTransfer.setData('text/plain', expr)
            e.dataTransfer.setData('application/flowsmith-variable', JSON.stringify({ expr, path, key: keyName }))
            e.dataTransfer.effectAllowed = 'copy'
            e.currentTarget.classList.add('is-dragging')
          }}
          onDragEnd={(e) => {
            e.currentTarget.classList.remove('is-dragging')
          }}
          onClick={(e) => {
            if (isObj && (e.target.closest('.nem-schema-expand-btn') || !e.target.closest('.nem-schema-copy-hint'))) {
              setExpanded(!expanded)
            } else {
              handleCopy(e)
            }
          }}
          title={`Drag into parameter input or click to copy: ${expr}`}
        >
          <span className="nem-schema-drag-handle" title="Drag variable into parameter fields">
            <svg width="8" height="12" viewBox="0 0 8 12" fill="currentColor">
              <circle cx="2" cy="2" r="1.2" />
              <circle cx="6" cy="2" r="1.2" />
              <circle cx="2" cy="6" r="1.2" />
              <circle cx="6" cy="6" r="1.2" />
              <circle cx="2" cy="10" r="1.2" />
              <circle cx="6" cy="10" r="1.2" />
            </svg>
          </span>

          {isObj ? (
            <button
              type="button"
              className={`nem-schema-expand-btn ${expanded ? 'is-open' : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                setExpanded(!expanded)
              }}
              title={expanded ? 'Collapse' : 'Expand'}
              aria-label={expanded ? 'Collapse' : 'Expand'}
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </button>
          ) : (
            <span className="nem-schema-expand-spacer" />
          )}

          <div className="nem-schema-main-content">
            <span className="nem-schema-key" title={keyName}>{keyName}</span>
            <span className="nem-schema-colon">:</span>
            <span className={`nem-schema-type type-${isArr ? 'array' : isObj ? 'object' : typeof value}`}>
              {typeStr}
            </span>
            {valPreview && (
              <span className="nem-schema-val-preview" title={valPreview}>
                {valPreview}
              </span>
            )}
          </div>

          <button
            type="button"
            className={`nem-schema-copy-hint ${copied ? 'is-copied' : ''}`}
            onClick={handleCopy}
            tabIndex={-1}
            title={`Copy ${expr}`}
          >
            {copied ? (
              <>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>
                <span>Copied</span>
              </>
            ) : (
              <>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2" /><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" /></svg>
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      )}

      {/* Recursive children for objects and arrays */}
      {isObj && expanded && (
        <div className="nem-schema-children">
          {isArr
            ? (showAllItems ? value : value.slice(0, chunkLimit)).map((subItem, idx) => (
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
            : Object.entries(value).map(([k, v]) => {
                const childPath = /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(k)
                  ? `${path}.${k}`
                  : `${path}['${k.replace(/'/g, "\\'")}']`
                return (
                  <SchemaFieldRow
                    key={k}
                    keyName={k}
                    value={v}
                    path={childPath}
                    depth={depth + 1}
                    nodeLabel={nodeLabel}
                    isDirectParent={isDirectParent}
                    onCopy={onCopy}
                    filter={filter}
                  />
                )
              })}
          {isArr && value.length > chunkLimit && !showAllItems && (
            <div className="nem-schema-more-hint" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 6px' }}>
              <span>Showing {chunkLimit} of {value.length} items —</span>
              <button
                type="button"
                className="nem-schema-chunk-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  setChunkLimit((c) => Math.min(c + 25, value.length))
                }}
                style={{
                  background: 'var(--panel-2, #1e293b)',
                  border: '1px solid var(--border)',
                  color: 'var(--text)',
                  fontSize: 10.5,
                  padding: '2px 7px',
                  borderRadius: 4,
                  cursor: 'pointer',
                }}
              >
                + Show {Math.min(25, value.length - chunkLimit)} more
              </button>
              <button
                type="button"
                className="nem-schema-chunk-btn text-accent"
                onClick={(e) => {
                  e.stopPropagation()
                  setShowAllItems(true)
                }}
                style={{
                  background: 'transparent',
                  border: '1px solid rgba(99, 102, 241, 0.4)',
                  color: '#818cf8',
                  fontSize: 10.5,
                  padding: '2px 7px',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontWeight: 600,
                }}
              >
                Show all ({value.length})
              </button>
            </div>
          )}
          {isArr && (showAllItems || chunkLimit > 25) && (
            <div
              className="nem-schema-more-hint clickable"
              onClick={(e) => {
                e.stopPropagation()
                setShowAllItems(false)
                setChunkLimit(25)
              }}
              title="Click to collapse"
              style={{ cursor: 'pointer', color: 'var(--muted)', fontSize: 11, padding: '4px 6px' }}
            >
              <span>↑ Show less</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
