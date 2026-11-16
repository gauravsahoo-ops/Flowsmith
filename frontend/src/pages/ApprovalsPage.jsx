import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ToolApprovalInbox from '../features/approvals/ToolApprovalInbox'

function fmt(iso) { return iso ? new Date(iso).toLocaleString() : '—' }

function RunPauseInbox({ navigate }) {
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
    <>
      <div className="exec-filter-bar" style={{ marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Workflow runs paused at a human-approval node or a gated agent tool call.
        </span>
        <button
          type="button"
          className="ghost small"
          onClick={refresh}
          disabled={loading}
          style={{ marginLeft: 'auto' }}
        >
          ↻ Refresh run pauses
        </button>
      </div>

      {error && <div className="banner-inline err">{error}</div>}
      {notice && <div className="banner-inline ok">{notice}</div>}

      {loading ? (
        <LoadingSkeleton rows={4} />
      ) : rows.length === 0 ? (
        <>
          <EmptyState
            icon="approvals"
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
              Add an <strong>Approval</strong> node to any workflow before critical steps (such as sending emails, deleting records, or updating customer data in Salesforce). The execution pauses safely in <code>waiting_approval</code> state and notifies you here with the payload to review, approve, or reject.
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
                <button className="primary small" disabled={busyId === e.id} onClick={() => decide(e.id, true)} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  Approve
                </button>
                <button className="danger small" disabled={busyId === e.id} onClick={() => decide(e.id, false)} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                  Reject
                </button>
                <button className="ghost small" onClick={() => navigate(`/executions/${e.id}`)}>Trace run →</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

export default function ApprovalsPage() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('run-pauses')

  return (
    <div className="page approvals-page">
      <PageHeader
        title="Approvals"
        description="Review workflow runs paused at an approval node and durable tool-level requests from the approval broker."
      />

      <div className="tabs" role="tablist" aria-label="Approval inbox" style={{ marginBottom: 16 }}>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'run-pauses'}
          className={activeTab === 'run-pauses' ? 'active' : ''}
          onClick={() => setActiveTab('run-pauses')}
        >
          Run pauses
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'tool-approvals'}
          className={activeTab === 'tool-approvals' ? 'active' : ''}
          onClick={() => setActiveTab('tool-approvals')}
        >
          Tool approvals
        </button>
      </div>

      {activeTab === 'run-pauses' ? <RunPauseInbox navigate={navigate} /> : <ToolApprovalInbox />}
    </div>
  )
}
