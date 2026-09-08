// TestsPanel: first-class workflow testing (Phase 14).
//
// Saved tests per workflow = test data (trigger items) + HTTP mock rules
// + assertions + an expected-outputs regression snapshot. Running a test
// executes the workflow with mocks enforced (unmatched outbound calls
// are BLOCKED — production is never contacted during a test run) and
// evaluates the spec into a PASS/FAIL/DIFF report shown below.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useWorkflowStore } from '../stores/workflowStore'
import {
  badgeClass,
  formatCheckLabel,
  formatDiffEntry,
  summarizeReport,
} from '../utils/testReport'

const TERMINAL = new Set(['success', 'failed', 'cancelled', 'timeout'])

function pretty(value) {
  if (value === null || value === undefined) return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function parseJsonField(text, fallback) {
  const trimmed = (text || '').trim()
  if (!trimmed) return null
  try {
    return JSON.parse(trimmed)
  } catch {
    return fallback // keep the last good value; the API validates the rest
  }
}

export default function TestsPanel({ open, onClose }) {
  const workflowId = useWorkflowStore((s) => s.workflow?.id)
  const [tests, setTests] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)

  // Editor state for the selected test.
  const [name, setName] = useState('')
  const [testData, setTestData] = useState('')
  const [mocks, setMocks] = useState('')
  const [assertions, setAssertions] = useState('')
  const [expectedOutputs, setExpectedOutputs] = useState('')

  // Live run state: poll the execution until terminal, then show report.
  const [runningTestId, setRunningTestId] = useState(null)
  const [report, setReport] = useState(null)
  const pollRef = useRef(null)

  const loadTests = useCallback(async () => {
    if (!workflowId) {
      setTests([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await api.listWorkflowTests(workflowId)
      setTests(data || [])
    } catch (err) {
      setError(err.message)
      setTests([])
    } finally {
      setLoading(false)
    }
  }, [workflowId])

  useEffect(() => {
    if (open) loadTests()
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current)
    }
  }, [open, loadTests])

  function selectTest(t) {
    setSelectedId(t ? t.id : null)
    setName(t ? t.name : '')
    setTestData(t && t.test_data !== undefined && t.test_data !== null ? pretty(t.test_data) : '')
    setMocks(t && t.mocks?.length ? pretty(t.mocks) : '')
    setAssertions(t && t.assertions?.length ? pretty(t.assertions) : '')
    setExpectedOutputs(t && t.expected_outputs ? pretty(t.expected_outputs) : '')
    setReport(null)
    setNotice(null)
    setError(null)
  }

  function newTest() {
    selectTest(null)
    setName('New test')
    setTestData('')
    setMocks('')
    setAssertions(JSON.stringify([{ type: 'workflow_succeeded' }], null, 2))
    setExpectedOutputs('')
  }

  async function save() {
    if (!workflowId || !name.trim()) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const payload = {
        name: name.trim(),
        test_data: parseJsonField(testData, undefined),
        mocks: parseJsonField(mocks, undefined) || [],
        assertions: parseJsonField(assertions, undefined) || [],
        expected_outputs: parseJsonField(expectedOutputs, undefined) || null,
      }
      if (payload.test_data === undefined) delete payload.test_data
      let saved
      if (selectedId) {
        saved = await api.updateWorkflowTest(workflowId, selectedId, payload)
      } else {
        saved = await api.createWorkflowTest(workflowId, payload)
        setSelectedId(saved.id)
      }
      setNotice(`Saved “${saved.name}”.`)
      await loadTests()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(t) {
    if (!window.confirm(`Delete test “${t.name}”?`)) return
    setError(null)
    try {
      await api.deleteWorkflowTest(workflowId, t.id)
      if (selectedId === t.id) selectTest(null)
      await loadTests()
    } catch (err) {
      setError(err.message)
    }
  }

  /** Capture the last finished execution's outputs as the regression snapshot. */
  async function captureSnapshot() {
    if (!workflowId) return
    setBusy(true)
    setError(null)
    try {
      const execs = await api.listExecutions({ workflowId, pageSize: 20 })
      const done = (execs || []).find((e) =>
        e.status === 'success' && e.trigger !== 'test',
      )
      if (!done) {
        setError('No successful non-test execution found to snapshot.')
        return
      }
      const full = await api.getExecution(done.id)
      const outputs = full?.results?.outputs
      if (!outputs || !Object.keys(outputs).length) {
        setError('That execution has no node outputs to snapshot.')
        return
      }
      setExpectedOutputs(pretty(outputs))
      setNotice(`Captured outputs from execution ${done.id.slice(0, 12)}…`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function runTest(t) {
    setError(null)
    setNotice(null)
    setReport(null)
    setRunningTestId(t.id)
    try {
      const { execution_id: executionId } = await api.runWorkflowTest(workflowId, t.id)
      pollRef.current = setInterval(async () => {
        try {
          const rec = await api.getExecution(executionId)
          if (!TERMINAL.has(rec.status)) return
          clearInterval(pollRef.current)
          setRunningTestId(null)
          setReport(rec.results?.tests || { verdict: 'FAIL', checks: [], summary: 'no report persisted' })
        } catch (err) {
          clearInterval(pollRef.current)
          setRunningTestId(null)
          setError(err.message)
        }
      }, 1000)
    } catch (err) {
      setRunningTestId(null)
      setError(err.message)
    }
  }

  if (!open) return null

  const summary = summarizeReport(report)
  const selected = tests.find((t) => t.id === selectedId) || null

  return (
    <aside className="panel testspanel">
      <header>
        <h2>Workflow tests</h2>
        <button className="ghost" onClick={onClose} title="Close">
          ✕
        </button>
      </header>
      <p className="hint">
        Saved test runs for this workflow. Mocked outbound HTTP never reaches a real
        provider; unmatched calls are blocked so tests can&apos;t touch production data.
      </p>

      {!workflowId && <p className="hint">Open or create a workflow first.</p>}

      {error && <div className="banner-inline err">{error}</div>}
      {notice && <div className="banner-inline ok">{notice}</div>}

      {workflowId && (
        <>
          <div className="tests-toolbar">
            <button className="ghost" onClick={newTest}>＋ New test</button>
            <button className="ghost" onClick={loadTests} disabled={loading}>⟳</button>
          </div>

          <ul className="tests-list">
            {tests.map((t) => (
              <li key={t.id} className={t.id === selectedId ? 'is-selected' : ''}>
                <button className="tests-item" onClick={() => selectTest(t)}>
                  <span className="tests-name">{t.name}</span>
                  <span className="tests-meta">
                    {(t.assertions?.length || 0)} checks · {(t.mocks?.length || 0)} mocks
                  </span>
                </button>
                <button
                  className="primary tests-run"
                  onClick={() => runTest(t)}
                  disabled={busy || runningTestId === t.id}
                  title="Run this test (mock mode)"
                >
                  {runningTestId === t.id ? '⏳' : '▶ Test'}
                </button>
                <button className="ghost" onClick={() => remove(t)} title="Delete test">🗑</button>
              </li>
            ))}
            {!loading && tests.length === 0 && (
              <li className="hint">No tests yet — create one.</li>
            )}
          </ul>

          {(selected || !selectedId) && (
            <section className="tests-editor">
              <h3>{selectedId ? 'Edit test' : 'New test'}</h3>
              <label className="tests-field">
                Name
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <label className="tests-field">
                Test data <span className="hint">(trigger items JSON)</span>
                <textarea rows={4} value={testData} onChange={(e) => setTestData(e.target.value)}
                  placeholder='{"user_id": 1}' spellCheck="false" />
              </label>
              <label className="tests-field">
                Mock responses <span className="hint">(matched rules answer locally)</span>
                <textarea rows={5} value={mocks} onChange={(e) => setMocks(e.target.value)}
                  placeholder={'[{"url_pattern": "api.example.com/v1/users/*",\n  "method": "GET", "status": 200,\n  "body": {"name": "Ada"}}]'} spellCheck="false" />
              </label>
              <label className="tests-field">
                Assertions <span className="hint">(PASS / FAIL)</span>
                <textarea rows={6} value={assertions} onChange={(e) => setAssertions(e.target.value)}
                  placeholder={'[{"type": "workflow_succeeded"},\n {"type": "output_equals", "node_id": "fetch",\n  "path": "0.body.name", "expected": "Ada"}]'} spellCheck="false" />
              </label>
              <label className="tests-field">
                Expected outputs <span className="hint">(regression snapshot → DIFF on drift)</span>
                <textarea rows={5} value={expectedOutputs}
                  onChange={(e) => setExpectedOutputs(e.target.value)}
                  placeholder='{"node_id": {"main": []}}' spellCheck="false" />
              </label>
              <div className="tests-actions">
                <button className="ghost" onClick={captureSnapshot} disabled={busy}>
                  📸 Capture from last run
                </button>
                <button className="primary" onClick={save} disabled={busy || !name.trim()}>
                  Save test
                </button>
                {selectedId && selected && (
                  <button className="primary" onClick={() => runTest(selected)}
                    disabled={busy || runningTestId === selected.id}>
                    {runningTestId === selected.id ? 'Running…' : '▶ Run test'}
                  </button>
                )}
              </div>
            </section>
          )}

          {report && (
            <section className="tests-report">
              <h3>
                Last run:{' '}
                <span className={`report-verdict ${badgeClass(summary.verdict)}`}>
                  {summary.verdict}
                </span>
                <span className="tests-meta"> {report.summary}</span>
              </h3>
              <ul className="checks-list">
                {report.checks.map((c, i) => (
                  <li key={i} className={`check check-${c.result.toLowerCase()}`}>
                    <span className={`check-badge ${badgeClass(c.result)}`}>{c.result}</span>
                    <div className="check-body">
                      <div className="check-label">{formatCheckLabel(c)}</div>
                      <div className="check-message">{c.message}</div>
                      {c.diff?.length > 0 && (
                        <pre className="check-diff">
                          {c.diff.map((d) => formatDiffEntry(d)).join('\n')}
                        </pre>
                      )}
                    </div>
                  </li>
                ))}
                {report.checks.length === 0 && (
                  <li className="hint">No checks were evaluated.</li>
                )}
              </ul>
            </section>
          )}
        </>
      )}
    </aside>
  )
}
