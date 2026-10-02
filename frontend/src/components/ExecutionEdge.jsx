// ExecutionEdge: connection wire with live run
// highlighting and interactive inline [+] node insertion and [Delete] delete buttons.

import { memo, useState, useRef, useEffect, useMemo } from 'react'
import { BaseEdge, EdgeLabelRenderer, getBezierPath } from '@xyflow/react'
import { useWorkflowStore } from '../stores/workflowStore'
import { NodeIcon } from './NodeIcons'

function EdgeNodePicker({ onSelect, onClose }) {
  const [query, setQuery] = useState('')
  const catalog = useWorkflowStore((s) => s.catalog)
  const pickerRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    inputRef.current?.focus()
    function handlePointer(e) {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) {
        onClose()
      }
    }
    function handleKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('pointerdown', handlePointer, true)
    window.addEventListener('mousedown', handlePointer, true)
    window.addEventListener('touchstart', handlePointer, true)
    window.addEventListener('keydown', handleKey, true)
    window.addEventListener('wheel', onClose, { passive: true, capture: true })
    return () => {
      window.removeEventListener('pointerdown', handlePointer, true)
      window.removeEventListener('mousedown', handlePointer, true)
      window.removeEventListener('touchstart', handlePointer, true)
      window.removeEventListener('keydown', handleKey, true)
      window.removeEventListener('wheel', onClose, { capture: true })
    }
  }, [onClose])

  const filtered = useMemo(() => {
    if (!Array.isArray(catalog)) return []
    // Exclude root triggers when inserting in the middle of a connection
    const nonTriggers = catalog.filter((n) => !n.type?.includes('trigger') && n.type !== 'webhook')
    if (!query.trim()) return nonTriggers
    const q = query.toLowerCase()
    return nonTriggers.filter(
      (n) =>
        (n.display_name || '').toLowerCase().includes(q) ||
        (n.type || '').toLowerCase().includes(q) ||
        (n.description || '').toLowerCase().includes(q)
    )
  }, [catalog, query])

  return (
    <div
      ref={pickerRef}
      className="edge-node-picker nodrag nopan"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="edge-picker-header">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Insert node..."
          className="edge-picker-input"
        />
        <button type="button" className="ghost edge-picker-close" onClick={onClose} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      <div className="edge-picker-list">
        {filtered.length === 0 ? (
          <div className="edge-picker-empty">No matching nodes</div>
        ) : (
          filtered.map((node) => (
            <button
              key={node.type}
              type="button"
              className="edge-picker-item"
              onClick={() => onSelect(node.type)}
            >
              <span className="edge-picker-item-icon">
                <NodeIcon type={node.type} icon={node.icon} size={15} />
              </span>
              <div className="edge-picker-item-info">
                <span className="edge-picker-item-name">{node.display_name}</span>
                {node.description && (
                  <span className="edge-picker-item-desc">{node.description}</span>
                )}
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  )
}

function ExecutionEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  label,
  data,
  selected,
}) {
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })

  const [hovered, setHovered] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const onEdgesChange = useWorkflowStore((s) => s.onEdgesChange)
  const insertNodeOnEdge = useWorkflowStore((s) => s.insertNodeOnEdge)

  const state = data?.state || 'idle'

  function handleDelete(e) {
    e.stopPropagation()
    onEdgesChange([{ id, type: 'remove' }])
  }

  function handleInsert(nodeType) {
    setMenuOpen(false)
    if (insertNodeOnEdge) {
      insertNodeOnEdge(id, nodeType)
    }
  }

  const showActions = hovered || selected || menuOpen

  return (
    <>
      {/* Invisible wider hit area for easy hovering */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={32}
        className="exec-edge-hit-area"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{ cursor: 'pointer' }}
      />

      <BaseEdge
        id={id}
        path={path}
        labelX={labelX}
        labelY={labelY}
        label={label}
        className={`exec-edge exec-${state}`}
      />

      {state === 'active' && (
        <circle r={3} fill="#10b981" style={{ filter: 'drop-shadow(0 0 5px #34d399)' }} pointerEvents="none">
          <animateMotion dur="0.9s" repeatCount="indefinite" path={path} />
        </circle>
      )}

      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
            zIndex: menuOpen ? 1000 : 25,
          }}
          className="nodrag nopan"
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        >
          <div className={`edge-action-pill ${showActions ? 'visible' : ''}`}>
            <button
              type="button"
              className="edge-action-btn plus"
              onClick={(e) => {
                e.stopPropagation()
                setMenuOpen((v) => !v)
              }}
              title="Insert node between these steps"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>
            <button
              type="button"
              className="edge-action-btn delete"
              onClick={handleDelete}
              title="Delete connection"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          </div>

          {menuOpen && (
            <EdgeNodePicker
              onSelect={handleInsert}
              onClose={() => setMenuOpen(false)}
            />
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

export default memo(ExecutionEdge)
