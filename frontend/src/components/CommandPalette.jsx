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
        title: '▶ Run workflow',
        hint: 'Ctrl+Enter',
        enabled: Boolean(workflow?.id),
        perform: () => run(workflow.id),
      },
      { id: 'cmd-save', title: '💾 Save now', hint: 'Ctrl+S', enabled: true, perform: () => save().catch(() => {}) },
      { id: 'cmd-undo', title: '↶ Undo', hint: 'Ctrl+Z', enabled: canUndo, perform: undo },
      { id: 'cmd-redo', title: '↷ Redo', hint: 'Ctrl+Shift+Z', enabled: canRedo, perform: redo },
      {
        id: 'cmd-select-all',
        title: '⬚ Select all nodes',
        hint: 'Ctrl+A',
        enabled: true,
        perform: () => selectAll(),
      },
      {
        id: 'cmd-fit',
        title: '⤢ Zoom to fit',
        hint: 'Ctrl+0',
        enabled: true,
        perform: () => fitView({ duration: 300, padding: 0.15 }),
      },
      {
        id: 'cmd-comment',
        title: '💬 Add comment',
        enabled: true,
        perform: () => useWorkflowStore.getState().addComment({ x: 160, y: 160 }, ''),
      },
      {
        id: 'cmd-group',
        title: '⛁ Group selected nodes',
        hint: 'select 2+, then run',
        enabled: nodes.filter((n) => n.selected).length >= 2,
        perform: () => {
          const store = useWorkflowStore.getState()
          store.groupSelected(store.nodes.filter((n) => n.selected).map((n) => n.id))
        },
      },
      {
        id: 'cmd-layout',
        title: '⌗ Auto-layout',
        enabled: true,
        perform: () => {
          import('../utils/autoLayout').then(({ autoLayout }) => {
            const store = useWorkflowStore.getState()
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
                {item.icon && (
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
          ↑↓ navigate · ⏎ run · esc close
        </footer>
      </div>
    </div>
  )
}
