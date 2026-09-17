import { useState, useEffect, useMemo } from 'react'
import { api } from '../api'
import Button from './shared/Button'
import './NodeAutoRepair.css'

export default function NodeAutoRepair({
  workflowId,
  node,
  errorMessage,
  onApplyFix,
  onClose,
}) {
  const [loading, setLoading] = useState(true)
  const [repairError, setRepairError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    let alive = true
    async function diagnose() {
      if (!workflowId || !node?.id) return
      setLoading(true)
      setRepairError(null)
      try {
        const res = await api.autoFixNode({
          workflow_id: workflowId,
          node_id: node.id,
          error_message: errorMessage || 'Execution failed',
        })
        if (!alive) return
        setResult(res)
      } catch (err) {
        if (!alive) return
        setRepairError(err.message || 'Failed to analyze node failure.')
      } finally {
        if (alive) setLoading(false)
      }
    }
    diagnose()
    return () => {
      alive = false
    }
  }, [workflowId, node?.id, errorMessage])

  const diffs = useMemo(() => {
    if (!result?.suggested_parameters || !node?.parameters) return []
    const oldP = node.parameters || {}
    const newP = result.suggested_parameters || {}
    const allKeys = Array.from(new Set([...Object.keys(oldP), ...Object.keys(newP)]))
    const list = []
    for (const k of allKeys) {
      const vOld = oldP[k]
      const vNew = newP[k]
      const sOld = JSON.stringify(vOld)
      const sNew = JSON.stringify(vNew)
      if (sOld !== sNew) {
        list.push({
          key: k,
          oldVal: vOld === undefined ? '(undefined)' : typeof vOld === 'object' ? JSON.stringify(vOld) : String(vOld),
          newVal: vNew === undefined ? '(removed)' : typeof vNew === 'object' ? JSON.stringify(vNew) : String(vNew),
        })
      }
    }
    return list
  }, [result, node?.parameters])

  return (
    <div className="node-auto-repair-container" role="region" aria-label="AI Auto-Repair Diagnostic">
      <div className="nar-header">
        <div className="nar-title">
          <span>✨</span>
          <span>Flowsmith AI Self-Healing Diagnostic</span>
        </div>
        <button
          type="button"
          className="nem-close"
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
          title="Close Diagnostic"
        >
          ✕
        </button>
      </div>

      {loading && (
        <div className="nar-loading">
          <div className="nar-spinner" />
          <span>Flowsmith AI is diagnosing root cause and evaluating parameter repairs...</span>
        </div>
      )}

      {repairError && (
        <div className="nar-section">
          <div className="nar-cause" style={{ color: '#f87171' }}>
            Diagnostic error: {repairError}
          </div>
        </div>
      )}

      {!loading && result && (
        <>
          <div className="nar-section">
            <div className="nar-label">Diagnosed Root Cause</div>
            <div className="nar-cause">{result.root_cause || 'Parameter mismatch or invalid configuration detected.'}</div>
          </div>

          <div className="nar-section">
            <div className="nar-label">Autonomous Repair Action</div>
            <div className="nar-summary">{result.changes_summary || 'Suggested corrections to parameters.'}</div>
          </div>

          <div className="nar-section">
            <div className="nar-label">Proposed Parameter Modifications</div>
            {diffs.length > 0 ? (
              <table className="nar-diff-table">
                <thead>
                  <tr>
                    <th>Parameter</th>
                    <th>Current Value</th>
                    <th>Proposed Fix</th>
                  </tr>
                </thead>
                <tbody>
                  {diffs.map((d) => (
                    <tr key={d.key}>
                      <td className="nar-param-name">{d.key}</td>
                      <td>
                        <span className="nar-val-old">{d.oldVal}</span>
                      </td>
                      <td>
                        <span className="nar-val-new">{d.newVal}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p style={{ fontSize: 11, color: '#94a3b8', margin: '4px 0' }}>
                Parameters were validated. Re-testing is recommended.
              </p>
            )}
          </div>

          <div className="nar-actions">
            <Button
              className="nar-btn-primary"
              onClick={() => onApplyFix(result.suggested_parameters, true)}
              title="Save repaired configuration and immediately re-test step"
            >
              ✨ Apply Fix & Re-test
            </Button>
            <Button
              variant="secondary"
              onClick={() => onApplyFix(result.suggested_parameters, false)}
              title="Apply fix without re-testing"
            >
              Apply Fix Only
            </Button>
            <Button variant="ghost" onClick={onClose}>
              Dismiss
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
