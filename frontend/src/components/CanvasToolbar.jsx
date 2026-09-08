// CanvasToolbar (Phase 12): floating editor tools.
//
// Own design language: a single glass strip docked top-center of the
// canvas — undo/redo, auto-layout, comment, group, fit, shortcuts help,
// and the graph-health indicator (connection validation summary).

import { useMemo, useState } from 'react'
import { useReactFlow } from '@xyflow/react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import Tooltip from './shared/Tooltip'

function ToolButton({ onClick, disabled, title, children, className = '' }) {
  return (
    <Tooltip label={title}>
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

export default function CanvasToolbar() {
  const { fitView, zoomIn, zoomOut } = useReactFlow()
  const canUndo = useWorkflowStore((s) => s.canUndo)
  const canRedo = useWorkflowStore((s) => s.canRedo)
  const undo = useWorkflowStore((s) => s.undo)
  const redo = useWorkflowStore((s) => s.redo)
  const nodes = useWorkflowStore((s) => s.nodes)
  const edges = useWorkflowStore((s) => s.edges)
  const comments = useWorkflowStore((s) => s.comments)
  const groups = useWorkflowStore((s) => s.groups)
  const showMiniMap = useUiStore((s) => s.showMiniMap)
  const toggleMiniMap = useUiStore((s) => s.toggleMiniMap)

  const [showProblems, setShowProblems] = useState(false)

  // Lightweight graph check: cycles and duplicate wires are allowed (the
  // engine executes nodes in topological order, each at most once per
  // pass), so we only flag nodes that are completely unconnected.
  const health = useMemo(() => {
    const connected = new Set()
    for (const e of edges) {
      connected.add(e.source)
      connected.add(e.target)
    }
    const orphans = nodes
      .filter((n) => n.type === 'custom' && !connected.has(n.id))
      .map((n) => `"${n.data?.node?.type || n.id}" (${n.id}) is not connected to anything`)
    return { ok: orphans.length === 0, problems: orphans }
  }, [nodes, edges])

  function onAutoLayout() {
    import('../utils/autoLayout').then(({ autoLayout }) => {
      const store = useWorkflowStore.getState()
      if (store.nodes.length < 2) return
      store.pushHistory('autolayout')
      const positions = autoLayout(
        store.nodes.filter((n) => n.type === 'custom'),
        store.edges,
      )
      useWorkflowStore.getState().onNodesChange(
        [...positions.entries()].map(([id, position]) => ({
          id,
          type: 'position',
          position,
          dragging: false,
        })),
      )
      setTimeout(() => fitView({ duration: 400, padding: 0.15 }), 60)
    })
  }

  function onAddComment() {
    const store = useWorkflowStore.getState()
    // Drop new notes near the viewport centre so they're never lost.
    store.addComment({ x: 120 + store.comments.length * 24, y: 120 + store.comments.length * 18 }, '')
  }

  function onGroup() {
    const store = useWorkflowStore.getState()
    const selected = store.nodes.filter((n) => n.selected).map((n) => n.id)
    if (!store.groupSelected(selected)) return
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
        title={`Add a comment (${comments.length} on canvas)`}
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
        title={`Group selected nodes (${groups.length} groups)`}
        onClick={onGroup}
        disabled={nodes.filter((n) => n.selected).length < 2}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" strokeDasharray="3 3" />
            <rect x="7" y="7" width="4" height="4" rx="1" />
            <rect x="13" y="13" width="4" height="4" rx="1" />
          </svg>
          Group
        </span>
      </ToolButton>
      <span className="tool-sep" />
      <ToolButton title="Zoom to fit (Ctrl+0)" onClick={() => fitView({ duration: 300, padding: 0.15 })}>
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
      <ToolButton title="Zoom in (+)" onClick={() => zoomIn({ duration: 200 })}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </ToolButton>
      <ToolButton title="Zoom out (-)" onClick={() => zoomOut({ duration: 200 })}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      </ToolButton>
      <Tooltip
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
    </div>
  )
}
