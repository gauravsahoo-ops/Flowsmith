// CommandPalette (Phase 12): Ctrl+K launcher.
//
// One input, three result kinds, scored by a tiny fuzzy matcher:
//   - commands (run/save/undo/layout/toggle…),
//   - node types from the catalog ("add HTTP Request"),
//   - nodes already on the canvas ("go to <node>").
//
// Own design language: centered modal, keyboard-first, no icon soup.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useReactFlow } from '@xyflow/react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useExecutionStore } from '../stores/executionStore'
import { useUiStore } from '../stores/uiStore'
import { NodeIcon } from './NodeIcons'
import { fuzzyScore } from '../utils/fuzzy'

export default function CommandPalette({ open, onClose }) {
  const catalog = useWorkflowStore((s) => s.catalog)
  const nodes = useWorkflowStore((s) => s.nodes)
  const addNode = useWorkflowStore((s) => s.addNode)
  const undo = useWorkflowStore((s) => s.undo)
  const redo = useWorkflowStore((s) => s.redo)
  const canUndo = useWorkflowStore((s) => s.canUndo)
  const canRedo = useWorkflowStore((s) => s.canRedo)
  const save = useWorkflowStore((s) => s.save)
  const selectAll = useWorkflowStore((s) => s.selectAll)
  const { fitView, screenToFlowPosition } = useReactFlow()
  const run = useExecutionStore((s) => s.run)
  const workflow = useWorkflowStore((s) => s.workflow)

  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      setTimeout(() => inputRef.current?.focus(), 20)
    }
  }, [open])

  const items = useMemo(() => {
    if (!open) return []
    const results = []

    const commands = [
      {
        id: 'cmd-run',
        title: 'Run workflow',
        svgIcon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3" /></svg>,
        hint: 'Ctrl+Enter',
        enabled: Boolean(workflow?.id),
        perform: () => run(workflow.id),
      },
      {
        id: 'cmd-save',
        title: 'Save workflow',
        svgIcon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" /><polyline points="17 21 17 13 7 13 7 21" /><polyline points="7 3 7 8 15 8" /></svg>,
        hint: 'Ctrl+S',
        enabled: true,
        perform: () => save().catch(() => {}),
      },
      {
        id: 'cmd-undo',
        title: 'Undo',
        svgIcon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" /></svg>,
        hint: 'Ctrl+Z',
        enabled: canUndo,
        perform: undo,
      },
      {
        id: 'cmd-redo',
        title: 'Redo',
        svgIcon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>,
        hint: 'Ctrl+Shift+Z',
        enabled: canRedo,
        perform: redo,
      },
      {
        id: 'cmd-select-all',
        title: 'Select all nodes',
        svgIcon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2" strokeDasharray="3 3" /></svg>,
        hint: 'Ctrl+A',
        enabled: true,
        perform: () => selectAll(),
      },
      {
        id: 'cmd-fit',
        title: 'Zoom to fit',
        svgIcon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" /><line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" /></svg>,
        hint: 'Ctrl+0',
        enabled: true,
        perform: () => fitView({ duration: 300, padding: 0.15, maxZoom: 1 }),
      },
      {
        id: 'cmd-comment',
        title: 'Add sticky note / comment',
        svgIcon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>,
        enabled: true,
        perform: () => {
          let at = { x: 160, y: 160 }
          if (typeof screenToFlowPosition === 'function') {
            const center = screenToFlowPosition({
              x: window.innerWidth / 2 - 110,
              y: window.innerHeight / 2 - 45,
            })
            if (Number.isFinite(center.x) && Number.isFinite(center.y)) {
              at = { x: Math.round(center.x), y: Math.round(center.y) }
            }
          }
          useWorkflowStore.getState().addComment(at, '')
        },
      },
      {
        id: 'cmd-group',
        title: 'Group selected nodes',
        svgIcon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /></svg>,
        hint: 'select 2+, then run',
        enabled: nodes.filter((n) => n.selected).length >= 2,
        perform: () => {
          const store = useWorkflowStore.getState()
          store.groupSelected(store.nodes.filter((n) => n.selected).map((n) => n.id))
        },
      },
      {
        id: 'cmd-layout',
        title: 'Auto-layout DAG',
        svgIcon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="15" y="3" width="6" height="6" rx="1" /><rect x="9" y="15" width="6" height="6" rx="1" /><line x1="6" y1="9" x2="12" y2="15" /><line x1="18" y1="9" x2="12" y2="15" /></svg>,
        enabled: true,
        perform: () => {
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
        },
      },
    ]
    for (const c of commands) {
      const s = fuzzyScore(query, c.title)
      if (s >= 0) results.push({ ...c, kind: 'command', score: s + 5 })
    }

    // Add-node entries land in the middle of the current viewport.
    const center = (() => {
      try {
        const rect = document.querySelector('.canvas')?.getBoundingClientRect()
        if (!rect) return { x: 120, y: 120 }
        return screenToFlowPosition({
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
        })
      } catch {
        return { x: 120, y: 120 }
      }
    })()
    for (const meta of catalog) {
      const title = `Add ${meta.display_name}`
      const s = fuzzyScore(query, `${title} ${meta.type} ${meta.category || ''}`)
      if (s >= 0 && !title.includes('Add TEMPLATE')) {
        results.push({
          id: `add-${meta.type}`,
          kind: 'add',
          title,
          hint: meta.category,
          type: meta.type,
          icon: meta.icon,
          score: s,
          perform: () => addNode(meta.type, { x: center.x - 80, y: center.y - 24 }),
        })
      }
    }

    for (const n of nodes.filter((x) => x.type === 'custom')) {
      const label =
        n.data?.node?.settings?.label || n.data?.node?.type || n.id
      const title = `Go to “${label}” (${n.id})`
      const s = fuzzyScore(query, title)
      if (s >= 0) {
        results.push({
          id: `go-${n.id}`,
          kind: 'goto',
          title,
          score: s - 1, // slightly below adds when ambiguous
          perform: () => {
            useWorkflowStore.setState({
              nodes: useWorkflowStore.getState().nodes.map((x) => ({
                ...x,
                selected: x.id === n.id,
              })),
            })
            useUiStore.getState().selectNode(n.id)
            fitView({ nodes: [{ id: n.id }], duration: 350, maxZoom: 1.4, padding: 4 })
          },
        })
      }
    }

    return results.sort((a, b) => b.score - a.score).slice(0, 12)
  }, [
    open, query, catalog, nodes, workflow, run, save, canUndo, canRedo,
    undo, redo, selectAll, fitView, screenToFlowPosition, addNode,
  ])

  function choose(item) {
    onClose()
    // Let the modal unmount before actions that open popups.
    setTimeout(() => item.perform(), 10)
  }

  if (!open) return null

  return (
    <div className="palette-overlay" onMouseDown={onClose}>
      <div className="palette" onMouseDown={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="palette-input"
          placeholder="Type a command or search nodes…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setActive(0)
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setActive((i) => Math.min(i + 1, items.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setActive((i) => Math.max(i - 1, 0))
            } else if (e.key === 'Enter' && items[active]) {
              e.preventDefault()
              choose(items[active])
            } else if (e.key === 'Escape') {
              onClose()
            }
            e.stopPropagation()
          }}
        />
        <ul className="palette-list">
          {items.map((item, i) => (
            <li key={item.id}>
              <button
                type="button"
                className={`palette-item ${i === active ? 'active' : ''}`}
                disabled={item.enabled === false}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(item)}
              >
                {item.svgIcon ? (
                  <span className="node-icon" style={{ display: 'inline-flex', alignItems: 'center', opacity: 0.8, color: '#94a3b8' }}>
                    {item.svgIcon}
                  </span>
                ) : item.icon && (
                  <span className="node-icon">
                    <NodeIcon type={item.type} icon={item.icon} size={16} />
                  </span>
                )}
                <span className="palette-title">{item.title}</span>
                {item.hint && <span className="muted">{item.hint}</span>}
                {item.kind && (
                  <span className={`palette-kind kind-${item.kind}`}>{item.kind}</span>
                )}
              </button>
            </li>
          ))}
          {!items.length && (
            <li className="hint palette-empty">Nothing matches “{query}”.</li>
          )}
        </ul>
        <footer className="palette-foot hint">
          ↑↓ navigate · Enter run · Esc close
        </footer>
      </div>
    </div>
  )
}
