import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ExecutionTimeline from '../components/ExecutionTimeline'
import StepDetail from '../components/StepDetail'

const STATUS_LABEL = { success: 'success', failed: 'failed', cancelled: 'cancelled', running: 'running…', queued: 'queued…', waiting_approval: 'waiting approval' }

export default function ExecutionDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('timeline')
  const [selected, setSelected] = useState(null)
  const [explain, setExplain] = useState(null)
  const [explaining, setExplaining] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    api.getExecution(id).then(d => { if (alive) { setData(d); if (d.trace?.length) setSelected(d.trace[0].node_id) } }).catch(e => { if (alive) setError(e.message) }).finally(()=> { if(alive) setLoading(false)})
    return () => { alive = false }
  }, [id])

  // Live auto-poll while running or queued
  useEffect(() => {
    if (!data) return
    const isActive = ['running', 'queued', 'waiting_approval'].includes(data.status)
    if (!isActive) return

    const timer = setInterval(() => {
      api.getExecution(id).then(d => {
        setData(d)
        if (d.trace?.length && !selected) setSelected(d.trace[0].node_id)
      }).catch(() => {})
    }, 2000)

    return () => clearInterval(timer)
  }, [id, data?.status, selected])

  async function handleRetry() {
    try { const { execution_id } = await api.retry(id); navigate(`/executions/${execution_id}`) } catch(e){ setError(e.message) }
  }
  async function handleCancel() {
    try { await api.cancel(id); setData(d => d ? { ...d, status: 'cancelling' } : d) } catch(e){ setError(e.message) }
  }
  async function handleExplain() {
    if (explaining) return
    setExplaining(true)
    try { const r = await api.explain(id); setExplain({ ok: true, text: r.explanation }) } catch(e){ setExplain({ ok:false, text:e.message }) } finally { setExplaining(false)}
  }

  if (loading) return <div className="page"><PageHeader title="Execution" /><LoadingSkeleton rows={6} /></div>
  if (error) return <div className="page"><PageHeader title="Execution" /><div className="banner-inline err">{error}</div><button className="ghost" onClick={() => navigate('/executions')}>Back</button></div>
  if (!data) return null

  const steps = (data.trace || []).map(s => ({ ...s }))
  const selectedStep = steps.find(s => s.node_id === selected) || steps[0] || null
  const terminal = ['success','failed','cancelled'].includes(data.status)

  return (
    <div className="page execution-detail-page">
      <PageHeader
        title={`Execution ${id.slice(0,8)}`}
        description={`${data.workflow_id} · ${STATUS_LABEL[data.status] || data.status}`}
        breadcrumbs={[{ label: 'Executions', href: '/executions' }, { label: id.slice(0,8) }]}
        actions={<>
          <button className="ghost" onClick={() => navigate('/executions')}>Back</button>
          {data.status === 'failed' && <button className="ghost" onClick={handleExplain} disabled={explaining}>✨ Explain</button>}
          {(data.status === 'running' || data.status === 'waiting_approval' || data.status === 'queued') && <button className="danger" onClick={handleCancel}>Cancel</button>}
          {terminal && <button className="ghost" onClick={handleRetry}>↻ Retry</button>}
        </>}
      />

      <div className="meta-grid">
        <div className="meta-item"><span className="meta-label">Status</span><span className={`status-label status-${data.status}`}>{STATUS_LABEL[data.status] || data.status}</span></div>
        <div className="meta-item"><span className="meta-label">Workflow</span><span>{data.workflow_id}</span></div>
        <div className="meta-item"><span className="meta-label">Version</span><span>{data.workflow_version ?? '—'}</span></div>
        <div className="meta-item"><span className="meta-label">Trigger</span><span>{data.trigger}</span></div>
        <div className="meta-item"><span className="meta-label">Started</span><span>{data.started_at ? new Date(data.started_at).toLocaleString() : '—'}</span></div>
        <div className="meta-item"><span className="meta-label">Finished</span><span>{data.finished_at ? new Date(data.finished_at).toLocaleString() : '—'}</span></div>
      </div>

      {data.error && (
        <div className="banner-inline err">
          {typeof data.error === 'object' ? (
            <>
              {data.error.code && <strong>{data.error.code}: </strong>}
              {data.error.message || JSON.stringify(data.error)}
            </>
          ) : (
            String(data.error)
          )}
        </div>
      )}
      {explain && <div className={`banner-inline ${explain.ok ? 'info' : 'err'}`}>{explain.ok && <strong>AI: </strong>}{explain.text}</div>}
      {data.pause_state && <div className="banner-inline info">⏸ {data.pause_state.message || 'Waiting for approval'}</div>}

      <div className="debug-tabs" style={{ marginTop: 16 }}>
        {['timeline','steps','trace'].map(t => (
          <button key={t} className={`debug-tab ${tab===t?'active':''}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      <div className="debug-body" style={{ marginTop: 12 }}>
        {tab === 'timeline' && (
          <ExecutionTimeline steps={steps} selectedId={selected} onSelect={s => setSelected(s.node_id)} />
        )}
        {tab === 'steps' && (
          <div className="steps-list">
            {steps.length === 0 && <p className="hint">No steps yet.</p>}
            {steps.map(s => (
              <button key={s.node_id} className={`step-row ${selected === s.node_id ? 'selected':''}`} onClick={() => setSelected(s.node_id)}>
                <span className="step-icon">{s.status === 'success' ? '✓' : s.status === 'error' || s.status === 'failed' ? '✕' : '•'}</span>
                <span className="step-name">{s.node_id}</span>
                <span className="muted">{s.node_type}</span>
                <span className="step-duration">{s.duration_ms != null ? `${s.duration_ms}ms` : ''}</span>
              </button>
            ))}
          </div>
        )}
        {tab === 'trace' && (
          <div className="trace-view">
            <pre className="json-tree">{JSON.stringify(steps, null, 2)}</pre>
          </div>
        )}

        {selectedStep && (
          <div style={{ marginTop: 16 }}>
            <StepDetail
              execution={data}
              step={selectedStep}
              onRetryNode={(nodeId) => {
                api.retry(id, nodeId).then(({ execution_id }) => navigate(`/executions/${execution_id}`)).catch(e => setError(e.message))
              }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
