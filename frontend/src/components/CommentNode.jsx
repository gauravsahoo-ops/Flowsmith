// CommentNode (Phase 12): editor-only sticky note.
//
// Comments are NOT workflow nodes — they live in
// workflow.settings.editor.comments and are rehydrated as ephemeral
// canvas nodes by Canvas.jsx, so the backend never sees them.

import { memo, useEffect, useRef, useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'

function CommentNode({ id, data }) {
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

  const color = data.comment.color || 'amber'

  return (
    <div
      className={`comment-node comment-${color}`}
      onDoubleClick={(e) => {
        e.stopPropagation()
        setEditing(true)
      }}
    >
      {editing ? (
        <textarea
          ref={areaRef}
          defaultValue={data.comment.text}
          onBlur={(e) => commit(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') commit(e.currentTarget.value)
            e.stopPropagation()
          }}
          placeholder="Leave a note…"
        />
      ) : (
        <div className="comment-text">{data.comment.text}</div>
      )}
      <button
        className="comment-delete"
        title="Delete comment"
        onClick={(e) => {
          e.stopPropagation()
          deleteComment(id)
        }}
      >
        ×
      </button>
    </div>
  )
}

export default memo(CommentNode)
