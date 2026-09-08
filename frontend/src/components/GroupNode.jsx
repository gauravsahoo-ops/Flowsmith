// GroupNode (Phase 12): visual frame around a set of nodes.
//
// Groups are editor-only decorations (workflow.settings.editor.groups).
// Members remain plain workflow nodes with absolute positions; dragging
// the group moves every member currently inside its bounds.

import { memo } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'

function GroupNode({ id, data, selected }) {
  const ungroup = useWorkflowStore((s) => s.ungroup)
  const updateGroup = useWorkflowStore((s) => s.updateGroup)

  function startMove(e) {
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
      const byId = new Map(s.nodes.map((n) => [n.id, n]))
      s.onNodesChange(
        starts.map((m) => ({
          id: m.id,
          type: 'position',
          position: { x: m.x + dx, y: m.y + dy },
          dragging: true,
        })),
      )
      void byId
    }
    function onUp() {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <div
      className={`group-node group-${data.group.color || 'blue'} ${selected ? 'selected' : ''}`}
      onMouseDown={startMove}
      onDoubleClick={(e) => {
        e.stopPropagation()
        const label = window.prompt('Group name:', data.group.label)
        if (label != null) updateGroup(id, { label })
      }}
    >
      <div className="group-label">
        <span>{data.group.label}</span>
        <button
          className="group-ungroup"
          title="Ungroup (keeps the nodes)"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation()
            ungroup(id)
          }}
        >
          ⊘
        </button>
      </div>
    </div>
  )
}

export default memo(GroupNode)
