// ExecutionInspector (Phase 13): the workflow debugger.
//
// Tabs:
//   Timeline — span chart of the run (click a bar to inspect the step)
//   Steps    — chronological list with inline detail for the selection
//   Compare  — diff this execution against another of the same workflow
//
// Header actions: full replay, AI explain (failures), close.
// Step-level "Retry from here" lives in StepDetail and hits the safe
// node-retry endpoint (upstream outputs are seeded, never re-run).

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useExecutionStore } from '../stores/executionStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { api } from '../api'
import ExecutionTimeline from './ExecutionTimeline'
import StepDetail from './StepDetail'
import ExecutionCompare from './ExecutionCompare'
import Status from './shared/Status'
import ErrorState from './shared/ErrorState'

function fmtDuration(ms) {
  if (ms == null) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString()
}

export default function ExecutionInspector({ onClose }) {
  const executionId = useExecutionStore((s) => s.executionId)
  const status = useExecutionStore((s) => s.status)
  const nodeStatuses = useExecutionStore((s) => s.nodeStatuses)
  const trace = useExecutionStore((s) => s.trace)
  const startedAt = useExecutionStore((s) => s.startedAt)
  const finishedAt = useExecutionStore((s) => s.finishedAt)
  const version = useExecutionStore((s) => s.version)
  const error = useExecutionStore((s) => s.error)
  const pauseState = useExecutionStore((s) => s.pauseState)
  const approval = useExecutionStore((s) => s.approval)
  const retry = useExecutionStore((s) => s.retry)
  const clear = useExecutionStore((s) => s.clear)
  const canvasNodes = useWorkflowStore((s) => s.nodes)
  const workflow = useWorkflowStore((s) => s.workflow)
  const run = useExecutionStore((s) => s.run)
  const running = useExecutionStore((s) => s.running)
  const loadExecution = useExecutionStore((s) => s.load)

  const [explain, setExplain] = useState(null)
  const [explaining, setExplaining] = useState(false)
  const [tab, setTab] = useState('timeline')
  const [selectedStepId, setSelectedStepId] = useState(null)
  const [recentExecutions, setRecentExecutions] = useState([])
  const [loadingRecent, setLoadingRecent] = useState(false)
  const [exportMenuOpen, setExportMenuOpen] = useState(false)

  // Full payload of THIS execution (results.outputs drive branch chips
  // and the compare baseline); fetched once per terminal state.
  const [fullExec, setFullExec] = useState(null)
  // Sibling executions for the compare picker.
  const [siblings, setSiblings] = useState([])
  const [compareWith, setCompareWith] = useState('')
  const [compareData, setCompareData] = useState(null)

  // Fetch recent executions when no active run is loaded
  useEffect(() => {
    if (executionId || !workflow?.id) return
    setLoadingRecent(true)
    let alive = true
    api
      .listExecutions({ workflowId: workflow.id, pageSize: 15 })
      .then(({ data }) => {
        if (alive) setRecentExecutions(Array.isArray(data) ? data : [])
      })
      .catch(() => {
        if (alive) setRecentExecutions([])
      })
      .finally(() => {
        if (alive) setLoadingRecent(false)
      })
    return () => {
      alive = false
    }
  }, [executionId, workflow?.id])

  const nameOf = useMemo(() => {
    const byId = new Map(canvasNodes.map((n) => [n.id, n.data?.node?.id]))
    return (nodeId) => byId.get(nodeId) || nodeId
  }, [canvasNodes])

  const steps = trace.length
    ? trace.map((s) => ({ ...s, _name: nameOf(s.node_id) }))
    : Object.entries(nodeStatuses).map(([nodeId, st]) => ({
        node_id: nodeId,
        status: st,
        node_type: '',
        _name: nameOf(nodeId),
      }))

  const selectedStep = useMemo(
    () =>
      steps.find((s) => s.node_id === selectedStepId) ||
      steps.find((s) => s.status === 'error' || s.status === 'failed') ||
      null,
    [steps, selectedStepId],
  )

  const terminal = status === 'success' || status === 'failed' || status === 'cancelled'
  const durationMs =
    startedAt && finishedAt ? new Date(finishedAt) - new Date(startedAt) : null

  // Pull the complete payload once the run settles (masked server-side).
  useEffect(() => {
    if (!executionId || !terminal) {
      setFullExec(null)
      return
    }
    let alive = true
    api.getExecution(executionId).then((data) => {
      if (alive) setFullExec(data)
    }).catch(() => {})
    return () => {
      alive = false
    }
  }, [executionId, terminal])

  // Reset per-execution UI state when switching runs.
  useEffect(() => {
    setSelectedStepId(null)
    setCompareWith('')
    setCompareData(null)
    setTab('timeline')
  }, [executionId])

  const loadSiblings = useCallback(() => {
    const wfId = useWorkflowStore.getState().workflow?.id
    if (!wfId) return
    api
      .listExecutions({ workflowId: wfId, pageSize: 25 })
      .then(({ data }) => setSiblings(Array.isArray(data) ? data : []))
      .catch(() => setSiblings([]))
  }, [])

  useEffect(() => {
    if (tab === 'compare' && terminal && !siblings.length) loadSiblings()
  }, [tab, terminal, siblings.length, loadSiblings])

  useEffect(() => {
    if (!compareWith) {
      setCompareData(null)
      return
    }
    let alive = true
    api.getExecution(compareWith).then((data) => {
      if (alive) setCompareData(data)
    }).catch(() => {})
    return () => {
      alive = false
    }
  }, [compareWith])

  async function onExplain() {
    if (!executionId || explaining) return
    setExplaining(true)
    setExplain(null)
    try {
      const res = await api.explain(executionId)
      setExplain({ ok: true, text: res.explanation })
    } catch (err) {
      setExplain({ ok: false, text: err.message })
    } finally {
      setExplaining(false)
    }
  }

  const onRetryNode = useCallback(
    (nodeId) => {
      if (!executionId) return
      api
        .retry(executionId, nodeId)
        .then(({ execution_id }) => useExecutionStore.getState().load(execution_id))
        .catch((err) => window.alert(`Node retry failed: ${err.message}`))
    },
    [executionId],
  )

  // Empty state when no execution is loaded yet
  if (!executionId) {
    return (
      <aside className="panel inspector debugger">
        <header>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--accent)' }}>
              <polyline points="4 17 10 11 4 5" />
              <line x1="12" y1="19" x2="20" y2="19" />
            </svg>
            <h2>Console</h2>
          </div>
          <div className="inspector-actions">
            <button type="button" className="ghost" onClick={onClose || clear} title="Close Console" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, padding: 0 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </header>

        <div style={{ padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto', flex: 1 }}>
          <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 10, padding: 18, textAlign: 'center' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 44, height: 44, borderRadius: '50%', background: 'rgba(99, 102, 241, 0.12)', color: 'var(--accent)', marginBottom: 10 }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="4 17 10 11 4 5" />
                <line x1="12" y1="19" x2="20" y2="19" />
              </svg>
            </div>
            <h4 style={{ margin: '0 0 6px', fontSize: 14, fontWeight: 600 }}>No Active Execution</h4>
            <p style={{ margin: 0, fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.5 }}>
              Run your workflow to inspect real-time execution steps, console outputs, and trace errors.
            </p>
            <button
              className="primary"
              disabled={running || !workflow?.id}
              onClick={() => {
                if (workflow?.id) run(workflow.id)
              }}
              style={{ marginTop: 14, display: 'inline-flex', alignItems: 'center', gap: 6, marginInline: 'auto' }}
            >
              {running ? (
                <>
                  <span className="spinner-sm" />
                  <span>Running…</span>
                </>
              ) : (
                <>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  <span>Run Workflow</span>
                </>
              )}
            </button>
          </div>

          {loadingRecent ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8, color: 'var(--muted)', fontSize: 13 }}>
              <span className="spinner" />
              <span>Loading past executions…</span>
            </div>
          ) : recentExecutions.length > 0 ? (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                  Past Executions ({recentExecutions.length})
                </span>
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>Click to inspect</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {recentExecutions.map((exec) => (
                  <button
                    key={exec.id}
                    type="button"
                    onClick={() => loadExecution(exec.id)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '9px 12px',
                      background: 'var(--panel-2)',
                      border: '1px solid var(--border)',
                      borderRadius: 7,
                      color: 'var(--text)',
                      cursor: 'pointer',
                      fontSize: 12.5,
                      textAlign: 'left',
                      transition: 'all 0.12s ease',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent)' }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className={`status-dot status-${exec.status}`} />
                      <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600 }}>#{exec.id.slice(-6)}</span>
                      <span style={{ fontSize: 11, color: 'var(--muted)' }}>{exec.trigger_type || 'manual'}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 11, color: 'var(--muted)' }}>{fmtTime(exec.started_at)}</span>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 600,
                          textTransform: 'capitalize',
                          color: exec.status === 'success' ? 'var(--green)' : exec.status === 'failed' ? 'var(--red)' : 'var(--muted)',
                        }}
                      >
                        {exec.status}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </aside>
    )
  }

  const basePayload = fullExec
    ? { id: executionId, trace: fullExec.trace, node_statuses: fullExec.node_statuses, results: fullExec.results }
    : null

  return (
    <aside className="panel inspector debugger">
      <header>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--accent)' }}>
            <polyline points="4 17 10 11 4 5" />
            <line x1="12" y1="19" x2="20" y2="19" />
          </svg>
          <h2>Console</h2>
        </div>
        <div className="inspector-actions">
          <button className="ghost" onClick={() => clear()} title="View other executions">
            All runs
          </button>
          {status === 'failed' && (
            <button className="ghost" onClick={onExplain} disabled={explaining} title="Ask the AI to explain the failure">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#ec4899' }}>
                <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
              </svg>
              <span>Explain</span>
            </button>
          )}
          {terminal && (
            <button className="ghost" onClick={retry} title="Replay: re-run this exact snapshot with the original input">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="1 4 1 10 7 10" />
                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
              </svg>
              <span>Replay</span>
            </button>
          )}
          {terminal && (
            <div style={{ position: 'relative', display: 'inline-block' }}>
              <button
                className="ghost"
                onClick={() => setExportMenuOpen((o) => !o)}
                title="Export execution audit trace"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                <span>Export</span>
              </button>
              {exportMenuOpen && (
                <div
                  style={{
                    position: 'absolute',
                    right: 0,
                    top: '100%',
                    marginTop: 4,
                    zIndex: 100,
                    minWidth: 130,
                    background: 'var(--panel-2, #1e293b)',
                    border: '1px solid var(--border, #334155)',
                    borderRadius: 6,
                    padding: 4,
                    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                  }}
                >
                  <button
                    type="button"
                    className="ghost small"
                    style={{ width: '100%', textAlign: 'left', padding: '6px 10px', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}
                    onClick={() => {
                      setExportMenuOpen(false)
                      api.exportExecution(executionId, 'json')
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="16 18 22 12 16 6" />
                      <polyline points="8 6 2 12 8 18" />
                    </svg>
                    JSON Trace
                  </button>
                  <button
                    type="button"
                    className="ghost small"
                    style={{ width: '100%', textAlign: 'left', padding: '6px 10px', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}
                    onClick={() => {
                      setExportMenuOpen(false)
                      api.exportExecution(executionId, 'csv')
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="20" x2="18" y2="10" />
                      <line x1="12" y1="20" x2="12" y2="4" />
                      <line x1="6" y1="20" x2="6" y2="14" />
                    </svg>
                    CSV Audit
                  </button>
                </div>
              )}
            </div>
          )}
          <button className="ghost" onClick={onClose || clear} title="Close Console" style={{ padding: '4px 7px', minWidth: 28, height: 28, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </header>

      {status === 'waiting_approval' && (
        <div className="banner-inline info" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="6" y="4" width="4" height="16" />
            <rect x="14" y="4" width="4" height="16" />
          </svg>
          <span>{pauseState?.message || 'Waiting for a human decision.'} Approve it in Approvals page.</span>
        </div>
      )}
      {approval && (
        <div className="banner-inline ok">
          {approval.approved ? 'Approved' : 'Rejected'} by user #{approval.approved_by}
          {approval.approved_at ? ` · ${new Date(approval.approved_at).toLocaleString()}` : ''}
        </div>
      )}
      <div className="meta">
        {status && (
          <>
            <span>Status</span>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <Status status={status} live />
            </div>
          </>
        )}
        <span>Execution</span>
        <code className="exec-id" title={executionId}>{executionId}</code>
        <span>Version</span>
        <span>{version ?? '—'}</span>
        <span>Started</span>
        <span>{fmtTime(startedAt)}</span>
        <span>Duration</span>
        <span>{fmtDuration(durationMs)}</span>
      </div>

      {error && (
        <ErrorState
          title={error.code || 'Execution error'}
          description={error.message || JSON.stringify(error)}
          details={
            Array.isArray(error.issues) && error.issues.length > 0
              ? error.issues.map((issue) => `${issue.node_id ? issue.node_id + ': ' : ''}${issue.message || issue.code}`).join('\n')
              : undefined
          }
        />
      )}

      {explain && (
        <div className={`banner-inline ${explain.ok ? 'info' : 'err'}`}>
          {explain.ok && <strong>AI:</strong>} {explain.text}
        </div>
      )}

      <div className="debug-tabs">
        {['timeline', 'steps', 'compare'].map((t) => (
          <button
            key={t}
            type="button"
            className={`debug-tab ${tab === t ? 'active' : ''}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab !== 'compare' && (
        <div className={`debug-body ${tab}`}>
          {tab === 'timeline' ? (
            <ExecutionTimeline
              steps={steps}
              selectedId={selectedStep?.node_id}
              onSelect={(s) => setSelectedStepId(s.node_id)}
            />
          ) : (
            <div className="steps">
              {steps.length === 0 && <p className="hint">No steps yet.</p>}
              {steps.map((s, i) => (
                <button
                  key={`${s.node_id}-${i}`}
                  type="button"
                  className={`step-row ${selectedStep?.node_id === s.node_id ? 'selected' : ''}`}
                  onClick={() => setSelectedStepId(s.node_id)}
                >
                  <span className="step-icon">{STEP_ICON[s.status] || '•'}</span>
                  <span className="step-name">{s._name}</span>
                  <span className="muted">{s.node_type}</span>
                  {Boolean(s.retries) && <span className="step-badge badge-warn">↻{s.retries}</span>}
                  <span className="step-duration">{fmtDuration(s.duration_ms ?? null)}</span>
                </button>
              ))}
            </div>
          )}
          <StepDetail
            execution={fullExec}
            step={selectedStep}
            onRetryNode={onRetryNode}
          />
        </div>
      )}

      {tab === 'compare' && (
        <div className="debug-body compare">
          {!terminal ? (
            <p className="hint">Comparison is available once this run finishes.</p>
          ) : (
            <>
              <label className="cmp-pick">
                Compare with
                <select value={compareWith} onChange={(e) => setCompareWith(e.target.value)}>
                  <option value="">Select an execution…</option>
                  {siblings
                    .filter((h) => h.id !== executionId)
                    .map((h) => (
                      <option key={h.id} value={h.id}>
                        {h.id.slice(-6)} · {h.status} · {fmtTime(h.started_at)}
                      </option>
                    ))}
                </select>
              </label>
              {basePayload ? (
                <ExecutionCompare base={basePayload} cmp={compareData} />
              ) : (
                <p className="hint">Loading this execution…</p>
              )}
            </>
          )}
        </div>
      )}
    </aside>
  )
}
