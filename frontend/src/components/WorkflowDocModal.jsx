import React, { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import './WorkflowDocModal.css'

export default function WorkflowDocModal({ isOpen, onClose, workflowId, workflowName }) {
  const [loading, setLoading] = useState(false)
  const [doc, setDoc] = useState(null)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('preview') // 'preview' | 'markdown'
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!isOpen || !workflowId) return
    setLoading(true)
    setError(null)
    api
      .documentWorkflow(workflowId)
      .then((data) => {
        setDoc(data.data || data)
      })
      .catch((err) => {
        setError(err.message || 'Failed to generate workflow architecture documentation.')
      })
      .finally(() => setLoading(false))
  }, [isOpen, workflowId])

  useEffect(() => {
    if (!isOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const handleCopy = () => {
    if (!doc?.markdown) return
    navigator.clipboard?.writeText(doc.markdown).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const handleDownload = () => {
    if (!doc?.markdown) return
    const blob = new Blob([doc.markdown], { type: 'text/markdown;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${(workflowName || 'workflow').replace(/[^a-zA-Z0-9_-]+/g, '_')}_architecture.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return createPortal(
    <div className="wdm-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="wdm-modal-window" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="wdm-modal-header">
          <div className="wdm-header-title">
            <span className="wdm-icon" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg>
            </span>
            <div>
              <h3>Workflow Architecture & Documentation</h3>
              <span className="wdm-subtitle">
                Auto-generated system blueprint, Mermaid topology, and step inventory
              </span>
            </div>
          </div>
          <button type="button" className="wdm-close-btn" onClick={onClose} aria-label="Close" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        {/* Action / Tab Bar */}
        <div className="wdm-action-bar">
          <div className="wdm-tabs">
            <button
              type="button"
              className={`wdm-tab ${tab === 'preview' ? 'active' : ''}`}
              onClick={() => setTab('preview')}
            >
              Formatted Document
            </button>
            <button
              type="button"
              className={`wdm-tab ${tab === 'markdown' ? 'active' : ''}`}
              onClick={() => setTab('markdown')}
            >
              Raw Markdown
            </button>
          </div>
          <div className="wdm-export-actions">
            <button
              type="button"
              className="wdm-btn ghost"
              onClick={handleCopy}
              disabled={!doc?.markdown}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
            >
              {copied ? (
                <>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                  <span>Copied!</span>
                </>
              ) : (
                <>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                  <span>Copy Markdown</span>
                </>
              )}
            </button>
            <button
              type="button"
              className="wdm-btn primary"
              onClick={handleDownload}
              disabled={!doc?.markdown}
            >
              Download .md
            </button>
            <button
              type="button"
              className="wdm-btn ghost"
              onClick={onClose}
              title="Close modal (Esc)"
            >
              Close
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="wdm-modal-body">
          {loading ? (
            <div className="wdm-loading">
              <div className="wdm-spinner" />
              <span>Analyzing graph topology and generating architecture document…</span>
            </div>
          ) : error ? (
            <div className="wdm-error-banner" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              <span>{error}</span>
            </div>
          ) : doc ? (
            tab === 'preview' ? (
              <div className="wdm-rendered-doc">
                {doc.overview && (
                  <div className="wdm-overview-card">
                    <h4>Executive Summary</h4>
                    <p>{doc.overview}</p>
                  </div>
                )}

                {doc.mermaid && (
                  <div className="wdm-section">
                    <h4>Mermaid Architecture Topology</h4>
                    <pre className="wdm-mermaid-box">{doc.mermaid}</pre>
                  </div>
                )}

                <div className="wdm-section">
                  <h4>Component Inventory</h4>
                  <div className="wdm-table-wrap">
                    <table className="wdm-table">
                      <thead>
                        <tr>
                          <th>Role</th>
                          <th>Node ID</th>
                          <th>Type</th>
                          <th>Operation</th>
                          <th>Downstream Targets</th>
                        </tr>
                      </thead>
                      <tbody>
                        {doc.structure?.triggers?.map((t) => (
                          <tr key={t.id} className="wdm-row-trigger">
                            <td><span className="wdm-badge trigger">Trigger</span></td>
                            <td><code>{t.id}</code></td>
                            <td>{t.type}</td>
                            <td>—</td>
                            <td>Active</td>
                          </tr>
                        ))}
                        {doc.structure?.steps?.map((s) => (
                          <tr key={s.id}>
                            <td><span className="wdm-badge step">Step</span></td>
                            <td><code>{s.id}</code></td>
                            <td>{s.type}</td>
                            <td>{s.operation || 'default'}</td>
                            <td>
                              {s.feeds?.length
                                ? s.feeds.map((f) => <code key={f} style={{ marginRight: 4 }}>{f}</code>)
                                : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : (
              <textarea
                className="wdm-raw-textarea"
                value={doc.markdown || ''}
                readOnly
                spellCheck={false}
              />
            )
          ) : null}
        </div>
      </div>
    </div>,
    document.body
  )
}
