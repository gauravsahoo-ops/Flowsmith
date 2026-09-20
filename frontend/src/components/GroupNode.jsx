// GroupNode: visual frame around a set of nodes.
//
// Groups are editor-only decorations (workflow.settings.editor.groups).
// Members remain plain workflow nodes with absolute positions; dragging
// the group moves every member currently inside its bounds.

import { memo, useState } from 'react'
import { useViewport } from '@xyflow/react'
import { useWorkflowStore } from '../stores/workflowStore'

const GROUP_COLORS = [
  { id: 'blue', label: 'Blue', color: '#3b82f6' },
  { id: 'emerald', label: 'Green', color: '#10b981' },
  { id: 'amber', label: 'Amber', color: '#f59e0b' },
  { id: 'purple', label: 'Purple', color: '#a855f7' },
  { id: 'rose', label: 'Rose', color: '#f43f5e' },
]

function GroupNode({ id, data, selected }) {
  const { zoom = 1 } = useViewport()
  const ungroup = useWorkflowStore((s) => s.ungroup)
  const updateGroup = useWorkflowStore((s) => s.updateGroup)
  const [editing, setEditing] = useState(false)
  const [labelVal, setLabelVal] = useState(data.group.label || 'Group')

  function startMove(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON' || e.target.classList.contains('group-resize-handle')) return
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

    function onMove(ev) {
      const dx = (ev.clientX - startX) / (zoom || 1)
      const dy = (ev.clientY - startY) / (zoom || 1)
      const s = useWorkflowStore.getState()
      s.updateGroup(id, { x: Math.round(originX + dx), y: Math.round(originY + dy) })
      if (starts.length) {
        s.onNodesChange(
          starts.map((m) => ({
            id: m.id,
            type: 'position',
            position: { x: Math.round(m.x + dx), y: Math.round(m.y + dy) },
            dragging: true,
          })),
        )
      }
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      if (starts.length) {
        const s = useWorkflowStore.getState()
        s.onNodesChange(
          starts.map((m) => ({
            id: m.id,
            type: 'position',
            dragging: false,
          })),
        )
      }
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  function startResize(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return
    e.stopPropagation()
    e.preventDefault()
    const group = data.group
    const startX = e.clientX
    const startY = e.clientY
    const originW = group.width || 260
    const originH = group.height || 160

    function onResizing(ev) {
      const dx = (ev.clientX - startX) / (zoom || 1)
      const dy = (ev.clientY - startY) / (zoom || 1)
      const newW = Math.max(160, Math.round(originW + dx))
      const newH = Math.max(120, Math.round(originH + dy))
      updateGroup(id, { width: newW, height: newH })
    }

    function onStopResize() {
      window.removeEventListener('mousemove', onResizing)
      window.removeEventListener('mouseup', onStopResize)
    }

    window.addEventListener('mousemove', onResizing)
    window.addEventListener('mouseup', onStopResize)
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

      <div
        className="group-resize-handle"
        onMouseDown={startResize}
        title="Drag to resize frame"
      />
    </div>
  )
}

export default memo(GroupNode)
