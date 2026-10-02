import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'

function fmt(iso) { return iso ? new Date(iso).toLocaleString() : '—' }

export default function ApprovalsPage() {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busyId, setBusyId] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true); setError(null)
    try { const { data } = await api.listExecutions({ status: 'waiting_approval', pageSize: 50 }); setRows(data || []) } catch(e){ setError(e.message)} finally{ setLoading(false)}
  }, [])

  useEffect(() => { refresh() }, [refresh])

  async function decide(id, approved) {
    setBusyId(id); setError(null); setNotice(null)
    try { await api.resume(id, approved); setNotice(approved ? 'Approved — resuming.' : 'Rejected — failing the run.'); await refresh() } catch(e){ setError(e.message)} finally{ setBusyId(null)}
  }

  return (
    <div className="page approvals-page">
      <PageHeader
        title="Approvals"
        description="Workflows paused at an approval step awaiting human review. Approve or reject to resume execution."
        actions={<button className="ghost" onClick={refresh} disabled={loading}>↻ Refresh</button>}
      />

      {error && <div className="banner-inline err">{error}</div>}
      {notice && <div className="banner-inline ok">{notice}</div>}

      {loading ? (
        <LoadingSkeleton rows={4} />
      ) : rows.length === 0 ? (
        <>
          <EmptyState
            icon="✅"
            title="Nothing waiting for approval"
            description="There are currently no workflow executions paused for review. When a workflow reaches a human approval node, it will appear here."
            action={<button className="primary" onClick={() => navigate('/executions')}>View Executions</button>}
            secondaryAction={<button className="ghost" onClick={() => navigate('/workflows')}>Go to Workflows</button>}
          />
          <div className="help-card" style={{ maxWidth: 680, margin: '20px auto', padding: '16px 20px', background: 'rgba(22, 27, 38, 0.5)', border: '1px solid rgba(255, 255, 255, 0.07)', borderRadius: 12 }}>
            <h4 style={{ margin: '0 0 6px', fontSize: 13, color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: 6 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#94a3b8' }}><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
              <span>How Human Approvals Work</span>
            </h4>
            <p className="hint" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.55 }}>
              Add an <strong>Approval</strong> node to any workflow before critical steps (such as sending emails, deleting records, or updating customer data in Salesforce). The execution pauses safely in <code>waiting_approval</code> state and notifies you here with the payload to inspect, approve, or reject.
            </p>
          </div>
        </>
      ) : (
        <div className="approvals-grid">
          {rows.map(e => (
            <div key={e.id} className="approval-card">
              <div className="approval-card-head">
                <span className="dot status-waiting_approval" />
                <strong style={{ fontSize: 14 }}>{e.workflow_name || (e.workflow_id ? e.workflow_id.slice(0, 8) : 'Workflow')}</strong>
                <span className="hint" style={{ marginLeft: 'auto', fontSize: 11 }}>{fmt(e.started_at)}</span>
              </div>
              <div style={{ color: '#cbd5e1', fontSize: 13, margin: '10px 0', background: 'rgba(255,255,255,0.03)', padding: '10px 12px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)' }}>
                {e.pause_state?.message || 'Waiting for approval decision'}
              </div>
              <div className="hint" style={{ fontSize: 11.5, marginBottom: 14, display: 'flex', gap: 8, alignItems: 'center' }}>
                <code className="exec-id-cell">{e.id}</code>
                {e.pause_state?.node_id && <span>· Node: {e.pause_state.node_id}</span>}
              </div>
              <div className="approvals-actions">
                <button className="primary small" disabled={busyId === e.id} onClick={() => decide(e.id, true)}>✓ Approve</button>
                <button className="danger small" disabled={busyId === e.id} onClick={() => decide(e.id, false)}>✕ Reject</button>
                <button className="ghost small" onClick={() => navigate(`/executions/${e.id}`)}>Inspect trace →</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
