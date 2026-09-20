// CommentNode (Phase 12): editor-only sticky note.
//
// Comments are NOT workflow nodes — they live in
// workflow.settings.editor.comments and are rehydrated as ephemeral
// canvas nodes by Canvas.jsx, so the backend never sees them.

import { memo, useEffect, useRef, useState } from 'react'
import { useViewport } from '@xyflow/react'
import { useWorkflowStore } from '../stores/workflowStore'

const NOTE_COLORS = [
  { id: 'amber', label: 'Amber', color: '#f59e0b' },
  { id: 'blue', label: 'Blue', color: '#3b82f6' },
  { id: 'green', label: 'Green', color: '#10b981' },
  { id: 'purple', label: 'Purple', color: '#a855f7' },
  { id: 'rose', label: 'Rose', color: '#f43f5e' },
]

function CommentNode({ id, data }) {
  const { zoom = 1 } = useViewport()
  const updateComment = useWorkflowStore((s) => s.updateComment)
  const deleteComment = useWorkflowStore((s) => s.deleteComment)
  const [editing, setEditing] = useState(!data.comment.text)
  const areaRef = useRef(null)

  useEffect(() => {
    if (editing && areaRef.current) {
      areaRef.current.focus()
      areaRef.current.selectionStart = areaRef.current.value.length
    }
  }, [editing])

  function commit(text) {
    setEditing(false)
    if (!text.trim()) {
      // Empty comments clean themselves up.
      deleteComment(id)
    } else if (text !== data.comment.text) {
      updateComment(id, { text })
    }
  }

  function startResize(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return
    e.stopPropagation()
    e.preventDefault()
    const comment = data.comment
    const startX = e.clientX
    const startY = e.clientY
    const originW = comment.width || 220
    const originH = comment.height || 90

    function onResizing(ev) {
      const dx = (ev.clientX - startX) / (zoom || 1)
      const dy = (ev.clientY - startY) / (zoom || 1)
      const newW = Math.max(140, Math.round(originW + dx))
      const newH = Math.max(60, Math.round(originH + dy))
      updateComment(id, { width: newW, height: newH })
    }

    function onStopResize() {
      window.removeEventListener('mousemove', onResizing)
      window.removeEventListener('mouseup', onStopResize)
    }

    window.addEventListener('mousemove', onResizing)
    window.addEventListener('mouseup', onStopResize)
  }

  const currentColor = data.comment.color || 'amber'

  return (
    <div
      className={`comment-node comment-${currentColor}`}
      onDoubleClick={(e) => {
        e.stopPropagation()
        setEditing(true)
      }}
    >
      <div className="comment-toolbar nodrag nopan">
        <div className="comment-colors">
          {NOTE_COLORS.map((c) => (
            <button
              key={c.id}
              type="button"
              className="comment-color-dot"
              title={c.label}
              onClick={(e) => {
                e.stopPropagation()
                updateComment(id, { color: c.id })
              }}
              style={{
                background: c.color,
                border: currentColor === c.id ? '1.5px solid #fff' : 'none',
              }}
            />
          ))}
        </div>
        <button
          className="comment-delete"
          title="Delete note"
          onClick={(e) => {
            e.stopPropagation()
            deleteComment(id)
          }}
        >
          ×
        </button>
      </div>

      {editing ? (
        <textarea
          ref={areaRef}
          className="nodrag nopan"
          defaultValue={data.comment.text}
          onBlur={(e) => commit(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') commit(e.currentTarget.value)
            e.stopPropagation()
          }}
          placeholder="Leave a note…"
        />
      ) : (
        <div className="comment-text" title="Double-click to edit note">
          {data.comment.text}
        </div>
      )}

      <div
        className="group-resize-handle nodrag nopan"
        onMouseDown={startResize}
        title="Drag to resize note"
      />
    </div>
  )
}

export default memo(CommentNode)
