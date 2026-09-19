import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  MiniMap,
  ReactFlow,
  useNodesInitialized,
  useReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useWorkflowStore } from '../stores/workflowStore'
import { useExecutionStore } from '../stores/executionStore'
import { useUiStore } from '../stores/uiStore'
import CustomNode from './CustomNode'
import CommentNode from './CommentNode'
import GroupNode from './GroupNode'
import ExecutionEdge from './ExecutionEdge'
import CanvasToolbar from './CanvasToolbar'
import CommandPalette from './CommandPalette'
import FlowsmithBrandMark from './FlowsmithBrandMark'
import { draggedNodeType } from '../utils/drag'
import { edgeKey } from '../utils/graphUtils'
import { toReactFlow, readDecorations } from '../mappers'

const nodeTypes = {
  custom: CustomNode,
  comment: CommentNode,
  group: GroupNode,
}
const edgeTypes = { exec: ExecutionEdge }
const defaultEdgeOptions = { type: 'exec' }

/**
 * Decorations (comments/groups) are editor-only; they render beneath the
 * real nodes and are never part of the saved graph nodes.
 */
function useDecoratedNodes(nodes, comments, groups) {
  return useMemo(() => {
    const groupNodes = groups.map((g) => ({
      id: g.id,
      type: 'group',
      position: { x: g.x, y: g.y },
      data: { group: g },
      selectable: true,
      draggable: false, // moves via its own drag handler (moves members too)
      zIndex: -1,
      style: { width: g.width, height: g.height },
    }))
    const commentNodes = comments.map((c) => ({
      id: c.id,
      type: 'comment',
      position: { x: c.x, y: c.y },
      data: { comment: c },
      zIndex: 0,
      style: { width: c.width, height: c.height },
    }))
    return [...groupNodes, ...commentNodes, ...nodes]
  }, [nodes, comments, groups])
}

/** Wire run-state for execution highlighting, derived once per change. */
function useLabeledStatefulEdges(edges, edgeLabels, nodeStatuses, running) {
  return useMemo(() => {
    const hasLabels = Object.keys(edgeLabels).length > 0
    const anyRunning = running || Object.values(nodeStatuses).some((s) => s === 'running' || s === 'waiting_approval')
    const hasAnyStatus = Object.keys(nodeStatuses).length > 0
    if (!hasLabels && !anyRunning && !hasAnyStatus) return edges
    return edges.map((e) => {
      let state = 'idle'
      const sourceStatus = nodeStatuses[e.source]
      const targetStatus = nodeStatuses[e.target]
      if (targetStatus === 'failed' || targetStatus === 'error') state = 'error'
      else if (targetStatus === 'skipped') state = 'skipped'
      else if (sourceStatus === 'success' || sourceStatus === 'skipped') state = 'active'
      else if (sourceStatus === 'running' || sourceStatus === 'waiting_approval') state = 'active'
      else if (hasAnyStatus && sourceStatus && targetStatus) {
        // For completed runs without `running` flag, highlight based on final statuses
        if (sourceStatus === 'success' && (targetStatus === 'success' || targetStatus === 'skipped')) state = 'active'
        if (targetStatus === 'failed' || targetStatus === 'error') state = 'error'
        if (targetStatus === 'skipped') state = 'skipped'
      }
      const label = edgeLabels[edgeKey(e)]
      const prevData = e.data || {}
      const prevLabel = e.label
      if (prevData.state === state && prevLabel === label) return e
      return { ...e, type: 'exec', label, data: { ...prevData, state } }
    })
  }, [edges, edgeLabels, nodeStatuses, running])
}

function EdgeContextMenu({ x, y, edgeId, onClose }) {
  const menuRef = useRef(null)
  const onEdgesChange = useWorkflowStore((s) => s.onEdgesChange)

  useEffect(() => {
    let active = true
    function handlePointer(e) {
      if (!active) return
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        onClose()
      }
    }
    function handleKey(e) {
      if (e.key === 'Escape') onClose()
    }

    const frame = requestAnimationFrame(() => {
      window.addEventListener('pointerdown', handlePointer, true)
      window.addEventListener('mousedown', handlePointer, true)
      window.addEventListener('touchstart', handlePointer, true)
      window.addEventListener('contextmenu', handlePointer, true)
      window.addEventListener('keydown', handleKey, true)
      window.addEventListener('wheel', onClose, { passive: true, capture: true })
    })

    return () => {
      active = false
      cancelAnimationFrame(frame)
      window.removeEventListener('pointerdown', handlePointer, true)
      window.removeEventListener('mousedown', handlePointer, true)
      window.removeEventListener('touchstart', handlePointer, true)
      window.removeEventListener('contextmenu', handlePointer, true)
      window.removeEventListener('keydown', handleKey, true)
      window.removeEventListener('wheel', onClose, { capture: true })
    }
  }, [onClose])

  function deleteEdge() {
    onEdgesChange([{ id: edgeId, type: 'remove' }])
    onClose()
  }

  return (
    <div
      ref={menuRef}
      className="node-context-menu"
      style={{ left: x, top: y }}
      onClick={(e) => e.stopPropagation()}
    >
      <button className="ctx-danger" onClick={deleteEdge}>
        <span className="ctx-icon">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            <line x1="10" y1="11" x2="10" y2="17" />
            <line x1="14" y1="11" x2="14" y2="17" />
          </svg>
        </span>
        <span className="ctx-label">Delete connection</span>
        <span className="ctx-shortcut">Del</span>
      </button>
    </div>
  )
}

function CanvasInner() {
  const previewVersion = useWorkflowStore((s) => s.previewVersion)
  const exitPreview = useWorkflowStore((s) => s.exitPreview)
  const rollbackVersion = useWorkflowStore((s) => s.rollbackVersion)
  const openHistoryDrawer = useUiStore((s) => s.openHistoryDrawer)
  const historyDrawerOpen = useUiStore((s) => s.historyDrawerOpen)
  const [actionsMenuOpen, setActionsMenuOpen] = useState(false)
  const actionsMenuRef = useRef(null)

  useEffect(() => {
    if (!actionsMenuOpen) return
    const handleClick = (e) => {
      if (actionsMenuRef.current && !actionsMenuRef.current.contains(e.target)) {
        setActionsMenuOpen(false)
      }
    }
    window.addEventListener('pointerdown', handleClick, true)
    window.addEventListener('touchstart', handleClick, true)
    return () => {
      window.removeEventListener('pointerdown', handleClick, true)
      window.removeEventListener('touchstart', handleClick, true)
    }
  }, [actionsMenuOpen])

  const nodes = useWorkflowStore((s) => s.nodes)
  const edges = useWorkflowStore((s) => s.edges)
  const comments = useWorkflowStore((s) => s.comments)
  const groups = useWorkflowStore((s) => s.groups)
  const edgeLabels = useWorkflowStore((s) => s.edgeLabels)
  const onNodesChange = useWorkflowStore((s) => s.onNodesChange)
  const onEdgesChange = useWorkflowStore((s) => s.onEdgesChange)
  const onConnect = useWorkflowStore((s) => s.onConnect)
  const canConnect = useWorkflowStore((s) => s.canConnect)
  const addNode = useWorkflowStore((s) => s.addNode)
  const selectNode = useUiStore((s) => s.selectNode)
  const showMiniMap = useUiStore((s) => s.showMiniMap)
  const toggleMiniMap = useUiStore((s) => s.toggleMiniMap)
  const wrapper = useRef(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [flash, setFlash] = useState(null)
  const [edgeMenu, setEdgeMenu] = useState(null)
  const { getNodes, screenToFlowPosition, fitView, zoomIn, zoomOut } = useReactFlow()
  const workflow = useWorkflowStore((s) => s.workflow)
  const nodeStatuses = useExecutionStore((s) => s.nodeStatuses)
  const running = useExecutionStore((s) => s.running)

  const nodesInitialized = useNodesInitialized()
  const fittedWorkflowId = useRef(null)

  // Reset fitted workflow ID when switching workflows
  useEffect(() => {
    fittedWorkflowId.current = null
  }, [workflow?.id])

  // Automatically fit view as soon as all nodes are initialized & measured in DOM
  useEffect(() => {
    if (!workflow?.id || nodes.length === 0) return
    if (nodesInitialized && fittedWorkflowId.current !== workflow.id) {
      fittedWorkflowId.current = workflow.id
      // Immediate frame fit plus smooth 250ms animation settle
      requestAnimationFrame(() => {
        fitView({ padding: 0.2, duration: 250 })
      })
      const timer = setTimeout(() => {
        fitView({ padding: 0.2, duration: 0 })
      }, 200)
      return () => clearTimeout(timer)
    }
  }, [nodesInitialized, workflow?.id, nodes.length, fitView])

  const previewGraph = useMemo(() => {
    if (!previewVersion?.data) return null
    try {
      return toReactFlow(previewVersion.data)
    } catch {
      return null
    }
  }, [previewVersion])

  const previewDecorations = useMemo(() => {
    if (!previewVersion?.data) return null
    try {
      return readDecorations(previewVersion.data)
    } catch {
      return null
    }
  }, [previewVersion])

  const activeNodes = previewGraph ? previewGraph.nodes : nodes
  const activeEdges = previewGraph ? previewGraph.edges : edges
  const activeComments = previewDecorations ? (previewDecorations.comments || []) : comments
  const activeGroups = previewDecorations ? (previewDecorations.groups || []) : groups
  const activeEdgeLabels = previewDecorations ? (previewDecorations.edgeLabels || {}) : edgeLabels

  const decoratedNodes = useDecoratedNodes(activeNodes, activeComments, activeGroups)
  const displayEdges = useLabeledStatefulEdges(
    activeEdges,
    activeEdgeLabels,
    previewGraph ? {} : nodeStatuses,
    previewGraph ? false : running
  )

  function flashMessage(text) {
    setFlash(text)
    setTimeout(() => setFlash(null), 2200)
  }

  const onDrop = useCallback(
    (e) => {
      e.preventDefault()
      setDragOver(false)
      const type = draggedNodeType(e)
      if (!type) return
      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })
      position.x -= 60
      position.y -= 20
      addNode(type, position)
      useUiStore.getState().closeSidebar()
    },
    [addNode, screenToFlowPosition],
  )

  // ------------------------------------------------------------------
  // keyboard map (Phase 12). Inputs/textareas are exempt so typing in
  // forms never triggers canvas actions.
  // ------------------------------------------------------------------
  useEffect(() => {
    function onKeyDown(e) {
      const tag = e.target?.tagName
      const typing =
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        e.target?.isContentEditable
      const mod = e.ctrlKey || e.metaKey

      // Palette opens even while typing (standard Ctrl+K behaviour).
      if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
        return
      }
      if (typing) return

      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        if (e.shiftKey) useWorkflowStore.getState().redo()
        else useWorkflowStore.getState().undo()
      } else if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        useWorkflowStore.getState().redo()
      } else if (mod && e.key.toLowerCase() === 'c') {
        const selected = useWorkflowStore.getState().nodes.filter((n) => n.selected)
        useWorkflowStore.getState().copySelection(selected.map((n) => n.id))
      } else if (mod && e.key.toLowerCase() === 'x') {
        const selected = useWorkflowStore.getState().nodes.filter((n) => n.selected)
        useWorkflowStore.getState().cutSelection(selected.map((n) => n.id))
      } else if (mod && e.key.toLowerCase() === 'v') {
        useWorkflowStore.getState().paste(null)
      } else if (mod && e.key.toLowerCase() === 'a') {
        e.preventDefault()
        useWorkflowStore.getState().selectAll()
      } else if (mod && e.key.toLowerCase() === 'd') {
        e.preventDefault()
        const selected = getNodes().filter((n) => n.selected)
        if (selected.length) {
          useWorkflowStore.getState().duplicateNodes(selected.map((n) => n.id))
        }
      } else if (mod && (e.key === '0')) {
        e.preventDefault()
        fitView({ duration: 300, padding: 0.15 })
      } else if (mod && e.key === '=') {
        e.preventDefault()
        zoomIn()
      } else if (mod && e.key === '-') {
        e.preventDefault()
        zoomOut()
      } else if (e.key === '?') {
        e.preventDefault()
        setPaletteOpen(true)
      } else if (!mod && e.key.toLowerCase() === 'm') {
        e.preventDefault()
        useUiStore.getState().toggleMiniMap()
      } else if (e.key === 'Escape') {
        useWorkflowStore.getState().clearSelection()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [getNodes, zoomIn, zoomOut, fitView])

  const isEmpty = nodes.length === 0 && comments.length === 0 && groups.length === 0

  const handleConnect = useCallback(
    (c) => {
      if (!canConnect(c)) {
        flashMessage('Connection rejected — a node cannot connect to itself.')
        return
      }
      onConnect(c)
    },
    [canConnect, onConnect],
  )

  const handlePaneClick = useCallback(() => {
    selectNode(null)
    setEdgeMenu(null)
    useUiStore.getState().closeSidebar()
  }, [selectNode])

  const handleEdgeContextMenu = useCallback((e, edge) => {
    e.preventDefault()
    setEdgeMenu({ x: e.clientX, y: e.clientY, edgeId: edge.id })
  }, [])

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback(() => setDragOver(false), [])

  return (
    <div
      className={`canvas ${dragOver ? 'drop-target' : ''} ${previewVersion ? 'canvas--preview-history' : ''}`}
      ref={wrapper}
      onDrop={previewGraph ? undefined : onDrop}
      onDragOver={previewGraph ? undefined : handleDragOver}
      onDragLeave={previewGraph ? undefined : handleDragLeave}
    >
      {/* Top-left pill: Current changes / Viewing Version */}
      <div className="canvas-history-pill-container">
        <button
          type="button"
          className={`canvas-history-pill ${previewVersion ? 'is-preview' : 'is-current'}`}
          onClick={() => {
            if (previewVersion) exitPreview()
            else openHistoryDrawer('versions')
          }}
          title={previewVersion ? "Click to return to current changes" : "View workflow history"}
        >
          <span className={`pill-dot ${previewVersion ? (previewVersion.is_active ? 'dot-active' : 'dot-saved') : 'dot-current'}`} />
          <span>
            {previewVersion
              ? `Viewing Version ${previewVersion.version}${previewVersion.is_active ? ' (Active)' : ''}`
              : 'Current changes'}
          </span>
          {previewVersion && <span className="pill-return-hint">Return</span>}
        </button>
      </div>

      {/* Actions menu: only rendered when previewing a historical version */}
      {previewVersion && (
        <div className={`canvas-actions-container ${historyDrawerOpen ? "with-drawer-open" : ""}`} ref={actionsMenuRef}>
          <button
            type="button"
            className="canvas-actions-btn"
            onClick={() => setActionsMenuOpen(!actionsMenuOpen)}
            aria-haspopup="menu"
            aria-expanded={actionsMenuOpen}
          >
            <span>Actions</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
          {actionsMenuOpen && (
            <div className="canvas-actions-dropdown" role="menu">
              <button
                type="button"
                role="menuitem"
                className="primary-action-item"
                onClick={() => {
                  setActionsMenuOpen(false)
                  if (window.confirm(`Restore workflow to version ${previewVersion.version}? Current unsaved edits will be replaced.`)) {
                    rollbackVersion(workflow.id, previewVersion.version)
                  }
                }}
              >
                Restore this version
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setActionsMenuOpen(false)
                  exitPreview()
                }}
              >
                Back to current changes
              </button>
            </div>
          )}
        </div>
      )}

      {/* Floating preview banner */}
      {previewVersion && (
        <div className="canvas-preview-banner">
          <div className="preview-banner-text">
            <strong>Viewing Version {previewVersion.version}</strong>
            {previewVersion.is_active && <span className="banner-tag">(Active)</span>}
            <span className="banner-sub">Read-only history snapshot</span>
          </div>
          <div className="preview-banner-btns">
            <button
              type="button"
              className="preview-restore-btn"
              onClick={() => {
                if (window.confirm(`Restore workflow to version ${previewVersion.version}? Current unsaved edits will be replaced.`)) {
                  rollbackVersion(workflow.id, previewVersion.version)
                }
              }}
            >
              Restore this version
            </button>
            <button
              type="button"
              className="preview-exit-btn"
              onClick={() => exitPreview()}
            >
              Exit preview
            </button>
          </div>
        </div>
      )}

      <CanvasToolbar />
      {flash && <div className="canvas-flash">{flash}</div>}
      {isEmpty && (
        <div className="canvas-empty">
          <div className="canvas-empty-icon">🗂️</div>
          <h3>Workflow is empty</h3>
          <p>Drag a node from the left palette to start building your workflow.</p>
          <p className="hint">A workflow must contain at least one node.</p>
        </div>
      )}
      <ReactFlow
        nodes={decoratedNodes}
        edges={displayEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        onNodesChange={previewGraph ? undefined : onNodesChange}
        onEdgesChange={previewGraph ? undefined : onEdgesChange}
        onConnect={previewGraph ? undefined : handleConnect}
        nodesDraggable={!previewGraph}
        nodesConnectable={!previewGraph}
        isValidConnection={canConnect}
        onPaneClick={handlePaneClick}
        onEdgeContextMenu={handleEdgeContextMenu}
        connectionLineStyle={{ stroke: '#4f8cff', strokeWidth: 2 }}
        connectionLineType="bezier"
        multiSelectionKeyCode="Shift"
        selectionKeyCode="Shift"
        panOnDrag={[1, 2]}
        zoomOnPinch={true}
        preventScrolling={true}
        deleteKeyCode={['Backspace', 'Delete']}
        minZoom={0.1}
        maxZoom={2.5}
        elevateEdgesOnSelect
        fitView
        fitViewOptions={{ padding: 0.2, includeHiddenNodes: true }}
        onInit={(instance) => setTimeout(() => instance.fitView({ padding: 0.2 }), 50)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={22} size={1.4} />
        {nodes.length === 0 && (
          <div className="canvas-empty-state">
            <div className="canvas-empty-card">
              <FlowsmithBrandMark size={42} variant="badge" glow />
              <h3 className="canvas-empty-title">Build your next flow</h3>
              <p className="canvas-empty-desc">
                Drag nodes from the sidebar, press <kbd className="canvas-kbd">Ctrl</kbd> <kbd className="canvas-kbd">K</kbd>, or start with a trigger below.
              </p>
              <div className="canvas-empty-actions">
                <button
                  type="button"
                  className="primary primary--sm"
                  onClick={() => addNode('webhook', { x: 280, y: 180 })}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 6 }}>
                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                  </svg>
                  Webhook Trigger
                </button>
                <button
                  type="button"
                  className="secondary secondary--sm"
                  onClick={() => addNode('manual_trigger', { x: 280, y: 180 })}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 6 }}>
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  Manual Trigger
                </button>
              </div>
            </div>
          </div>
        )}
        {showMiniMap && (
          <div className="canvas-minimap-wrap" style={{ position: 'absolute', bottom: 16, right: 16, zIndex: 10 }}>
            <MiniMap
              pannable
              zoomable
              nodeColor={(n) => {
                const s = nodeStatuses[n.id]
                if (s === 'success') return '#10b981'
                if (s === 'error' || s === 'failed') return '#f43f5e'
                if (s === 'running') return '#818cf8'
                if (s === 'waiting_approval') return '#f59e0b'
                if (n.data?.disabled) return '#475569'
                return '#6366f1'
              }}
              nodeStrokeColor="rgba(255, 255, 255, 0.25)"
              nodeBorderRadius={4}
              maskColor="rgba(11, 14, 20, 0.72)"
            />
            <button
              type="button"
              onClick={toggleMiniMap}
              title="Hide minimap (M)"
              aria-label="Hide minimap"
              style={{
                position: 'absolute',
                top: 6,
                right: 6,
                width: 20,
                height: 20,
                borderRadius: '50%',
                background: 'rgba(20, 24, 34, 0.85)',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                color: '#cbd5e1',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                zIndex: 15,
                fontSize: 10,
                lineHeight: 1,
              }}
            >
              ✕
            </button>
          </div>
        )}
      </ReactFlow>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      {edgeMenu && (
        <EdgeContextMenu
          x={edgeMenu.x}
          y={edgeMenu.y}
          edgeId={edgeMenu.edgeId}
          onClose={() => setEdgeMenu(null)}
        />
      )}
    </div>
  )
}

export default function Canvas() {
  // ReactFlowProvider lives in App.jsx so the Sidebar shares the viewport.
  return <CanvasInner />
}
