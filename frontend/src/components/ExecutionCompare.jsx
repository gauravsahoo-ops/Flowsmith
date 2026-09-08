// ExecutionCompare (Phase 13): side-by-side diff of two executions of
// the same workflow — status/duration/retry deltas and output changes
// per node. Purely read-only over the two execution payloads.

import { useMemo } from 'react'
import { diffExecutions, MASK } from '../utils/debugger'

function fmt(ms) {
  if (ms == null) return '—'
  if (Math.abs(ms) < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function Delta({ value }) {
  if (value == null) return <span className="muted">—</span>
  if (Math.abs(value) < 1) return <span className="muted">±0</span>
  const cls = value > 0 ? 'delta-worse' : 'delta-better'
  const sign = value > 0 ? '+' : ''
  return <span className={cls}>{sign}{fmt(value)}</span>
}

export default function ExecutionCompare({ base, cmp }) {
  const rows = useMemo(() => diffExecutions(base, cmp), [base, cmp])

  if (!base || !cmp) {
    return <p className="hint">Pick a second execution above to compare.</p>
  }

  const changed = rows.filter((r) => r.outputsChanged).length

  return (
    <div className="exec-compare">
      <div className="cmp-meta">
        <code>{base.id}</code> vs <code>{cmp.id}</code>
        <span className="hint">
          {' '}· {rows.length} nodes · {changed} output change{changed === 1 ? '' : 's'}
        </span>
      </div>
      <table className="cmp-table">
        <thead>
          <tr>
            <th>Node</th>
            <th>{base.id.slice(-6)}</th>
            <th>{cmp.id.slice(-6)}</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Δ</th>
            <th>Retries</th>
            <th>Outputs</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.nodeId} className={r.inBoth ? '' : 'only-one'}>
              <td className="cmp-node">{r.nodeId}</td>
              <td>{fmt(r.baseDuration)}</td>
              <td>{fmt(r.cmpDuration)}</td>
              <td>
                <span className={`step-status status-${r.baseStatus}`}>{r.baseStatus}</span>
                {' → '}
                <span className={`step-status status-${r.cmpStatus}`}>{r.cmpStatus}</span>
              </td>
              <td><Delta value={r.durationDelta} /></td>
              <td>{r.baseRetries} → {r.cmpRetries}</td>
              <td>
                {r.outputsChanged
                  ? <span className="delta-worse">changed</span>
                  : <span className="muted">same</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint cmp-note">
        Output comparison uses structural equality on the stored (masked)
        payloads; values like {MASK} compare equal to any masked secret.
      </p>
    </div>
  )
}
