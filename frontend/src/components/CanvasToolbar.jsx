// CanvasToolbar (Phase 12): floating editor tools.
//
// Own design language: a single glass strip docked top-center of the
// canvas — undo/redo, auto-layout, comment, group, fit, shortcuts help,
// and the graph-health indicator (connection validation summary).

import { useMemo, useState, useEffect, memo } from 'react'
import { useReactFlow, useViewport } from '@xyflow/react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import Tooltip from './shared/Tooltip'
import InCanvasCopilot from './InCanvasCopilot'

function ToolButton({ onClick, disabled, title, children, className = '' }) {
  return (
    <Tooltip label={title} placement="bottom">
      <button
        className={`tool-btn ${className}`}
        onClick={onClick}
        disabled={disabled}
        type="button"
      >
        {children}
      </button>
    </Tooltip>
  )
}

/**
 * Isolated zoom percentage indicator.
 * Consuming useViewport() here ensures panning/zooming re-renders only this tiny button,
 * keeping the entire CanvasToolbar, undo/redo states, and health checks free of 60fps churn.
 */
const ZoomPercentButton = memo(function ZoomPercentButton({ onResetZoom }) {
  const viewport = useViewport()
  const zoomPercent = Math.round((viewport?.zoom || 1) * 100)
  return (
    <ToolButton title="Reset zoom to 100% (Ctrl+1)" onClick={onResetZoom}>
      <span style={{ fontSize: 10.5, fontWeight: 700, minWidth: 32, textAlign: 'center', color: '#cbd5e1' }}>
        {zoomPercent}%
      </span>
    </ToolButton>
  )
})

function CanvasToolbarComponent() {
  const { fitView, zoomIn, zoomOut, zoomTo, screenToFlowPosition } = useReactFlow()
  const canUndo = useWorkflowStore((s) => s.canUndo)
  const canRedo = useWorkflowStore((s) => s.canRedo)
  const undo = useWorkflowStore((s) => s.undo)
  const redo = useWorkflowStore((s) => s.redo)
  // Structural subscriptions: extract only IDs and topology so node position changes during drag do NOT re-render the toolbar
  const nodeTopology = useWorkflowStore(
    (s) => s.nodes.map((n) => `${n.id}:${n.type}:${n.data?.node?.type || ''}`).join('|')
  )
  const edgeTopology = useWorkflowStore(
    (s) => s.edges.map((e) => `${e.source}->${e.target}`).join('|')
  )
  const commentsCount = useWorkflowStore((s) => s.comments.length)
  const groupsCount = useWorkflowStore((s) => s.groups.length)
  const showMiniMap = useUiStore((s) => s.showMiniMap)
  const toggleMiniMap = useUiStore((s) => s.toggleMiniMap)

  const [showProblems, setShowProblems] = useState(false)
  const [copilotOpen, setCopilotOpen] = useState(false)

  // Alt+A toggles In-Canvas AI Copilot
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.altKey && (e.key === 'a' || e.key === 'A')) {
        e.preventDefault()
        setCopilotOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Lightweight graph check: derived only when topology (nodes/edges structure) changes, never on position drags
  const health = useMemo(() => {
    if (!nodeTopology) return { ok: true, problems: [] }
    const store = useWorkflowStore.getState()
    const edgePairs = edgeTopology.split('|').filter(Boolean)
    const connected = new Set()
    for (const pair of edgePairs) {
      const [src, tgt] = pair.split('->')
      if (src) connected.add(src)
      if (tgt) connected.add(tgt)
    }
    const orphans = store.nodes
      .filter((n) => n.type === 'custom' && !connected.has(n.id))
      .map((n) => `"${n.data?.node?.type || n.id}" (${n.id}) is not connected to anything`)
    return { ok: orphans.length === 0, problems: orphans }
  }, [nodeTopology, edgeTopology])

  function onAutoLayout() {
    import('../utils/autoLayout').then(({ autoLayout, animateAutoLayout }) => {
      const store = useWorkflowStore.getState()
      if (store.nodes.length < 2) return
      store.pushHistory('autolayout')
      const positions = autoLayout(
        store.nodes.filter((n) => n.type === 'custom'),
        store.edges,
      )
      if (typeof animateAutoLayout === 'function') {
        animateAutoLayout(store, positions, 280, () => {
          fitView({ duration: 400, padding: 0.15, maxZoom: 1 })
        })
      } else {
        useWorkflowStore.getState().onNodesChange(
          [...positions.entries()].map(([id, position]) => ({
            id,
            type: 'position',
            position,
            dragging: false,
          })),
        )
        setTimeout(() => fitView({ duration: 400, padding: 0.15, maxZoom: 1 }), 60)
      }
    })
  }

  function onAddComment() {
    const store = useWorkflowStore.getState()
    let at = { x: 120 + store.comments.length * 24, y: 120 + store.comments.length * 18 }
    if (typeof screenToFlowPosition === 'function') {
      const center = screenToFlowPosition({
        x: window.innerWidth / 2 - 110,
        y: window.innerHeight / 2 - 45,
      })
      if (Number.isFinite(center.x) && Number.isFinite(center.y)) {
        at = { x: Math.round(center.x), y: Math.round(center.y) }
      }
    }
    store.addComment(at, '')
  }

  function onGroup() {
    const store = useWorkflowStore.getState()
    const selected = store.nodes.filter((n) => n.selected).map((n) => n.id)
    store.groupSelected(selected)
  }

  const problemCount = health.problems.length

  return (
    <div className="canvas-toolbar">
      <ToolButton title="Undo (Ctrl+Z)" onClick={undo} disabled={!canUndo}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 7v6h6" />
          <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" />
        </svg>
      </ToolButton>
      <ToolButton title="Redo (Ctrl+Shift+Z)" onClick={redo} disabled={!canRedo}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 7v6h-6" />
          <path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3l3 2.7" />
        </svg>
      </ToolButton>
      <span className="tool-sep" />
      <ToolButton
        title="AI Copilot (Alt+A) — natural language surgical workflow edits"
        onClick={() => setCopilotOpen((v) => !v)}
        className={copilotOpen ? 'active' : ''}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: '#c084fc', fontWeight: 600 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z" />
          </svg>
          Copilot
        </span>
      </ToolButton>
      <ToolButton title="Auto-layout (tidy everything)" onClick={onAutoLayout}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1.5" />
            <rect x="14" y="3" width="7" height="7" rx="1.5" />
            <rect x="14" y="14" width="7" height="7" rx="1.5" />
            <rect x="3" y="14" width="7" height="7" rx="1.5" />
          </svg>
          Layout
        </span>
      </ToolButton>
      <ToolButton
        title={`Add a comment (${commentsCount} on canvas)`}
        onClick={onAddComment}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <line x1="10" y1="9" x2="8" y2="9" />
          </svg>
          Note
        </span>
      </ToolButton>
      <ToolButton
        title={`Add Group Frame (${groupsCount} active)`}
        onClick={onGroup}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" strokeDasharray="3 3" />
            <rect x="7" y="7" width="4" height="4" rx="1" />
            <rect x="13" y="13" width="4" height="4" rx="1" />
          </svg>
          Frame
        </span>
      </ToolButton>
      <span className="tool-sep" />
      <ToolButton title="Zoom to fit (Ctrl+0)" onClick={() => fitView({ duration: 300, padding: 0.15, maxZoom: 1 })}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
          </svg>
          Fit
        </span>
      </ToolButton>
      <ToolButton title={showMiniMap ? 'Hide canvas minimap' : 'Show canvas minimap'} onClick={toggleMiniMap}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: showMiniMap ? '#818cf8' : 'inherit' }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21" />
            <line x1="9" y1="3" x2="9" y2="18" />
            <line x1="15" y1="6" x2="15" y2="21" />
          </svg>
          Map
        </span>
      </ToolButton>
      <span className="tool-sep" />
      <ToolButton title="Zoom out (-)" onClick={() => zoomOut({ duration: 200 })}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </ToolButton>
      <ZoomPercentButton onResetZoom={() => zoomTo(1, { duration: 200 })} />
      <ToolButton title="Zoom in (+)" onClick={() => zoomIn({ duration: 200 })}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </ToolButton>
      <Tooltip
        placement="bottom"
        label={
          problemCount
            ? `${problemCount} unconnected node(s) — click to review`
            : 'Graph is clean: all nodes are connected'
        }
      >
        <button
          type="button"
          className={`tool-btn tool-health ${problemCount ? 'warn' : 'ok'}`}
          onClick={() => setShowProblems((v) => !v)}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          {problemCount ? (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <span>{problemCount}</span>
            </>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          )}
        </button>
      </Tooltip>

      {showProblems && (
        <div className="toolbar-popover">
          <h4>Graph check</h4>
          {problemCount === 0 ? (
            <p className="hint">All nodes are connected to the graph.</p>
          ) : (
            <ul>
              {health.problems.slice(0, 8).map((p) => (
                <li key={p}>{p}</li>
              ))}
              {health.problems.length > 8 && (
                <li className="hint">…and {health.problems.length - 8} more</li>
              )}
            </ul>
          )}
          <button type="button" className="ghost" onClick={() => setShowProblems(false)}>
            Close
          </button>
        </div>
      )}

      <InCanvasCopilot
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        onAutoLayout={onAutoLayout}
        fitView={fitView}
      />
    </div>
  )
}

const CanvasToolbar = memo(CanvasToolbarComponent)
export default CanvasToolbar

