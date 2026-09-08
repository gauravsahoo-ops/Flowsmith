// ExecutionTimeline (Phase 13): a horizontal span chart of the run.
//
// Each step becomes one bar: left/width derived from started_at +
// duration_ms relative to the run window; colour by status; click to
// select the step in the debugger. A lane list sits underneath so the
// same component doubles as the compact step index.

import { useMemo } from 'react'
import { computeSpans, totalSpanMs } from '../utils/debugger'

function fmt(ms) {
  if (ms == null) return ''
  if (ms < 1) return '0ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

const STATUS_CLASS = {
  success: 'ok',
  error: 'err',
  failed: 'err',
  cancelled: 'cancel',
  skipped: 'skip',
  running: 'run',
  retry: 'run',
}

export default function ExecutionTimeline({ steps, selectedId, onSelect }) {
  const spans = useMemo(() => computeSpans(steps), [steps])
  const total = totalSpanMs(spans)

  if (!spans.length) {
    return <p className="hint">No completed steps yet — the timeline fills in live as nodes finish.</p>
  }

  return (
    <div className="exec-timeline">
      <div className="tl-ruler">
        <span>0</span>
        <span className="tl-total">{fmt(total)} total</span>
      </div>
      {spans.map(({ step, leftPct, widthPct }) => {
        const cls = STATUS_CLASS[step.status] || 'idle'
        const selected = selectedId != null && step.node_id === selectedId
        return (
          <button
            key={`${step.node_id}`}
            type="button"
            className={`tl-row ${selected ? 'selected' : ''}`}
            title={`${step.node_id} · ${step.status} · ${fmt(step.duration_ms)}${step.retries ? ` · ${step.retries} retries` : ''}`}
            onClick={() => onSelect?.(step)}
          >
            <span className="tl-label">{step.node_id}</span>
            <span className="tl-track">
              <span
                className={`tl-bar bar-${cls}${step.retries ? ' had-retries' : ''}`}
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
              />
            </span>
            <span className="tl-duration">{fmt(step.duration_ms)}</span>
          </button>
        )
      })}
    </div>
  )
}
