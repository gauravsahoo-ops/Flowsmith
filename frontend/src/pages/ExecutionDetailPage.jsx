import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ExecutionTimeline from '../components/ExecutionTimeline'
import StepDetail from '../components/StepDetail'
import { NodeIcon } from '../components/NodeIcons'

const STATUS_LABEL = {
  success: 'Success',
  failed: 'Failed',
  cancelled: 'Cancelled',
  running: 'Running…',
  queued: 'Queued…',
  waiting_approval: 'Waiting Approval',
  partial_success: 'Partial Success',
  retrying: 'Retrying…',
}

function fmtTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function fmtDur(s, f) {
  if (!s) return '—'
  const ms = f ? new Date(f) - new Date(s) : Date.now() - new Date(s)
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export default function ExecutionDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('timeline')
  const [selected, setSelected] = useState(null)
  const [copiedId, setCopiedId] = useState(false)

  // AI explanation state
  const [explain, setExplain] = useState(null)
  const [explaining, setExplaining] = useState(false)

  // Outbound API Telemetry inspector state
  const [apiRequests, setApiRequests] = useState([])
  const [selectedRequestId, setSelectedRequestId] = useState(null)
  const [selectedRequestDetail, setSelectedRequestDetail] = useState(null)
  const [loadingRequests, setLoadingRequests] = useState(false)
  const [copiedPayload, setCopiedPayload] = useState(null)

  // Retry history state
  const [retryHistory, setRetryHistory] = useState([])
  const [loadingRetries, setLoadingRetries] = useState(false)

  // Retry confirmation dialog state
  const [retryModalOpen, setRetryModalOpen] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [retryReason, setRetryReason] = useState('')

  // Load execution core payload
  const fetchExecution = useCallback((silent = false) => {
    if (!silent) setLoading(true)
    return api
      .getExecution(id)
      .then((d) => {
        setData(d)
        if (d.trace?.length && !selected) {
          setSelected(d.trace[0].node_id)
        }
        setError(null)
      })
      .catch((e) => {
        if (!silent) setError(e.message)
      })
      .finally(() => {
        if (!silent) setLoading(false)
      })
  }, [id, selected])

  useEffect(() => {
    fetchExecution()
  }, [fetchExecution])

  // Live auto-poll while running, queued, or retrying
  const isRunning = Boolean(
    data && ['running', 'queued', 'waiting_approval', 'retrying'].includes(data.status),
  )

  useEffect(() => {
    if (!isRunning) return
    const timer = setInterval(() => {
      fetchExecution(true)
    }, 2000)
    return () => clearInterval(timer)
  }, [isRunning, fetchExecution])

  // Load API requests when switching to 'requests' tab
  useEffect(() => {
    if (tab === 'requests') {
      setLoadingRequests(true)
      api
        .getExecutionRequests(id)
        .then((res) => {
          const reqs = res?.data || res || []
          setApiRequests(Array.isArray(reqs) ? reqs : [])
          if (reqs.length > 0 && !selectedRequestId) {
            setSelectedRequestId(reqs[0].id)
          }
        })
        .catch(() => setApiRequests([]))
        .finally(() => setLoadingRequests(false))
    }
  }, [id, tab, selectedRequestId])

  // Load detailed request payload when selected
  useEffect(() => {
    if (!selectedRequestId) {
      setSelectedRequestDetail(null)
      return
    }
    api
      .getExecutionRequestDetail(id, selectedRequestId)
      .then((detail) => setSelectedRequestDetail(detail))
      .catch(() => setSelectedRequestDetail(null))
  }, [id, selectedRequestId])

  // Load Retry History when switching to 'retries' tab
  useEffect(() => {
    if (tab === 'retries') {
      setLoadingRetries(true)
      api
        .getExecutionRetries(id)
        .then((res) => {
          const rets = res?.data || res || []
          setRetryHistory(Array.isArray(rets) ? rets : [])
        })
        .catch(() => setRetryHistory([]))
        .finally(() => setLoadingRetries(false))
    }
  }, [id, tab])

  async function handleConfirmRetry() {
    if (retrying) return
    setRetrying(true)
    setError(null)
    try {
      const idempotencyKey = `retry_${id}_${Date.now()}`
      const res = await api.retryExecution(id, {
        idempotency_key: idempotencyKey,
        retry_reason: retryReason || 'Manual retry from execution inspector',
      })
      setRetryModalOpen(false)
      const nextId = res?.execution_id || res?.id
      if (nextId) {
        navigate(`/executions/${nextId}`)
      } else {
        fetchExecution()
      }
    } catch (e) {
      setError(`Retry failed: ${e.message}`)
    } finally {
      setRetrying(false)
    }
  }

  async function handleCancel() {
    try {
      await api.cancel(id)
      setData((d) => (d ? { ...d, status: 'cancelled' } : d))
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleExplain() {
    if (explaining) return
    setExplaining(true)
    try {
      const r = await api.explain(id)
      setExplain({ ok: true, text: r.explanation })
    } catch (e) {
      setExplain({ ok: false, text: e.message })
    } finally {
      setExplaining(false)
    }
  }

  function copyText(val, key) {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(typeof val === 'string' ? val : JSON.stringify(val, null, 2))
      if (key === 'id') {
        setCopiedId(true)
        setTimeout(() => setCopiedId(false), 2000)
      } else {
        setCopiedPayload(key)
        setTimeout(() => setCopiedPayload(null), 2000)
      }
    }
  }

  if (loading) {
    return (
      <div className="page">
        <PageHeader title="Execution" />
        <LoadingSkeleton rows={8} />
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="page">
        <PageHeader title="Execution" />
        <div className="banner-inline err">{error}</div>
        <button className="ghost" onClick={() => navigate('/executions')} style={{ marginTop: 12 }}>
          Back to Executions
        </button>
      </div>
    )
  }

  if (!data) return null

  const steps = (data.trace || []).map((s) => ({ ...s }))
  const selectedStep = steps.find((s) => s.node_id === selected) || steps[0] || null
  const terminal = ['success', 'failed', 'cancelled', 'partial_success'].includes(data.status)
  const isFailed = data.status === 'failed' || Boolean(data.error)

  const httpSuccess = data.http_status_code && data.http_status_code >= 200 && data.http_status_code < 300
  const httpError = data.http_status_code && data.http_status_code >= 400

  return (
    <div className="page execution-detail-page">
      <PageHeader
        title={`Execution ${id.slice(0, 8)}`}
        description={`${data.workflow_name || data.workflow_id} · ${STATUS_LABEL[data.status] || data.status}`}
        breadcrumbs={[{ label: 'Executions', href: '/executions' }, { label: id.slice(0, 8) }]}
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button className="ghost" onClick={() => navigate('/executions')}>
              ← Back
            </button>
            {isFailed && (
              <button className="ghost" onClick={handleExplain} disabled={explaining}>
                {explaining ? 'Analyzing…' : '✨ AI Diagnostics'}
              </button>
            )}
            {(data.status === 'running' || data.status === 'waiting_approval' || data.status === 'queued') && (
              <button className="danger" onClick={handleCancel}>
                Cancel Run
              </button>
            )}
            {terminal && (
              <button
                className="primary"
                onClick={() => setRetryModalOpen(true)}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <span>↻ Re-execute</span>
              </button>
            )}
          </div>
        }
      />

      {/* Top Telemetry & Record Processing KPI Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 14,
          margin: '16px 0',
        }}
      >
        {/* Card 1: Status & Execution Identity */}
        <div
          style={{
            background: 'rgba(19, 23, 34, 0.75)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: 12,
            padding: '16px 18px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
              Execution Status
            </span>
            <span className={`status-label status-${data.status}`}>
              {STATUS_LABEL[data.status] || data.status}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
            <code style={{ fontSize: 12, color: '#f8fafc', background: 'rgba(255,255,255,0.06)', padding: '2px 6px', borderRadius: 4 }}>
              {data.id}
            </code>
            <button
              type="button"
              className="ghost"
              onClick={() => copyText(data.id, 'id')}
              style={{ padding: '2px 6px', fontSize: 11, color: copiedId ? '#34d399' : '#94a3b8' }}
              title="Copy Execution ID"
            >
              {copiedId ? '✓ Copied' : 'Copy'}
            </button>
          </div>

          <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div>Started: <strong style={{ color: '#e2e8f0' }}>{fmtTime(data.started_at)}</strong></div>
            <div>Duration: <strong style={{ color: '#e2e8f0' }}>{fmtDur(data.started_at, data.finished_at)}</strong></div>
            <div>Trigger: <strong style={{ color: '#e2e8f0' }}>{data.trigger || 'manual'}</strong></div>
          </div>
        </div>

        {/* Card 2: Record Processing Statistics */}
        <div
          style={{
            background: 'rgba(19, 23, 34, 0.75)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: 12,
            padding: '16px 18px',
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 12 }}>
            Record Processing Telemetry
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, textAlign: 'center' }}>
            <div style={{ background: 'rgba(255,255,255,0.03)', padding: '8px 4px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: '#38bdf8' }}>{(data.records_read || 0).toLocaleString()}</div>
              <div style={{ fontSize: 10.5, color: '#94a3b8', textTransform: 'uppercase' }}>Read</div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', padding: '8px 4px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: '#34d399' }}>{(data.records_processed || 0).toLocaleString()}</div>
              <div style={{ fontSize: 10.5, color: '#94a3b8', textTransform: 'uppercase' }}>Processed</div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', padding: '8px 4px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: data.records_failed ? '#f87171' : '#94a3b8' }}>
                {(data.records_failed || 0).toLocaleString()}
              </div>
              <div style={{ fontSize: 10.5, color: '#94a3b8', textTransform: 'uppercase' }}>Failed</div>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-around', marginTop: 10, fontSize: 11, color: 'var(--text-muted)' }}>
            <span>Created: <strong style={{ color: '#e2e8f0' }}>{data.records_created || 0}</strong></span>
            <span>Updated: <strong style={{ color: '#e2e8f0' }}>{data.records_updated || 0}</strong></span>
            <span>Skipped: <strong style={{ color: '#e2e8f0' }}>{data.records_skipped || 0}</strong></span>
          </div>
        </div>

        {/* Card 3: Integration Telemetry (Cyclr metadata) */}
        <div
          style={{
            background: 'rgba(19, 23, 34, 0.75)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: 12,
            padding: '16px 18px',
          }}
        >
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 10 }}>
            Integration Telemetry
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="muted">Source:</span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: '#e2e8f0' }}>
                {data.source_connector && <NodeIcon type={data.source_connector} size={14} />}
                <strong>{data.source_connector || 'Webhook / Trigger'}</strong>
                {data.source_object && <span className="muted">({data.source_object})</span>}
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="muted">Destination:</span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: '#e2e8f0' }}>
                {data.destination_connector && <NodeIcon type={data.destination_connector} size={14} />}
                <strong>{data.destination_connector || 'Flow Output'}</strong>
                {data.destination_object && <span className="muted">({data.destination_object})</span>}
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 }}>
              <span className="muted">HTTP Telemetry:</span>
              {data.http_status_code ? (
                <span
                  style={{
                    padding: '2px 6px',
                    borderRadius: 4,
                    fontFamily: 'monospace',
                    fontWeight: 700,
                    fontSize: 11,
                    background: httpSuccess ? 'rgba(16, 185, 129, 0.15)' : httpError ? 'rgba(239, 68, 68, 0.15)' : 'rgba(255,255,255,0.06)',
                    color: httpSuccess ? '#34d399' : httpError ? '#f87171' : '#cbd5e1',
                    border: `1px solid ${httpSuccess ? 'rgba(16, 185, 129, 0.3)' : httpError ? 'rgba(239, 68, 68, 0.3)' : 'rgba(255,255,255,0.1)'}`,
                  }}
                >
                  {data.http_method || 'HTTP'} {data.http_status_code}
                </span>
              ) : (
                <span className="muted">—</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Primary Failure Diagnostics Alert */}
      {isFailed && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.08)',
            border: '1px solid rgba(239, 68, 68, 0.25)',
            borderRadius: 10,
            padding: '14px 18px',
            marginBottom: 18,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{ color: '#f87171', fontWeight: 700, fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              Execution Error Diagnostic
            </span>
            {data.error_type && (
              <span
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  padding: '1px 6px',
                  borderRadius: 4,
                  background: 'rgba(239, 68, 68, 0.2)',
                  color: '#fca5a5',
                  border: '1px solid rgba(239, 68, 68, 0.35)',
                }}
              >
                {data.error_type}
              </span>
            )}
            {data.error_code && (
              <code style={{ fontSize: 11, color: '#fca5a5' }}>
                [{data.error_code}]
              </code>
            )}
          </div>

          <div style={{ fontSize: 12.5, color: '#fecaca', lineHeight: 1.5 }}>
            {data.error_summary ||
              (typeof data.error === 'object' ? data.error.message || JSON.stringify(data.error) : String(data.error))}
          </div>
        </div>
      )}

      {explain && (
        <div className={`banner-inline ${explain.ok ? 'info' : 'err'}`} style={{ marginBottom: 16 }}>
          {explain.ok && <strong>AI Diagnostic Insight: </strong>}
          {explain.text}
        </div>
      )}

      {/* Tabs Bar */}
      <div className="debug-tabs" style={{ marginBottom: 14 }}>
        {[
          { id: 'timeline', label: 'Timeline & Spans' },
          { id: 'steps', label: `Steps (${steps.length})` },
          { id: 'requests', label: 'API Inspector' },
          { id: 'retries', label: `Retry History ${data.retry_count ? `(${data.retry_count})` : ''}` },
          { id: 'trace', label: 'Raw Trace (JSON)' },
        ].map((t) => (
          <button
            key={t.id}
            type="button"
            className={`debug-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Body Contents */}
      <div className="debug-body">
        {/* Tab 1: Timeline */}
        {tab === 'timeline' && (
          <div>
            <ExecutionTimeline
              steps={steps}
              selectedId={selected}
              onSelect={(s) => setSelected(s.node_id)}
            />
            {selectedStep && (
              <div style={{ marginTop: 18 }}>
                <StepDetail
                  execution={data}
                  step={selectedStep}
                  onRetryNode={(nodeId) => {
                    api
                      .retry(id, nodeId)
                      .then(({ execution_id }) => navigate(`/executions/${execution_id}`))
                      .catch((e) => setError(e.message))
                  }}
                />
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Steps Table */}
        {tab === 'steps' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 340px) 1fr', gap: 16 }}>
            <div className="steps-list" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {steps.length === 0 && <p className="hint">No steps recorded in this run.</p>}
              {steps.map((s) => (
                <button
                  key={s.node_id}
                  className={`step-row ${selected === s.node_id ? 'selected' : ''}`}
                  onClick={() => setSelected(s.node_id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 12px',
                    borderRadius: 7,
                    border: '1px solid var(--border)',
                    background: selected === s.node_id ? 'rgba(99, 102, 241, 0.15)' : 'var(--panel-2)',
                    textAlign: 'left',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="step-icon" style={{ display: 'inline-flex' }}>
                      {s.status === 'success' ? (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#34d399" strokeWidth="2.5">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : s.status === 'error' || s.status === 'failed' ? (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#f87171" strokeWidth="2.5">
                          <line x1="18" y1="6" x2="6" y2="18" />
                          <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                      ) : (
                        <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} />
                      )}
                    </span>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 12.5, color: '#f8fafc' }}>{s.node_id}</div>
                      <div className="muted" style={{ fontSize: 11 }}>{s.node_type}</div>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span className="step-duration" style={{ fontSize: 11, fontFamily: 'monospace' }}>
                      {s.duration_ms != null ? `${s.duration_ms}ms` : ''}
                    </span>
                  </div>
                </button>
              ))}
            </div>

            {selectedStep ? (
              <StepDetail
                execution={data}
                step={selectedStep}
                onRetryNode={(nodeId) => {
                  api
                    .retry(id, nodeId)
                    .then(({ execution_id }) => navigate(`/executions/${execution_id}`))
                    .catch((e) => setError(e.message))
                }}
              />
            ) : (
              <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
                Select a step on the left to inspect inputs, outputs, and parameters.
              </div>
            )}
          </div>
        )}

        {/* Tab 3: API Request / Response Inspector */}
        {tab === 'requests' && (
          <div>
            {loadingRequests ? (
              <LoadingSkeleton rows={5} />
            ) : apiRequests.length === 0 ? (
              <div style={{ padding: '32px 16px', textAlign: 'center', background: 'var(--panel-2)', borderRadius: 10, border: '1px solid var(--border)' }}>
                <h4 style={{ margin: '0 0 6px', fontSize: 14 }}>No Outbound API Calls</h4>
                <p className="hint" style={{ margin: 0, fontSize: 12.5 }}>
                  This execution did not trigger external HTTP requests or connector network calls.
                </p>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 360px) 1fr', gap: 16 }}>
                {/* Outbound Request List */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {apiRequests.map((req) => {
                    const isOk = req.status_code && req.status_code >= 200 && req.status_code < 300
                    const isErr = req.status_code && req.status_code >= 400
                    const isSel = selectedRequestId === req.id
                    return (
                      <button
                        key={req.id}
                        type="button"
                        onClick={() => setSelectedRequestId(req.id)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '10px 12px',
                          borderRadius: 8,
                          background: isSel ? 'rgba(99, 102, 241, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                          border: `1px solid ${isSel ? 'rgba(99, 102, 241, 0.4)' : 'rgba(255, 255, 255, 0.06)'}`,
                          cursor: 'pointer',
                          textAlign: 'left',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                          <span
                            style={{
                              fontSize: 10.5,
                              fontFamily: 'monospace',
                              fontWeight: 700,
                              padding: '2px 5px',
                              borderRadius: 4,
                              background: isOk ? 'rgba(16, 185, 129, 0.15)' : isErr ? 'rgba(239, 68, 68, 0.15)' : 'rgba(255,255,255,0.06)',
                              color: isOk ? '#34d399' : isErr ? '#f87171' : '#cbd5e1',
                            }}
                          >
                            {req.method} {req.status_code || ''}
                          </span>
                          <span
                            style={{
                              fontSize: 12,
                              color: '#f8fafc',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                            title={req.url}
                          >
                            {req.url}
                          </span>
                        </div>
                        <span style={{ fontSize: 11, color: '#94a3b8', flexShrink: 0, fontFamily: 'monospace' }}>
                          {req.duration_ms ? `${Math.round(req.duration_ms)}ms` : ''}
                        </span>
                      </button>
                    )
                  })}
                </div>

                {/* Request / Response Details Pane */}
                <div
                  style={{
                    background: 'rgba(19, 23, 34, 0.75)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: 10,
                    padding: 16,
                  }}
                >
                  {selectedRequestDetail ? (
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span
                            style={{
                              fontFamily: 'monospace',
                              fontWeight: 700,
                              fontSize: 12,
                              padding: '3px 7px',
                              borderRadius: 4,
                              background: 'rgba(99, 102, 241, 0.2)',
                              color: '#818cf8',
                            }}
                          >
                            {selectedRequestDetail.method}
                          </span>
                          <code style={{ fontSize: 12.5, color: '#f8fafc' }}>
                            {selectedRequestDetail.url}
                          </code>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span className="hint">
                            Status: <strong style={{ color: selectedRequestDetail.status_code < 400 ? '#34d399' : '#f87171' }}>{selectedRequestDetail.status_code || '—'}</strong>
                          </span>
                          <span className="hint">
                            Latency: <strong>{selectedRequestDetail.duration_ms ? `${Math.round(selectedRequestDetail.duration_ms)}ms` : '—'}</strong>
                          </span>
                        </div>
                      </div>

                      {/* Request Headers */}
                      <div style={{ marginBottom: 14 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                            Request Headers (Sanitized)
                          </span>
                          <button
                            type="button"
                            className="ghost"
                            onClick={() => copyText(selectedRequestDetail.request_headers, 'req_h')}
                            style={{ fontSize: 11, padding: '2px 6px' }}
                          >
                            {copiedPayload === 'req_h' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre
                          style={{
                            margin: 0,
                            padding: 10,
                            borderRadius: 6,
                            background: 'rgba(0,0,0,0.3)',
                            border: '1px solid rgba(255,255,255,0.05)',
                            fontSize: 11.5,
                            fontFamily: 'monospace',
                            color: '#94a3b8',
                            maxHeight: 120,
                            overflowY: 'auto',
                          }}
                        >
                          {JSON.stringify(selectedRequestDetail.request_headers || {}, null, 2)}
                        </pre>
                      </div>

                      {/* Request Body */}
                      <div style={{ marginBottom: 14 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                            Request Payload
                          </span>
                          <button
                            type="button"
                            className="ghost"
                            onClick={() => copyText(selectedRequestDetail.request_body, 'req_b')}
                            style={{ fontSize: 11, padding: '2px 6px' }}
                          >
                            {copiedPayload === 'req_b' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre
                          style={{
                            margin: 0,
                            padding: 10,
                            borderRadius: 6,
                            background: 'rgba(0,0,0,0.3)',
                            border: '1px solid rgba(255,255,255,0.05)',
                            fontSize: 11.5,
                            fontFamily: 'monospace',
                            color: '#cbd5e1',
                            maxHeight: 180,
                            overflowY: 'auto',
                          }}
                        >
                          {typeof selectedRequestDetail.request_body === 'object'
                            ? JSON.stringify(selectedRequestDetail.request_body, null, 2)
                            : selectedRequestDetail.request_body || '—'}
                        </pre>
                      </div>

                      {/* Response Payload */}
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                            Response Payload
                          </span>
                          <button
                            type="button"
                            className="ghost"
                            onClick={() => copyText(selectedRequestDetail.response_body, 'res_b')}
                            style={{ fontSize: 11, padding: '2px 6px' }}
                          >
                            {copiedPayload === 'res_b' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre
                          style={{
                            margin: 0,
                            padding: 10,
                            borderRadius: 6,
                            background: 'rgba(0,0,0,0.3)',
                            border: '1px solid rgba(255,255,255,0.05)',
                            fontSize: 11.5,
                            fontFamily: 'monospace',
                            color: '#cbd5e1',
                            maxHeight: 220,
                            overflowY: 'auto',
                          }}
                        >
                          {typeof selectedRequestDetail.response_body === 'object'
                            ? JSON.stringify(selectedRequestDetail.response_body, null, 2)
                            : selectedRequestDetail.response_body || '—'}
                        </pre>
                      </div>
                    </div>
                  ) : (
                    <div style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)' }}>
                      Select a request on the left to inspect outbound network payloads and headers.
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Retry History */}
        {tab === 'retries' && (
          <div>
            {loadingRetries ? (
              <LoadingSkeleton rows={4} />
            ) : retryHistory.length === 0 ? (
              <div style={{ padding: '32px 16px', textAlign: 'center', background: 'var(--panel-2)', borderRadius: 10, border: '1px solid var(--border)' }}>
                <h4 style={{ margin: '0 0 6px', fontSize: 14 }}>No Prior Retry Attempts</h4>
                <p className="hint" style={{ margin: 0, fontSize: 12.5 }}>
                  This execution was triggered directly as attempt #1.
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {retryHistory.map((rh) => (
                  <div
                    key={rh.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '12px 16px',
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid rgba(255,255,255,0.07)',
                      borderRadius: 8,
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{ fontWeight: 700, fontSize: 12.5, color: '#f8fafc' }}>
                          Attempt #{rh.attempt_number}
                        </span>
                        <span className={`status-label status-${rh.status || 'unknown'}`}>
                          {rh.status || 'retrying'}
                        </span>
                        <code style={{ fontSize: 11, color: '#94a3b8' }}>{rh.execution_id}</code>
                      </div>
                      <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                        Triggered by {rh.triggered_by || 'system'} · {fmtTime(rh.created_at)}
                        {rh.retry_reason && ` · Note: "${rh.retry_reason}"`}
                      </div>
                    </div>
                    <div>
                      <button
                        type="button"
                        className="ghost"
                        onClick={() => navigate(`/executions/${rh.execution_id}`)}
                        style={{ fontSize: 12 }}
                      >
                        Inspect Attempt →
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 5: Raw Trace JSON */}
        {tab === 'trace' && (
          <div className="trace-view">
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
              <button
                type="button"
                className="ghost"
                onClick={() => copyText(steps, 'trace')}
                style={{ fontSize: 12 }}
              >
                {copiedPayload === 'trace' ? '✓ Copied Trace' : 'Copy Trace JSON'}
              </button>
            </div>
            <pre className="json-tree" style={{ maxHeight: 600, overflowY: 'auto' }}>
              {JSON.stringify(steps, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* Retry Confirmation Modal */}
      {retryModalOpen && (
        <div
          className="modal-backdrop"
          onClick={() => setRetryModalOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            backdropFilter: 'blur(4px)',
            display: 'grid',
            placeItems: 'center',
            zIndex: 1000,
          }}
        >
          <div
            className="modal-content"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: '100%',
              maxWidth: 480,
              background: '#0f172a',
              border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: 14,
              padding: 24,
              boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
            }}
          >
            <h3 style={{ margin: '0 0 10px', fontSize: 16, color: '#f8fafc' }}>
              Confirm Workflow Re-Execution
            </h3>
            <p style={{ margin: '0 0 14px', fontSize: 13, color: '#94a3b8', lineHeight: 1.5 }}>
              You are about to re-trigger this execution with original parameters. An idempotency token will be dispatched to prevent duplicate upstream submissions.
            </p>

            <div style={{ marginBottom: 14 }}>
              <label style={{ display: 'block', fontSize: 11.5, fontWeight: 600, color: '#cbd5e1', marginBottom: 6 }}>
                Retry Reason / Operational Note (Optional)
              </label>
              <input
                type="text"
                placeholder="e.g. Downstream endpoint recovered; manual re-trigger"
                value={retryReason}
                onChange={(e) => setRetryReason(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  fontSize: 12.5,
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 6,
                  color: '#f8fafc',
                }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 20 }}>
              <button
                type="button"
                className="ghost"
                onClick={() => setRetryModalOpen(false)}
                disabled={retrying}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                onClick={handleConfirmRetry}
                disabled={retrying}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                {retrying ? (
                  <>
                    <span className="spinner-sm" />
                    <span>Launching…</span>
                  </>
                ) : (
                  <span>Launch Retry Run</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
