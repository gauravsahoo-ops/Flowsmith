// GroupNode: visual frame around a set of nodes.
//
// Groups are editor-only decorations (workflow.settings.editor.groups).
// Members remain plain workflow nodes with absolute positions; dragging
// the group moves every member currently inside its bounds.

import { memo, useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'

const GROUP_COLORS = [
  { id: 'blue', label: 'Blue', color: '#3b82f6' },
  { id: 'emerald', label: 'Green', color: '#10b981' },
  { id: 'amber', label: 'Amber', color: '#f59e0b' },
  { id: 'purple', label: 'Purple', color: '#a855f7' },
  { id: 'rose', label: 'Rose', color: '#f43f5e' },
]

function GroupNode({ id, data, selected }) {
  const ungroup = useWorkflowStore((s) => s.ungroup)
  const updateGroup = useWorkflowStore((s) => s.updateGroup)
  const [editing, setEditing] = useState(false)
  const [labelVal, setLabelVal] = useState(data.group.label || 'Group')

  function startMove(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return
    e.stopPropagation()
    const group = data.group
    const startX = e.clientX
    const startY = e.clientY
    const originX = group.x
    const originY = group.y
    const store = useWorkflowStore.getState()

    // Everything geometrically inside the frame travels with it.
    const members = store.nodes.filter(
      (n) =>
        n.position.x >= group.x &&
        n.position.y >= group.y &&
        n.position.x <= group.x + group.width &&
        n.position.y <= group.y + group.height,
    )
    const starts = members.map((n) => ({ id: n.id, x: n.position.x, y: n.position.y }))
    if (!starts.length) return

    function onMove(ev) {
      const dx = ev.clientX - startX
      const dy = ev.clientY - startY
      const s = useWorkflowStore.getState()
      s.updateGroup(id, { x: originX + dx, y: originY + dy })
      s.onNodesChange(
        starts.map((m) => ({
          id: m.id,
          type: 'position',
          position: { x: m.x + dx, y: m.y + dy },
          dragging: true,
        })),
      )
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  function commitLabel() {
    setEditing(false)
    if (labelVal.trim() && labelVal !== data.group.label) {
      updateGroup(id, { label: labelVal.trim() })
    }
  }

  const currentColor = data.group.color || 'blue'

  return (
    <div
      className={`group-node group-${currentColor} ${selected ? 'selected' : ''}`}
      onMouseDown={startMove}
    >
      <div className="group-label" onMouseDown={(e) => e.stopPropagation()}>
        {editing ? (
          <input
            type="text"
            value={labelVal}
            autoFocus
            onChange={(e) => setLabelVal(e.target.value)}
            onBlur={commitLabel}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitLabel()
              if (e.key === 'Escape') setEditing(false)
              e.stopPropagation()
            }}
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              color: '#fff',
              fontSize: 11,
              fontWeight: 700,
              padding: '2px 6px',
              outline: 'none',
            }}
          />
        ) : (
          <span
            onDoubleClick={() => setEditing(true)}
            title="Double-click to rename frame"
            style={{ cursor: 'pointer' }}
          >
            {data.group.label || 'Group Frame'}
          </span>
        )}

        <div style={{ display: 'inline-flex', gap: 3, alignItems: 'center', marginLeft: 4 }}>
          {GROUP_COLORS.map((c) => (
            <button
              key={c.id}
              type="button"
              title={c.label}
              onClick={(e) => {
                e.stopPropagation()
                updateGroup(id, { color: c.id })
              }}
              style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: c.color,
                border: currentColor === c.id ? '1.5px solid #fff' : 'none',
                cursor: 'pointer',
                padding: 0,
              }}
            />
          ))}
        </div>

        <button
          className="group-ungroup"
          title="Remove frame (keeps nodes)"
          onClick={(e) => {
            e.stopPropagation()
            ungroup(id)
          }}
        >
          ✕
        </button>
      </div>
    </div>
  )
}

export default memo(GroupNode)
