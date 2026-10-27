// Visual Expression Autocomplete & Live Evaluation Modal/Drawer
// Provides visual variable tree autocomplete, pipe helpers,
// and real-time live preview evaluation against upstream node context.

import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import './ExpressionHelper.css'

const BASE_VARS = [
  { name: '$json', snippet: '{{ $json }}', hint: 'first input item of this node', category: 'Input' },
  { name: '$execution.id', snippet: '{{ $execution.id }}', hint: 'current execution id', category: 'System' },
  { name: '$workflow.id', snippet: '{{ $workflow.id }}', hint: 'workflow id', category: 'System' },
  { name: '$now', snippet: '{{ $now }}', hint: 'current ISO timestamp', category: 'System' },
]

const COMMON_PIPES = [
  { name: 'upper', snippet: '| upper', hint: 'Convert to uppercase' },
  { name: 'lower', snippet: '| lower', hint: 'Convert to lowercase' },
  { name: 'trim', snippet: '| trim', hint: 'Strip leading/trailing whitespace' },
  { name: 'length', snippet: '| length', hint: 'Get string/array length' },
  { name: 'int', snippet: '| int', hint: 'Cast to integer' },
  { name: 'float', snippet: '| float', hint: 'Cast to float' },
  { name: 'bool', snippet: '| bool', hint: 'Cast to boolean' },
  { name: 'json', snippet: '| json', hint: 'Serialize to JSON string' },
]

export default function ExpressionHelper({ workflowId, nodeId, initialExpression = '', onApply = null }) {
  const [isOpen, setIsOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [ctx, setCtx] = useState(null)
  const [copied, setCopied] = useState('')

  // Live Builder State
  const [expression, setExpression] = useState(initialExpression || '{{ $json }}')
  const [previewResult, setPreviewResult] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState(null)
  const debounceTimer = useRef(null)

  useEffect(() => {
    if (!isOpen || !workflowId || ctx) return
    let alive = true
    api
      .expressionContext(workflowId)
      .then((data) => alive && setCtx(data))
      .catch((err) => {
        if (alive) console.debug('[flowsmith] expression context unavailable', err)
      })
    return () => {
      alive = false
    }
  }, [isOpen, workflowId, ctx])

  useEffect(() => {
    if (!isOpen) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setIsOpen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen])

  // Real-time live expression evaluation
  const evaluateExpression = useCallback(
    async (expr) => {
      if (!workflowId || !expr || !expr.includes('{{')) {
        setPreviewResult(null)
        setPreviewError(null)
        return
      }
      setPreviewLoading(true)
      setPreviewError(null)
      setPreviewResult(null)
      try {
        const res = await api.previewExpression(workflowId, {
          expression: expr,
          node_id: nodeId || '',
        })
        setPreviewResult(res)
      } catch (err) {
        setPreviewError(err.message)
      } finally {
        setPreviewLoading(false)
      }
    },
    [workflowId, nodeId]
  )

  useEffect(() => {
    if (!isOpen) return
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    debounceTimer.current = setTimeout(() => {
      evaluateExpression(expression)
    }, 280)
    return () => clearTimeout(debounceTimer.current)
  }, [expression, isOpen, evaluateExpression])

  const insertSnippet = (snippet) => {
    setExpression((prev) => {
      if (!prev.trim()) return snippet
      if (snippet.startsWith('|')) {
        // Appending pipe inside or after existing {{ ... }}
        if (prev.endsWith('}}')) {
          return prev.slice(0, -2).trimEnd() + ' ' + snippet + ' }}'
        }
        return prev + ' ' + snippet
      }
      return prev + (prev.endsWith(' ') ? '' : ' ') + snippet
    })
  }

  const copy = (text) => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(text)
      setTimeout(() => setCopied(''), 1500)
    })
  }

  const filteredPipes = useMemo(() => {
    const pipes = (ctx?.pipes || []).map((p) => {
      const match = COMMON_PIPES.find((cp) => cp.name === p)
      return match || { name: p, snippet: `| ${p}`, hint: `Pipe: ${p}` }
    })
    if (!filter) return pipes
    return pipes.filter((p) => p.name.toLowerCase().includes(filter.toLowerCase()))
  }, [ctx, filter])

  const filteredNodes = useMemo(() => {
    if (!ctx?.nodes) return []
    if (!filter) return ctx.nodes
    return ctx.nodes.filter(
      (n) =>
        (n.name || n.id).toLowerCase().includes(filter.toLowerCase()) ||
        (n.type || '').toLowerCase().includes(filter.toLowerCase())
    )
  }, [ctx, filter])

  const filteredEnvs = useMemo(() => {
    if (!ctx?.env_keys) return []
    if (!filter) return ctx.env_keys
    return ctx.env_keys.filter((k) => k.toLowerCase().includes(filter.toLowerCase()))
  }, [ctx, filter])

  const filteredBaseVars = useMemo(() => {
    if (!filter) return BASE_VARS
    const query = filter.toLowerCase()
    return BASE_VARS.filter(
      (v) => v.name.toLowerCase().includes(query) || v.hint.toLowerCase().includes(query)
    )
  }, [filter])

  const hasSearchResults =
    filteredBaseVars.length > 0 ||
    filteredNodes.length > 0 ||
    filteredEnvs.length > 0 ||
    filteredPipes.length > 0

  const hasPreviewValue = Boolean(
    previewResult && (previewResult.resolved !== undefined || previewResult.value !== undefined)
  )
  const previewValue = previewResult?.resolved !== undefined
    ? previewResult.resolved
    : previewResult?.value

  return (
    <div className="expr-helper-container">
      <button
        type="button"
        className="expr-trigger-btn"
        onClick={() => setIsOpen(true)}
        title="Open Expression Builder & Live Preview"
      >
        <span className="expr-fx-icon">fx</span>
        <span>Expression Builder</span>
      </button>

      {isOpen &&
        createPortal(
          <div className="expr-modal-overlay" onClick={() => setIsOpen(false)}>
            <div
              className="expr-modal-window"
              onClick={(e) => e.stopPropagation()}
              role="dialog"
              aria-modal="true"
              aria-label="Expression Builder"
            >
            {/* Header */}
            <div className="expr-modal-header">
              <div className="expr-header-title">
                <span className="expr-fx-badge">fx</span>
                <div>
                  <h3>Expression Builder</h3>
                  <span className="expr-sub-hint">
                    Build and preview expressions against real upstream data
                  </span>
                </div>
              </div>
              <button
                type="button"
                className="expr-close-btn"
                onClick={() => setIsOpen(false)}
                title="Close (Esc)"
                aria-label="Close expression builder"
                style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>

            {/* Modal Body */}
            <div className="expr-modal-body">
              {/* Left Column: Variables & Pipes Tree */}
              <div className="expr-sidebar">
                <div className="expr-search-box">
                  <svg className="expr-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="11" cy="11" r="8" />
                    <line x1="21" y1="21" x2="16.65" y2="16.65" />
                  </svg>
                  <input
                    type="text"
                    className="expr-search-input"
                    placeholder="Search variables or pipes…"
                    aria-label="Search variables and pipes"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  />
                  {filter && (
                    <button
                      type="button"
                      className="expr-search-clear"
                      onClick={() => setFilter("")}
                      aria-label="Clear search"
                      style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                  )}
                </div>

                <div className="expr-tree-scroll">
                  {/* Base Variables */}
                  {filteredBaseVars.length > 0 && (
                    <div className="expr-group">
                      <div className="expr-group-title">Variables</div>
                      {filteredBaseVars.map((v) => (
                        <button
                          type="button"
                          key={v.name}
                          className="expr-tree-item"
                          onClick={() => insertSnippet(v.snippet)}
                          title={`Click to insert: ${v.snippet}`}
                        >
                          <span className="expr-item-code">{v.name}</span>
                          <span className="expr-item-desc">{v.hint}</span>
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Nodes in Workflow */}
                  {filteredNodes.length > 0 && (
                    <div className="expr-group">
                      <div className="expr-group-title">Workflow Nodes</div>
                      {filteredNodes.map((n) => {
                        const snippet = `{{ $node["${n.id}"].json }}`
                        return (
                          <button
                            type="button"
                            key={n.id}
                            className="expr-tree-item"
                            onClick={() => insertSnippet(snippet)}
                            title={`Click to insert: ${snippet}`}
                          >
                            <span className="expr-item-code">{n.name || n.id}</span>
                            <span className="expr-item-badge">{n.type}</span>
                          </button>
                        )
                      })}
                    </div>
                  )}

                  {/* Workspace Environment Variables */}
                  {filteredEnvs.length > 0 && (
                    <div className="expr-group">
                      <div className="expr-group-title">Environment Variables</div>
                      {filteredEnvs.map((k) => {
                        const snippet = `{{ $env.${k} }}`
                        return (
                          <button
                            type="button"
                            key={k}
                            className="expr-tree-item"
                            onClick={() => insertSnippet(snippet)}
                            title={`Click to insert: ${snippet}`}
                          >
                            <span className="expr-item-code">$env.{k}</span>
                          </button>
                        )
                      })}
                    </div>
                  )}

                  {/* Transformation Pipes */}
                  {filteredPipes.length > 0 && (
                    <div className="expr-group">
                      <div className="expr-group-title">Pipes & Transforms</div>
                      {filteredPipes.map((p) => (
                        <button
                          type="button"
                          key={p.name}
                          className="expr-tree-item pipe-item"
                          onClick={() => insertSnippet(p.snippet)}
                          title={`Click to append pipe: ${p.snippet}`}
                        >
                          <span className="expr-item-code">{p.snippet}</span>
                          <span className="expr-item-desc">{p.hint}</span>
                        </button>
                      ))}
                    </div>
                  )}

                  {filter && !hasSearchResults && (
                    <div className="expr-empty-search">
                      No variables, nodes, or pipes match “{filter}”.
                    </div>
                  )}
                </div>
              </div>

              {/* Right Column: Expression Editor & Live Evaluator */}
              <div className="expr-main-panel">
                <div className="expr-editor-wrap">
                  <div className="expr-editor-top">
                    <label className="expr-field-label" htmlFor="expr-expression-input">Expression</label>
                    <div className="expr-quick-wrappers">
                      <button
                        type="button"
                        className="expr-mini-btn"
                        onClick={() => setExpression('{{ $json }}')}
                      >
                        Use $json
                      </button>
                      <button
                        type="button"
                        className="expr-mini-btn"
                        onClick={() => insertSnippet('{{ }}')}
                      >
                        Wrap
                      </button>
                    </div>
                  </div>

                  <textarea
                    id="expr-expression-input"
                    className="expr-textarea"
                    rows={4}
                    value={expression}
                    onChange={(e) => setExpression(e.target.value)}
                    placeholder="e.g. {{ $json.user.email | upper }} or Hello {{ $json.name }}!"
                    spellCheck={false}
                  />
                </div>

                {/* Live Preview Section */}
                <div className="expr-preview-wrap">
                  <div className="expr-preview-header">
                    <span className="expr-preview-label">Live preview</span>
                    {previewLoading ? (
                      <span className="expr-loading-chip">Evaluating…</span>
                    ) : previewResult?.type ? (
                      <span className="expr-type-chip">{previewResult.type}</span>
                    ) : null}
                  </div>

                  <div className="expr-preview-box" aria-live="polite">
                    {previewError ? (
                      <div className="expr-preview-err">
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>{previewError}</span>
                      </div>
                    ) : previewResult?.error ? (
                      <div className="expr-preview-err">
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>{previewResult.error}</span>
                      </div>
                    ) : previewLoading && !hasPreviewValue ? (
                      <div className="expr-preview-loading">Resolving against upstream data…</div>
                    ) : hasPreviewValue ? (
                      <pre className="expr-preview-val">
                        {typeof previewValue === 'object'
                          ? JSON.stringify(previewValue, null, 2)
                          : String(previewValue)}
                      </pre>
                    ) : (
                      <div className="expr-preview-empty">
                        <span>Start with <code>&#123;&#123; $json &#125;&#125;</code> or choose a variable to preview its resolved value.</span>
                      </div>
                    )}
                  </div>

                  {previewResult?.missing && (
                    <div className="expr-missing-warning">
                      Contains unresolved placeholders (some fields were not found upstream).
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="expr-modal-footer">
              <div className="expr-footer-left">
                {copied && <span className="expr-copied-notice">Copied to clipboard!</span>}
              </div>
              <div className="expr-footer-right">
                <button
                  type="button"
                  className="expr-btn ghost"
                  onClick={() => copy(expression)}
                  title="Copy expression text"
                >
                  Copy Expression
                </button>
                {onApply && (
                  <button
                    type="button"
                    className="expr-btn primary"
                    onClick={() => {
                      onApply(expression)
                      setIsOpen(false)
                    }}
                  >
                    Apply to Field
                  </button>
                )}
                <button
                  type="button"
                  className={`expr-btn ${onApply ? 'secondary' : 'primary'}`}
                  onClick={() => setIsOpen(false)}
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}
