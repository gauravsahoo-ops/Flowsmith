// ApprovalsPanel: the human-approval inbox (Phase 32). Lists executions
// paused at a human_approval node (status waiting_approval) and lets an
// authorized user approve or reject. Approve/reject resumes the run; the
// engine replays persisted node outputs, so upstream steps never re-run.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { useExecutionStore } from '../stores/executionStore'

function fmtTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}

export default function ApprovalsPanel({ open, onClose }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busyId, setBusyId] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await api.listExecutions({ status: 'waiting_approval', pageSize: 50 })
      setRows(data || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) refresh()
  }, [open, refresh])

  async function decide(id, approved) {
    setBusyId(id)
    setError(null)
    setNotice(null)
    try {
      await api.resume(id, approved)
      setNotice(approved ? 'Approved — the workflow is resuming.' : 'Rejected — the run will fail.')
      await refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  function inspect(id) {
    useExecutionStore.getState().load(id)
    onClose()
  }

  if (!open) return null

  return (
    <aside className="panel approvals">
      <header>
        <h2>Approvals</h2>
        <button className="ghost" onClick={onClose} title="Close">
          ✕
        </button>
      </header>
      <p className="hint">
        Runs waiting for a human decision.
        <button className="ghost linklike" onClick={refresh} disabled={loading}>
          ↻ Refresh
        </button>
      </p>
      {error && <div className="banner-inline err">{error}</div>}
      {notice && <div className="banner-inline ok">{notice}</div>}
      {!loading && rows.length === 0 && <p className="hint">Nothing waiting. 🎉</p>}
      <div className="approvals-list">
        {rows.map((e) => (
          <div key={e.id} className="approvals-row">
            <button className="approvals-main" onClick={() => inspect(e.id)} title="Open in inspector">
              <span className={`dot status-waiting_approval`} />
              <span className="history-name">{e.workflow_name || e.workflow_id.slice(0, 8)}</span>
              <span className="approvals-message">{e.pause_state?.message || 'Waiting for approval'}</span>
              <span className="history-time">{fmtTime(e.started_at)}</span>
            </button>
            <div className="approvals-actions">
              <button
                className="primary"
                disabled={busyId === e.id}
                onClick={() => decide(e.id, true)}
              >
                ✓ Approve
              </button>
              <button
                className="danger"
                disabled={busyId === e.id}
                onClick={() => decide(e.id, false)}
              >
                ✕ Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}
