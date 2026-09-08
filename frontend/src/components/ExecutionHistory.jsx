// ExecutionHistory: past executions list (M8). Clicking a row loads the
// execution into the inspector (per-node I/O, retry, live updates if the
// run is still going). Optionally filtered to the current workflow.

import { useEffect } from 'react'
import { useExecutionStore } from '../stores/executionStore'
import { useWorkflowStore } from '../stores/workflowStore'

const STATUS_LABEL = {
  running: 'running…',
  queued: 'queued…',
  success: 'success',
  failed: 'failed',
  cancelled: 'cancelled',
  waiting_approval: 'waiting approval',
}

function fmtDuration(startedAt, finishedAt) {
  if (!startedAt) return ''
  const ms = finishedAt ? new Date(finishedAt) - new Date(startedAt) : Date.now() - new Date(startedAt)
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

export default function ExecutionHistory({ open, onClose }) {
  const history = useExecutionStore((s) => s.history)
  const meta = useExecutionStore((s) => s.historyMeta)
  const loading = useExecutionStore((s) => s.historyLoading)
  const error = useExecutionStore((s) => s.historyError)
  const fetchHistory = useExecutionStore((s) => s.fetchHistory)
  const load = useExecutionStore((s) => s.load)
  const currentWorkflowId = useWorkflowStore((s) => s.workflow?.id)

  const filtered = currentWorkflowId ? history.filter((h) => h.workflow_id === currentWorkflowId) : history

  useEffect(() => {
    if (open) fetchHistory()
  }, [open, fetchHistory])

  if (!open) return null

  return (
    <aside className="panel history">
      <header>
        <h2>Executions</h2>
        <button className="ghost" onClick={onClose} title="Close">
          ✕
        </button>
      </header>
      <p className="hint">
        {currentWorkflowId
          ? 'Showing runs of this workflow.'
          : 'Showing all runs you can access.'}
        <button className="ghost linklike" onClick={() => fetchHistory({ page: 1 })} disabled={loading}>
          ↻ Refresh
        </button>
      </p>
      {error && <div className="banner-inline err">{error}</div>}
      {!loading && filtered.length === 0 && <p className="hint">No executions yet. Press ▶ Run.</p>}
      <div className="history-list">
        {filtered.map((h) => (
          <button
            key={h.id}
            className={`history-row status-${h.status}`}
            onClick={() => load(h.id)}
            title={`${h.workflow_name} — ${h.id}`}
          >
            <span className="history-name">
              <span className={`dot status-${h.status}`} />
              {h.workflow_name || h.workflow_id.slice(0, 8)}
            </span>
            <span className="history-trigger">{h.trigger}</span>
            <span className={`status-label status-${h.status}`}>{STATUS_LABEL[h.status] || h.status}</span>
            <span className="history-time">{fmtTime(h.started_at)}</span>
            <span className="history-duration">{fmtDuration(h.started_at, h.finished_at)}</span>
            <span className="muted">v{h.workflow_version}</span>
          </button>
        ))}
      </div>
      {meta.total > meta.page * meta.pageSize && (
        <button
          className="ghost more-button"
          disabled={loading}
          onClick={() => fetchHistory({ page: meta.page + 1 })}
        >
          Load more…
        </button>
      )}
    </aside>
  )
}
