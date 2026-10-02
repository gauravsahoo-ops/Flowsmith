// StepDetail (Phase 13): everything the debugger knows about one step —
// inputs, outputs, error, attempts/retries, duration, branch taken, API
// status code and the connector that served the call.
//
// "Retry node" re-runs from this step: enabled outright for nodes whose
// catalog metadata declares idempotent operations; requires an explicit
// confirmation otherwise (side effects may repeat).

import { useMemo, useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import JsonTree from './JsonTree'
import {
  connectorIdFromNote,
  deriveBranches,
  extractApiStatus,
  retrySafety,
} from '../utils/debugger'
import { NodeIcon } from './NodeIcons'

function fmtDuration(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function Badge({ tone = 'muted', title, children }) {
  return (
    <span className={`step-badge badge-${tone}`} title={title}>
      {children}
    </span>
  )
}

export default function StepDetail({ execution, step, onRetryNode }) {
  const catalogIndex = useWorkflowStore((s) => s.catalogIndex)
  const [confirmUnsafe, setConfirmUnsafe] = useState(false)

  const nodeType = step?.node_type
  const meta = useMemo(
    () => catalogIndex.get(nodeType) || null,
    [catalogIndex, nodeType],
  )

  if (!step) {
    return <p className="hint">Select a step to inspect its inputs, outputs and errors.</p>
  }

  const branches = deriveBranches(step, execution?.results?.outputs)
  const totalOutputs = branches.reduce((acc, b) => acc + (b.items || 0), 0)
  const stoppedAtNode = step.status === 'success' && branches.length > 0 && totalOutputs === 0
  const isSkipped = step.status === 'skipped'
  const apiStatus = extractApiStatus(step.outputs)
  const connectorId = connectorIdFromNote(step.note)
  const failed = step.status === 'error' || step.status === 'failed'

  // The live canvas knows which node id this step belongs to only when
  // the workflow still contains it; retry targets must exist in the
  // snapshotted graph (backend validates too).
  const existsInWorkflow =
    execution?.workflow_data?.nodes?.some((n) => n.id === step.node_id) ?? false
  const canRetryNode = Boolean(execution && existsInWorkflow && failed)
  const safety = retrySafety(meta, nodeType)

  function onRetryClick() {
    if (!canRetryNode) return
    if (safety === 'safe' || confirmUnsafe) {
      setConfirmUnsafe(false)
      onRetryNode?.(step.node_id)
    } else {
      setConfirmUnsafe(true)
    }
  }

  return (
    <div className="step-detail">
      <header className="sd-head">
        <h4 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <NodeIcon type={nodeType} icon={meta?.icon} size={18} />
          <span>{step.node_id}</span>
          <span className="muted"> · {nodeType}</span>
        </h4>
        <span className={`step-status status-${step.status}`}>{step.status}</span>
      </header>

      <div className="sd-badges">
        <Badge tone="time" title="Wall-clock duration of this step">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 4, verticalAlign: -1 }}>
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
          {fmtDuration(step.duration_ms)}
        </Badge>
        {(step.retries > 0 || (step.attempts ?? 1) > 1) ? (
          <>
            <Badge tone="warn" title="Executed attempts including the first">
              {step.attempts ?? step.retries + 1} attempts
            </Badge>
            <Badge tone="warn" title="Automatic retries inside this node">
              {step.retries} retries
            </Badge>
          </>
        ) : (
          <Badge tone="ok" title="First attempt succeeded">1 attempt</Badge>
        )}
        {apiStatus != null && (
          <Badge
            tone={apiStatus < 400 ? 'ok' : 'err'}
            title="HTTP status returned by the API call"
          >
            API {apiStatus}
          </Badge>
        )}
        {connectorId && (
          <Badge tone="conn" title="Served by this connector">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 4, verticalAlign: -1 }}>
              <path d="M12 2v6"/><path d="M9 2v4"/><path d="M15 2v4"/><path d="M6 8v4a6 6 0 0 0 12 0V8z"/><path d="M12 18v4"/>
            </svg>
            {connectorId}
          </Badge>
        )}
        {branches.map((b) => (
          <Badge
            key={b.handle}
            tone={b.taken ? 'branch' : 'muted'}
            title={`${b.items} item(s) routed to “${b.handle}”`}
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 4, verticalAlign: -1 }}>
              {b.taken ? (
                <>
                  <line x1="6" x2="6" y1="3" y2="15"/>
                  <circle cx="18" cy="6" r="3"/>
                  <circle cx="6" cy="18" r="3"/>
                  <path d="M18 9a9 9 0 0 1-9 9"/>
                </>
              ) : (
                <circle cx="12" cy="12" r="8"/>
              )}
            </svg>
            {b.handle}: {b.items}
          </Badge>
        ))}
      </div>

      {failed && (
        <div className="banner-inline err sd-error">
          <strong>{(typeof step.error === 'object' && step.error?.code) || 'Error'}:</strong>{' '}
          {typeof step.error === 'object' && step.error !== null
            ? (step.error.message || JSON.stringify(step.error))
            : String(step.error || 'Step execution failed')}
        </div>
      )}

      {isSkipped && (
        <div className="banner-inline info sd-skipped" style={{ background: 'rgba(148, 163, 184, 0.12)', borderColor: 'rgba(148, 163, 184, 0.3)', color: '#cbd5e1' }}>
          <strong style={{ color: '#f1f5f9', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" x2="19.07" y1="4.93" y2="19.07"/></svg>
            Step Skipped:
          </strong>{' '}
          {step.note || 'No input items arrived; step was not executed.'}
        </div>
      )}

      {stoppedAtNode && (
        <div className="banner-inline warn sd-stopped" style={{ background: 'rgba(245, 158, 11, 0.12)', borderColor: 'rgba(245, 158, 11, 0.3)', color: '#fde68a' }}>
          <strong style={{ color: '#fbbf24', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="14" height="14" x="5" y="5" rx="2"/></svg>
            Workflow Stopped Here:
          </strong>{' '}
          This node executed successfully and produced 0 items. Downstream connected nodes were skipped because there was no data to continue.
        </div>
      )}

      {canRetryNode && (
        <div className={`sd-retry ${safety === 'caution' ? 'caution' : ''}`}>
          {!confirmUnsafe ? (
            <>
              <button type="button" className="ghost" onClick={onRetryClick} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
                Retry from here
              </button>
              {safety === 'caution' && (
                <span className="hint">
                  This node is not marked idempotent — retrying may repeat side effects.
                </span>
              )}
            </>
          ) : (
            <>
              <span className="hint">
                Retry anyway? Side effects of this node may repeat.
              </span>
              <button type="button" className="danger" onClick={onRetryClick}>
                Retry now
              </button>
              <button type="button" className="ghost" onClick={() => setConfirmUnsafe(false)}>
                Cancel
              </button>
            </>
          )}
        </div>
      )}

      <h5>Inputs</h5>
      <JsonTree value={step.inputs} />
      <h5>Outputs</h5>
      <JsonTree value={step.outputs} />
    </div>
  )
}
