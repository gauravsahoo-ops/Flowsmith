import { useEffect, useState, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import WorkspaceTabs from '../components/shared/WorkspaceTabs'

const STATUS_OPTS = ['', 'success', 'failed', 'running', 'queued', 'cancelled', 'waiting_approval']
const STATUS_LABEL = { running: 'running…', queued: 'queued…', success: 'success', failed: 'failed', cancelled: 'cancelled', waiting_approval: 'waiting approval' }

function fmtTime(iso) { return iso ? new Date(iso).toLocaleString() : '—' }
function fmtDur(s, f) {
  if (!s) return '—'
  const ms = f ? new Date(f) - new Date(s) : Date.now() - new Date(s)
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms/1000).toFixed(1)}s`
}

export default function ExecutionsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [execs, setExecs] = useState([])
  const [meta, setMeta] = useState({ page: 1, pageSize: 25, total: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(params.get('status') || '')
  const [workflowId, setWorkflowId] = useState(params.get('workflow_id') || '')
  const [workflows, setWorkflows] = useState([])

  const page = Number(params.get('page') || 1)

  const load = useCallback(async (p = page, silent = false) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      const { data, meta: m } = await api.listExecutions({ workflowId: workflowId || undefined, status: status || undefined, page: p, pageSize: 25 })
      setExecs(data || []); if (m) setMeta(m)
    } catch (e) {
      if (!silent) setError(e.message)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [workflowId, status, page])

  useEffect(() => { load() }, [load])
  useEffect(() => { api.listWorkflows().then(d => setWorkflows(Array.isArray(d) ? d : [])).catch(()=>{}) }, [])

  // Auto-poll every 2s while any execution is running or queued
  useEffect(() => {
    const hasActive = execs.some(e => ['running', 'queued', 'waiting_approval'].includes(e.status))
    if (!hasActive) return

    const timer = setInterval(() => {
      load(page, true)
    }, 2000)

    return () => clearInterval(timer)
  }, [execs, load, page])

  function updateFilters(nextStatus, nextWf, nextPage = 1) {
    const q = new URLSearchParams()
    if (nextStatus) q.set('status', nextStatus)
    if (nextWf) q.set('workflow_id', nextWf)
    if (nextPage > 1) q.set('page', String(nextPage))
    setParams(q, { replace: true })
    setStatus(nextStatus); setWorkflowId(nextWf)
  }

  return (
    <div className="page executions-page">
      <PageHeader title="Executions" description="History of workflow runs. Click any execution to inspect its debug trace." actions={<button className="ghost" onClick={() => load(1)}>↻ Refresh</button>} />
      <WorkspaceTabs />

      <div className="exec-filter-bar">
        <div className="exec-status-chips">
          {[
            { id: '', label: 'All Executions' },
            { id: 'running', label: 'Running', dotColor: '#38bdf8' },
            { id: 'success', label: 'Success', dotColor: '#10b981' },
            { id: 'failed', label: 'Failed', dotColor: '#f43f5e' },
            { id: 'queued', label: 'Queued', dotColor: '#f59e0b' },
            { id: 'waiting_approval', label: 'Approval', dotColor: '#a855f7' },
          ].map(chip => (
            <button
              key={chip.id}
              type="button"
              className={`exec-status-chip ${status === chip.id ? 'is-active' : ''}`}
              onClick={() => updateFilters(chip.id, workflowId)}
            >
              {chip.dotColor && (
                <span className="chip-dot" style={{ background: chip.dotColor, boxShadow: `0 0 6px ${chip.dotColor}` }} />
              )}
              <span>{chip.label}</span>
            </button>
          ))}
        </div>

        <div className="toolbar" style={{ margin: 0, padding: 0, background: 'transparent', border: 'none' }}>
          <select value={workflowId} onChange={e => updateFilters(status, e.target.value)} aria-label="Filter by workflow">
            <option value="">All workflows</option>
            {workflows.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <select value={status} onChange={e => updateFilters(e.target.value, workflowId)} aria-label="Filter by status">
            <option value="">All statuses</option>
            {STATUS_OPTS.filter(Boolean).map(s => <option key={s} value={s}>{STATUS_LABEL[s] || s}</option>)}
          </select>
          <span className="hint">{meta.total} total</span>
        </div>
      </div>

      {error && <div className="banner-inline err">{error}</div>}

      {loading ? <LoadingSkeleton rows={8} /> : execs.length === 0 ? (
        status || workflowId ? (
          <EmptyState
            icon="search"
            title="No matching executions"
            description="No execution records match the selected status or workflow filter."
            action={<button className="ghost" onClick={() => updateFilters('', '')}>Clear filters</button>}
          />
        ) : (
          <EmptyState
            icon="executions"
            badge="Telemetry Active"
            title="No workflow executions yet"
            description="When your workflows run via manual trigger, webhook, cron schedule, or API call, their step traces appear here."
            guidance="Executions track millisecond step durations, payloads, retries, and full debug error stacks."
            highlights={[
              {
                icon: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                ),
                title: 'Live Run Tracing',
                desc: 'Inspect in-flight and completed runs with per-node input/output inspection.',
              },
              {
                icon: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                ),
                title: 'Instant Replay',
                desc: 'Re-execute failed runs with modified parameters or auto-repair diagnostics.',
              },
              {
                icon: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                ),
                title: 'Audit & Compliance',
                desc: 'Immutable cryptographic execution logs with actor attribution.',
              },
            ]}
            action={<button className="primary" onClick={() => navigate('/workflows')}>Go to workflows to run</button>}
            secondaryAction={<button className="ghost" onClick={() => navigate('/monitoring')}>View system health</button>}
          />
        )
      ) : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Execution</th>
                  <th>Workflow</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Duration</th>
                  <th>Trigger</th>
                  <th style={{ textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {execs.map(e => (
                  <tr key={e.id} className="clickable" onClick={() => navigate(`/executions/${e.id}`)} tabIndex={0} onKeyDown={ev => { if (ev.key === 'Enter') navigate(`/executions/${e.id}`)}}>
                    <td>
                      <code className="exec-id-cell" title={e.id}>
                        {e.id.length > 14 ? `${e.id.slice(0, 12)}…` : e.id}
                      </code>
                    </td>
                    <td className="wf-name-cell">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                        <span style={{ color: '#818cf8', display: 'inline-flex', flexShrink: 0 }}>
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" fillOpacity="0.2" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                        </span>
                        <strong style={{ fontWeight: 600, color: '#f1f5f9' }}>
                          {e.workflow_name || (e.workflow_id ? e.workflow_id.slice(0, 8) : '—')}
                        </strong>
                      </div>
                    </td>
                    <td><span className={`status-label status-${e.status}`}>{STATUS_LABEL[e.status] || e.status}</span></td>
                    <td className="muted" style={{ fontSize: 12 }}>{fmtTime(e.started_at)}</td>
                    <td>
                      <span className="exec-dur-badge">
                        {fmtDur(e.started_at, e.finished_at)}
                      </span>
                    </td>
                    <td className="muted trigger-cell">
                      <span className="exec-trigger-pill">
                        {e.trigger || 'manual'}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <span className="exec-inspect-btn">
                        Trace →
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button className="ghost" disabled={meta.page <= 1 || loading} onClick={() => { const q = new URLSearchParams(params); q.set('page', String(meta.page - 1)); setParams(q); }}>← Prev</button>
            <span className="hint">Page {meta.page} · {meta.total} total</span>
            <button className="ghost" disabled={meta.page * meta.pageSize >= meta.total || loading} onClick={() => { const q = new URLSearchParams(params); q.set('page', String(meta.page + 1)); setParams(q); }}>Next →</button>
          </div>
        </>
      )}
    </div>
  )
}
