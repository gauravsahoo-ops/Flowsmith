import React, { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import { useWorkflowStore } from '../stores/workflowStore'
import './OpenApiImportModal.css'

export default function OpenApiImportModal({ isOpen = true, onClose, onImportSuccess }) {
  const [tab, setTab] = useState('url') // 'url' | 'raw'
  const [specUrl, setSpecUrl] = useState('')
  const [specRaw, setSpecRaw] = useState('')
  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('api')
  const [baseUrl, setBaseUrl] = useState('')

  const [previewing, setPreviewing] = useState(false)
  const [previewData, setPreviewData] = useState(null)
  const [previewError, setPreviewError] = useState(null)

  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState(null)
  const [importSuccess, setImportSuccess] = useState(null)

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const currentSpec = tab === 'url' ? specUrl.trim() : specRaw.trim()

  const handlePreview = async () => {
    if (!currentSpec) {
      setPreviewError('Please provide an OpenAPI URL or paste raw JSON/YAML content.')
      return
    }
    setPreviewing(true)
    setPreviewError(null)
    setPreviewData(null)
    try {
      const res = await api.previewOpenApi({ spec: currentSpec })
      const data = res.data || res
      setPreviewData(data)
      if (data.title && !title) setTitle(data.title)
      if (data.title && !name) {
        setName(data.title.toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 32))
      }
      if (data.base_url && !baseUrl) setBaseUrl(data.base_url)
    } catch (err) {
      setPreviewError(err.message || 'Failed to preview OpenAPI specification.')
    } finally {
      setPreviewing(false)
    }
  }

  const handleImport = async () => {
    if (!currentSpec) {
      setImportError('Please provide an OpenAPI spec.')
      return
    }
    if (!name.trim()) {
      setImportError('Please specify a connector identifier (slug).')
      return
    }
    setImporting(true)
    setImportError(null)
    setImportSuccess(null)
    try {
      const res = await api.importOpenApi({
        spec: currentSpec,
        name: name.trim(),
        title: title.trim() || undefined,
        category: category || 'api',
        base_url: baseUrl.trim() || undefined,
      })
      const data = res.data || res
      setImportSuccess(
        `Successfully imported "${data.display_name}" with ${data.operations_count} operations!`
      )
      // Refresh the workflow node catalog so the new connector shows up immediately
      try {
        const nodes = await api.listNodes()
        if (Array.isArray(nodes)) {
          useWorkflowStore.setState({ catalog: nodes })
        }
      } catch {}
      if (typeof onImportSuccess === 'function') {
        onImportSuccess(data)
      }
    } catch (err) {
      setImportError(err.message || 'Failed to import connector.')
    } finally {
      setImporting(false)
    }
  }

  return createPortal(
    <div className="oai-modal-overlay" onClick={onClose}>
      <div className="oai-modal-window" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="oai-modal-header">
          <div className="oai-header-title">
            <span className="oai-icon" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v6"/><path d="M9 2v4"/><path d="M15 2v4"/><path d="M6 8v4a6 6 0 0 0 12 0V8z"/><path d="M12 18v4"/></svg>
            </span>
            <div>
              <h3>Import OpenAPI / Swagger Connector</h3>
              <span className="oai-subtitle">
                Generate first-class, production-ready connectors from any OpenAPI 3.x or Swagger spec
              </span>
            </div>
          </div>
          <button type="button" className="oai-close-btn" onClick={onClose} aria-label="Close" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        {/* Body */}
        <div className="oai-modal-body">
          {importSuccess ? (
            <div className="oai-success-state">
              <div className="oai-success-badge" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              </div>
              <h4>Connector Generated & Registered!</h4>
              <p>{importSuccess}</p>
              <p className="oai-hint">
                The connector is now available in your Node Palette under the Connectors category and can be added to any workflow.
              </p>
              <button
                type="button"
                className="oai-btn primary"
                onClick={onClose}
                style={{ marginTop: 16 }}
              >
                Done
              </button>
            </div>
          ) : (
            <>
              {/* Tabs */}
              <div className="oai-tabs">
                <button
                  type="button"
                  className={`oai-tab ${tab === 'url' ? 'active' : ''}`}
                  onClick={() => setTab('url')}
                >
                  From URL
                </button>
                <button
                  type="button"
                  className={`oai-tab ${tab === 'raw' ? 'active' : ''}`}
                  onClick={() => setTab('raw')}
                >
                  Paste JSON / YAML
                </button>
              </div>

              {tab === 'url' ? (
                <div className="oai-form-group">
                  <label>OpenAPI / Swagger Spec URL</label>
                  <div className="oai-input-row">
                    <input
                      type="url"
                      placeholder="e.g. https://petstore.swagger.io/v2/swagger.json"
                      value={specUrl}
                      onChange={(e) => setSpecUrl(e.target.value)}
                    />
                    <button
                      type="button"
                      className="oai-btn ghost"
                      onClick={handlePreview}
                      disabled={previewing || !specUrl.trim()}
                    >
                      {previewing ? 'Inspecting…' : 'Inspect Spec'}
                    </button>
                  </div>
                  <span className="oai-hint">
                    Supports JSON and YAML specs from any public or protected endpoint.
                  </span>
                </div>
              ) : (
                <div className="oai-form-group">
                  <label>OpenAPI Spec Definition (JSON or YAML)</label>
                  <textarea
                    rows={6}
                    placeholder="Paste full OpenAPI 3.0 / 3.1 JSON or YAML document here…"
                    value={specRaw}
                    onChange={(e) => setSpecRaw(e.target.value)}
                    spellCheck={false}
                  />
                  <div style={{ marginTop: 6 }}>
                    <button
                      type="button"
                      className="oai-btn ghost"
                      onClick={handlePreview}
                      disabled={previewing || !specRaw.trim()}
                    >
                      {previewing ? 'Inspecting…' : 'Inspect Spec'}
                    </button>
                  </div>
                </div>
              )}

              {previewError && (
                <div className="oai-error-banner" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                  <span>{previewError}</span>
                </div>
              )}

              {/* Spec Details Preview */}
              {previewData && (
                <div className="oai-preview-box">
                  <div className="oai-preview-header">
                    <div>
                      <strong>{previewData.title || 'Untitled API'}</strong>
                      <span className="oai-preview-ops">
                        {previewData.operations_count} operation(s) found
                      </span>
                    </div>
                    {previewData.auth?.kind && (
                      <span className="oai-auth-badge">
                        Auth: {previewData.auth.kind.replace(/_/g, ' ').toUpperCase()}
                      </span>
                    )}
                  </div>
                  {previewData.base_url && (
                    <div className="oai-base-url">
                      Base URL: <code>{previewData.base_url}</code>
                    </div>
                  )}

                  <div className="oai-ops-list">
                    {previewData.operations?.slice(0, 8).map((op, idx) => (
                      <div key={idx} className="oai-op-row">
                        <span className={`oai-method ${op.method.toLowerCase()}`}>
                          {op.method.toUpperCase()}
                        </span>
                        <code className="oai-path">{op.path}</code>
                        <span className="oai-op-summary">{op.summary || op.operation_key}</span>
                      </div>
                    ))}
                    {previewData.operations?.length > 8 && (
                      <div className="oai-ops-more">
                        + {previewData.operations.length - 8} more operations
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Config Fields */}
              <div className="oai-grid-2">
                <div className="oai-form-group">
                  <label>Connector Identifier (Slug)</label>
                  <input
                    type="text"
                    placeholder="e.g. petstore or custom_crm"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>
                <div className="oai-form-group">
                  <label>Display Name</label>
                  <input
                    type="text"
                    placeholder="e.g. Swagger Petstore"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </div>
              </div>

              <div className="oai-grid-2">
                <div className="oai-form-group">
                  <label>Category</label>
                  <select value={category} onChange={(e) => setCategory(e.target.value)}>
                    <option value="api">API & Web Services</option>
                    <option value="communication">Communication</option>
                    <option value="database">Database</option>
                    <option value="crm">CRM & Sales</option>
                    <option value="marketing">Marketing</option>
                    <option value="analytics">Analytics</option>
                  </select>
                </div>
                <div className="oai-form-group">
                  <label>Base URL Override (Optional)</label>
                  <input
                    type="url"
                    placeholder="e.g. https://api.example.com/v1"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                  />
                </div>
              </div>

              {importError && (
                <div className="oai-error-banner" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                  <span>{importError}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {!importSuccess && (
          <div className="oai-modal-footer">
            <button type="button" className="oai-btn ghost" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="oai-btn primary"
              onClick={handleImport}
              disabled={importing || !currentSpec || !name.trim()}
            >
              {importing ? 'Generating Connector…' : 'Generate & Register Connector'}
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
