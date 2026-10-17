import React, { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import {
  badgeClass,
  formatCheckLabel,
  formatDiffEntry,
  summarizeReport,
} from '../utils/testReport'
import './WorkflowTestsModal.css'

const TERMINAL_STATUSES = new Set(['success', 'failed', 'cancelled', 'timeout'])

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
    return fallback
  }
}

export default function WorkflowTestsModal({ isOpen, onClose, workflowId, workflowName }) {
  const [tests, setTests] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)

  // Tab: 'data' | 'mocks' | 'assertions' | 'snapshot'
  const [activeTab, setActiveTab] = useState('data')

  // Editor fields
  const [name, setName] = useState('')
  const [testData, setTestData] = useState('')
  const [mocks, setMocks] = useState('')
  const [assertions, setAssertions] = useState('')
  const [expectedOutputs, setExpectedOutputs] = useState('')

  // Running test state
  const [runningTestId, setRunningTestId] = useState(null)
  const [report, setReport] = useState(null)
  const pollRef = useRef(null)

  const selectTest = useCallback((t) => {
    setSelectedId(t ? t.id : null)
    setName(t ? t.name : '')
    setTestData(t && t.test_data !== undefined && t.test_data !== null ? pretty(t.test_data) : '')
    setMocks(t && t.mocks?.length ? pretty(t.mocks) : '')
    setAssertions(t && t.assertions?.length ? pretty(t.assertions) : '')
    setExpectedOutputs(t && t.expected_outputs ? pretty(t.expected_outputs) : '')
    setReport(null)
    setNotice(null)
    setError(null)
  }, [])

  const loadTests = useCallback(async () => {
    if (!workflowId) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.listWorkflowTests(workflowId)
      const list = Array.isArray(res) ? res : (res?.data || [])
      setTests(list)
      if (list.length > 0) {
        // If nothing selected or currently selected was removed, pick first
        setSelectedId((current) => {
          const matched = list.find((item) => item.id === current)
          if (matched) {
            return current
          }
          selectTest(list[0])
          return list[0].id
        })
      }
    } catch (err) {
      setError(err.message || 'Failed to load workflow tests.')
      setTests([])
    } finally {
      setLoading(false)
    }
  }, [workflowId, selectTest])

  useEffect(() => {
    if (isOpen) {
      loadTests()
    } else {
      if (pollRef.current) clearInterval(pollRef.current)
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [isOpen, loadTests])

  useEffect(() => {
    if (!isOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  function handleNewTest() {
    setSelectedId(null)
    setName('New Regression Test')
    setTestData(JSON.stringify({ user_id: 1, action: 'test' }, null, 2))
    setMocks(JSON.stringify([{
      url_pattern: 'https://api.example.com/*',
      method: 'GET',
      status: 200,
      body: { ok: true, mocked: true }
    }], null, 2))
    setAssertions(JSON.stringify([{ type: 'workflow_succeeded' }], null, 2))
    setExpectedOutputs('')
    setReport(null)
    setNotice(null)
    setError(null)
    setActiveTab('data')
  }

  async function handleSave() {
    if (!workflowId || !name.trim()) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const payload = {
        name: name.trim(),
        test_data: parseJsonField(testData, {}),
        mocks: parseJsonField(mocks, []) || [],
        assertions: parseJsonField(assertions, []) || [],
        expected_outputs: parseJsonField(expectedOutputs, null),
      }
      let saved
      if (selectedId) {
        saved = await api.updateWorkflowTest(workflowId, selectedId, payload)
      } else {
        saved = await api.createWorkflowTest(workflowId, payload)
        setSelectedId(saved.id)
      }
      setNotice(`Saved test "${saved.name || name}".`)
      await loadTests()
    } catch (err) {
      setError(err.message || 'Failed to save test.')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(testId) {
    if (!testId || !window.confirm('Delete this test case?')) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteWorkflowTest(workflowId, testId)
      if (selectedId === testId) {
        setSelectedId(null)
      }
      await loadTests()
    } catch (err) {
      setError(err.message || 'Failed to delete test.')
    } finally {
      setBusy(false)
    }
  }

  async function handleCaptureSnapshot() {
    if (!workflowId) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.listExecutions({ workflowId, pageSize: 20 })
      const execs = Array.isArray(res) ? res : (res?.data || [])
      const done = execs.find((e) => e.status === 'success' && e.trigger !== 'test')
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
      setNotice(`Captured outputs from execution ${done.id.slice(0, 8)}…`)
    } catch (err) {
      setError(err.message || 'Failed to capture snapshot.')
    } finally {
      setBusy(false)
    }
  }

  async function handleRunTest(testId) {
    if (!testId) return
    setError(null)
    setNotice(null)
    setReport(null)
    setRunningTestId(testId)
    try {
      const runRes = await api.runWorkflowTest(workflowId, testId)
      const executionId = runRes.execution_id || runRes.id
      if (!executionId) {
        throw new Error('Test run initiated but no execution ID returned.')
      }

      pollRef.current = setInterval(async () => {
        try {
          const rec = await api.getExecution(executionId)
          if (!TERMINAL_STATUSES.has(rec.status)) return
          clearInterval(pollRef.current)
          setRunningTestId(null)
          setReport(rec.results?.tests || {
            verdict: rec.status === 'success' ? 'PASS' : 'FAIL',
            checks: [],
            summary: `Execution finished with status: ${rec.status}`
          })
        } catch (pollErr) {
          clearInterval(pollRef.current)
          setRunningTestId(null)
          setError(pollErr.message)
        }
      }, 1000)
    } catch (err) {
      setRunningTestId(null)
      setError(err.message || 'Failed to initiate test run.')
    }
  }

  if (!isOpen) return null

  const summary = summarizeReport(report)
  const isEditing = Boolean(selectedId || name)
  const isRunning = runningTestId !== null

  const mocksCount = (parseJsonField(mocks, []) || []).length
  const assertionsCount = (parseJsonField(assertions, []) || []).length

  return createPortal(
    <div className="tests-backdrop" onClick={onClose}>
      <aside className="tests-drawer" aria-label="Workflow Tests" onClick={(e) => e.stopPropagation()}>
        {/* Top Header */}
        <div className="tests-drawer-header">
          <div className="tests-drawer-header-left">
            <div className="tests-drawer-icon-wrap" aria-hidden="true">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14.5 2v6.5L19 17a2.5 2.5 0 0 1-2.2 3.8H7.2A2.5 2.5 0 0 1 5 17l4.5-8.5V2" />
                <path d="M8.5 2h7" />
                <path d="M7 16h10" />
              </svg>
            </div>
            <div className="tests-drawer-title-group">
              <h2 className="tests-drawer-title">Workflow Tests</h2>
              <span className="tests-count-badge">
                {tests.length} suite{tests.length === 1 ? '' : 's'}
              </span>
            </div>
          </div>
          <div className="tests-drawer-header-right">
            <button
              type="button"
              className="tests-header-btn-new"
              onClick={handleNewTest}
              title="Create new test case"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              <span>New</span>
            </button>
            <button
              type="button"
              className="tests-drawer-close-btn"
              onClick={onClose}
              title="Close panel (Esc)"
              aria-label="Close panel"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* Test Case Switcher Toolbar */}
        <div className="tests-switcher-bar">
          <select
            className="tests-select"
            value={selectedId || ''}
            onChange={(e) => {
              const found = tests.find((t) => t.id === e.target.value)
              if (found) selectTest(found)
            }}
            disabled={tests.length === 0}
          >
            {tests.length === 0 ? (
              <option value="">No saved tests</option>
            ) : (
              tests.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name || 'Untitled Test'} · {(t.assertions?.length || 0)} checks
                </option>
              ))
            )}
          </select>

          {selectedId && (
            <button
              type="button"
              className="tests-quick-run-btn"
              onClick={() => handleRunTest(selectedId)}
              disabled={busy || isRunning}
              title="Run this test case in mock sandbox"
            >
              {runningTestId === selectedId ? (
                <>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="tests-spin">
                    <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                  </svg>
                  <span>Running…</span>
                </>
              ) : (
                <>
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  <span>Run</span>
                </>
              )}
            </button>
          )}

          {/* Refresh Tests button */}
          <button
            type="button"
            className="tests-refresh-icon-btn"
            onClick={loadTests}
            disabled={loading}
            title="Refresh test list"
            aria-label="Refresh tests"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={loading ? 'tests-spin' : ''}>
              <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.3" />
            </svg>
          </button>
        </div>

        {/* Tab Navigation Strip */}
        <div className="tests-tabs-strip" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'data'}
            className={`tests-tab-item ${activeTab === 'data' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('data')}
          >
            Payload
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'mocks'}
            className={`tests-tab-item ${activeTab === 'mocks' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('mocks')}
          >
            <span>HTTP Mocks</span>
            <span className="tests-tab-count">{mocksCount}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'assertions'}
            className={`tests-tab-item ${activeTab === 'assertions' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('assertions')}
          >
            <span>Assertions</span>
            <span className="tests-tab-count">{assertionsCount}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'snapshot'}
            className={`tests-tab-item ${activeTab === 'snapshot' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('snapshot')}
          >
            Snapshot
          </button>
        </div>

        {/* Scrollable Body */}
        <div className="tests-drawer-body">
          {error && (
            <div className="tests-banner err">
              <span>{error}</span>
              <button type="button" className="tests-banner-dismiss" onClick={() => setError(null)}>Dismiss</button>
            </div>
          )}
          {notice && (
            <div className="tests-banner ok">
              <span>{notice}</span>
              <button type="button" className="tests-banner-dismiss" onClick={() => setNotice(null)}>Dismiss</button>
            </div>
          )}

          {isEditing ? (
            <>
              {/* Test Name Input */}
              <div className="tests-field-group">
                <div className="tests-label">
                  <span>TEST CASE NAME</span>
                  {selectedId ? <span style={{ opacity: 0.6, fontSize: '10px' }}>ID: {selectedId.slice(0, 8)}</span> : <span style={{ color: '#818cf8', fontSize: '10px' }}>UNSAVED DRAFT</span>}
                </div>
                <input
                  type="text"
                  className="tests-name-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Verify CRM Sync with Mocked API"
                  spellCheck="false"
                />
              </div>

              {/* Tab Editor Content */}
              {activeTab === 'data' && (
                <div className="tests-field-group">
                  <p className="tests-field-desc">
                    Injected into the trigger node during execution. Simulates incoming webhook payloads or manual triggers.
                  </p>
                  <div className="tests-code-wrap">
                    <textarea
                      className="tests-code-editor"
                      rows={10}
                      value={testData}
                      onChange={(e) => setTestData(e.target.value)}
                      placeholder={'{\n  "event": "customer.created",\n  "data": { "id": "cus_123", "email": "test@example.com" }\n}'}
                      spellCheck="false"
                    />
                  </div>
                </div>
              )}

              {activeTab === 'mocks' && (
                <div className="tests-field-group">
                  <p className="tests-field-desc">
                    Mock rules for outbound HTTP requests. Any unmatched outbound HTTP request is automatically blocked to safeguard external systems.
                  </p>
                  <div className="tests-code-wrap">
                    <textarea
                      className="tests-code-editor"
                      rows={10}
                      value={mocks}
                      onChange={(e) => setMocks(e.target.value)}
                      placeholder={'[\n  {\n    "url_pattern": "https://api.stripe.com/v1/*",\n    "method": "GET",\n    "status": 200,\n    "body": { "id": "cus_123", "balance": 0 }\n  }\n]'}
                      spellCheck="false"
                    />
                  </div>
                </div>
              )}

              {activeTab === 'assertions' && (
                <div className="tests-field-group">
                  <p className="tests-field-desc">
                    Assertions evaluated on completion: <code>workflow_succeeded</code>, <code>output_equals</code>, <code>node_executed</code>.
                  </p>
                  <div className="tests-code-wrap">
                    <textarea
                      className="tests-code-editor"
                      rows={10}
                      value={assertions}
                      onChange={(e) => setAssertions(e.target.value)}
                      placeholder={'[\n  { "type": "workflow_succeeded" },\n  { "type": "output_equals", "node_id": "filter_step", "path": "0.status", "expected": "active" }\n]'}
                      spellCheck="false"
                    />
                  </div>
                </div>
              )}

              {activeTab === 'snapshot' && (
                <div className="tests-field-group">
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                    <p className="tests-field-desc" style={{ margin: 0 }}>
                      Baseline snapshot of node outputs. Deviations are flagged as regression diffs.
                    </p>
                    <button
                      type="button"
                      className="tests-btn-snapshot"
                      onClick={handleCaptureSnapshot}
                      disabled={busy}
                      title="Extract node outputs from the latest successful execution"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                        <circle cx="12" cy="13" r="4" />
                      </svg>
                      <span>Capture</span>
                    </button>
                  </div>
                  <div className="tests-code-wrap">
                    <textarea
                      className="tests-code-editor"
                      rows={10}
                      value={expectedOutputs}
                      onChange={(e) => setExpectedOutputs(e.target.value)}
                      placeholder={'{\n  "httpRequestNode": {\n    "main": [{ "id": 123, "name": "Ada" }]\n  }\n}'}
                      spellCheck="false"
                    />
                  </div>
                </div>
              )}

              {/* Test Run Report Section */}
              {report && (
                <div className="tests-report-section">
                  <div className="tests-report-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span className={`tests-report-verdict ${(summary.verdict || 'FAIL').toLowerCase()}`}>
                        {summary.verdict === 'PASS' && (
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                        {summary.verdict === 'FAIL' && (
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                          </svg>
                        )}
                        {summary.verdict === 'DIFF' && (
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                          </svg>
                        )}
                        <span>{summary.verdict}</span>
                      </span>
                      <span className="tests-report-summary">
                        {summary.passed} passed · {summary.failed} failed · {summary.diffs} diffs
                      </span>
                    </div>
                  </div>

                  <ul className="tests-checks-list">
                    {(report.checks || []).map((check, idx) => (
                      <li key={idx} className="tests-check-row">
                        <span className={`tests-check-status-chip ${(check.result || 'fail').toLowerCase()}`}>
                          {check.result}
                        </span>
                        <div className="tests-check-info">
                          <div className="tests-check-label">{formatCheckLabel(check)}</div>
                          {check.message && <div className="tests-check-msg">{check.message}</div>}
                          {check.diff?.length > 0 && (
                            <pre className="tests-diff-box">
                              {check.diff.map((d) => formatDiffEntry(d)).join('\n')}
                            </pre>
                          )}
                        </div>
                      </li>
                    ))}
                    {(!report.checks || report.checks.length === 0) && (
                      <li style={{ padding: '8px 10px', fontSize: '11.5px', color: '#94a3b8', fontStyle: 'italic' }}>
                        Execution finished with status: {report.verdict || 'PASS'}. No assertions configured.
                      </li>
                    )}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <div className="tests-empty-card">
              <div className="tests-empty-icon" aria-hidden="true">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14.5 2v6.5L19 17a2.5 2.5 0 0 1-2.2 3.8H7.2A2.5 2.5 0 0 1 5 17l4.5-8.5V2" />
                  <path d="M8.5 2h7" />
                  <path d="M7 16h10" />
                </svg>
              </div>
              <h3 className="tests-empty-title">No Test Case Selected</h3>
              <p className="tests-empty-desc">
                Configure isolated test cases with mock HTTP rules, trigger payloads, and regression output snapshots.
              </p>
              <button
                type="button"
                className="tests-header-btn-new"
                style={{ padding: '6px 16px', fontSize: '12px' }}
                onClick={handleNewTest}
              >
                Create Test Case
              </button>
            </div>
          )}
        </div>

        {/* Drawer Footer Actions */}
        {isEditing && (
          <div className="tests-drawer-footer">
            <div className="tests-footer-left">
              {selectedId && (
                <button
                  type="button"
                  className="tests-btn-delete"
                  onClick={() => handleDelete(selectedId)}
                  disabled={busy || isRunning}
                  title="Delete this test case"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                  <span>Delete</span>
                </button>
              )}
            </div>

            <div className="tests-footer-right">
              <button
                type="button"
                className="tests-btn-save"
                onClick={handleSave}
                disabled={busy || !name.trim()}
              >
                Save
              </button>

              {selectedId && (
                <button
                  type="button"
                  className="tests-btn-run"
                  onClick={() => handleRunTest(selectedId)}
                  disabled={busy || isRunning}
                >
                  {runningTestId === selectedId ? (
                    <>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="tests-spin">
                        <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                      </svg>
                      <span>Running…</span>
                    </>
                  ) : (
                    <>
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
                        <polygon points="5 3 19 12 5 21 5 3" />
                      </svg>
                      <span>Run Test</span>
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        )}
      </aside>
    </div>,
    document.body
  )
}
