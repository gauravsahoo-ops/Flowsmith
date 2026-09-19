import React, { useState, useEffect } from 'react'
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

  return (
    <div className="wdm-modal-overlay" onClick={onClose}>
      <div className="wdm-modal-window" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="wdm-modal-header">
          <div className="wdm-header-title">
            <span className="wdm-icon">📄</span>
            <div>
              <h3>Workflow Architecture & Documentation</h3>
              <span className="wdm-subtitle">
                Auto-generated system blueprint, Mermaid topology, and step inventory
              </span>
            </div>
          </div>
          <button type="button" className="wdm-close-btn" onClick={onClose}>
            ✕
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
            >
              {copied ? '✓ Copied!' : 'Copy Markdown'}
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
            <div className="wdm-error-banner">⚠️ {error}</div>
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
    </div>
  )
}
