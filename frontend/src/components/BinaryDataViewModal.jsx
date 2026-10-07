import React, { useEffect, useState } from 'react'
import { fetchFileObjectUrl, downloadStoredFile } from '../api'
import './BinaryDataViewModal.css'

export default function BinaryDataViewModal({ binaryEntry, onClose }) {
  const [activeTab, setActiveTab] = useState('preview')
  const [serverUrl, setServerUrl] = useState(null)
  const [serverText, setServerText] = useState(null)
  const [previewError, setPreviewError] = useState(null)

  const id = binaryEntry?.id || null
  const data = binaryEntry?.data || null
  const mimeType = binaryEntry?.mimeType || ''
  const fileExtension = binaryEntry?.fileExtension || ''
  const isImage = mimeType.startsWith('image/') || ['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(fileExtension.toLowerCase())
  const isPdf = mimeType === 'application/pdf' || fileExtension.toLowerCase() === 'pdf'
  const isText = mimeType.startsWith('text/') || ['txt', 'csv', 'json', 'log', 'xml', 'md'].includes(fileExtension.toLowerCase())
  const needsServerPreview = !!id && (isImage || isPdf || (isText && !data))

  useEffect(() => {
    if (!needsServerPreview) return undefined
    let objectUrl = null
    let cancelled = false
    setServerUrl(null)
    setServerText(null)
    setPreviewError(null)
    fetchFileObjectUrl(id, 'view')
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        objectUrl = url
        if (isText && !data) {
          // Text previews are fetched and rendered as escaped text — never as
          // a document — so stored HTML can never execute under our origin.
          return fetch(url)
            .then((r) => r.text())
            .then((t) => {
              if (!cancelled) setServerText(t)
            })
        }
        setServerUrl(url)
      })
      .catch((err) => {
        if (!cancelled) setPreviewError(err?.message || 'Preview failed')
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [id, needsServerPreview, isText, data])

  if (!binaryEntry) return null
  const { fileName, fileSize, bytes } = binaryEntry

  const dataUrl = data ? `data:${mimeType || 'application/octet-stream'};base64,${data}` : null

  const handleDownload = () => {
    if (id) {
      downloadStoredFile(id, fileName || 'download.bin').catch(() => {})
    } else if (data) {
      const a = document.createElement('a')
      a.href = dataUrl
      a.download = fileName || 'download.bin'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    }
  }

  const previewSrc = serverUrl || dataUrl

  const previewBody = () => {
    if (isImage || isPdf) {
      if (previewSrc) {
        return isImage ? (
          <img src={previewSrc} alt={fileName} className="bdv-image-preview" />
        ) : (
          // Opaque origin (no allow-same-origin): the document can never
          // touch app storage/cookies even if the PDF/HTML is hostile.
          <iframe
            src={previewSrc}
            title={fileName}
            className="bdv-iframe-preview"
            sandbox="allow-scripts allow-popups"
          />
        )
      }
      if (previewError) {
        return <div className="bdv-no-preview"><h4>Preview failed</h4><p>{previewError}</p></div>
      }
      return <div className="bdv-no-preview"><p>Loading preview…</p></div>
    }
    if (isText) {
      if (data) {
        return (
          <div className="bdv-text-wrapper">
            <pre className="bdv-text-content">
              {atob(data)}
            </pre>
          </div>
        )
      }
      if (serverText !== null) {
        return (
          <div className="bdv-text-wrapper">
            <pre className="bdv-text-content">
              {serverText}
            </pre>
          </div>
        )
      }
      if (previewError) {
        return <div className="bdv-no-preview"><h4>Preview failed</h4><p>{previewError}</p></div>
      }
      return <div className="bdv-no-preview"><p>Loading preview…</p></div>
    }
    return (
      <div className="bdv-no-preview">
        <span className="bdv-no-preview-icon" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>
        </span>
        <h4>No inline preview available</h4>
        <p>This file type cannot be previewed directly in the browser.</p>
        <button type="button" className="bdv-btn-download-center" onClick={handleDownload}>
          Download {fileName} ({fileSize})
        </button>
      </div>
    )
  }

  return (
    <div className="bdv-backdrop" onClick={onClose}>
      <div className="bdv-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="bdv-header">
          <div className="bdv-title-group">
            <span className="bdv-icon" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              {isImage ? (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>
              ) : isPdf ? (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg>
              ) : isText ? (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="17" x2="3" y1="6" y2="6"/><line x1="21" x2="3" y1="12" y2="12"/><line x1="15" x2="3" y1="18" y2="18"/></svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>
              )}
            </span>
            <div className="bdv-meta">
              <span className="bdv-filename" title={fileName}>{fileName || 'Unnamed File'}</span>
              <span className="bdv-badge">{fileSize || (bytes ? `${bytes} B` : '0 B')}</span>
              <span className="bdv-badge bdv-badge-subtle">{mimeType || 'application/octet-stream'}</span>
            </div>
          </div>

          <div className="bdv-actions">
            <div className="bdv-tabs">
              <button
                type="button"
                className={`bdv-tab ${activeTab === 'preview' ? 'active' : ''}`}
                onClick={() => setActiveTab('preview')}
              >
                Preview
              </button>
              <button
                type="button"
                className={`bdv-tab ${activeTab === 'info' ? 'active' : ''}`}
                onClick={() => setActiveTab('info')}
              >
                Metadata
              </button>
            </div>

            <button type="button" className="bdv-btn-download" onClick={handleDownload} title="Download file">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Download
            </button>

            <button type="button" className="bdv-btn-close" onClick={onClose} title="Close" aria-label="Close" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="bdv-body">
          {activeTab === 'preview' ? (
            <div className="bdv-preview-container">
              {previewBody()}
            </div>
          ) : (
            <div className="bdv-info-container">
              <table className="bdv-info-table">
                <tbody>
                  <tr>
                    <th>File Name</th>
                    <td>{fileName || '—'}</td>
                  </tr>
                  <tr>
                    <th>Extension</th>
                    <td>{binaryEntry.fileExtension || '—'}</td>
                  </tr>
                  <tr>
                    <th>MIME Type</th>
                    <td>{mimeType || '—'}</td>
                  </tr>
                  <tr>
                    <th>File Size</th>
                    <td>{fileSize} ({bytes?.toLocaleString() || 0} bytes)</td>
                  </tr>
                  {id && (
                    <tr>
                      <th>Storage ID</th>
                      <td><code>{id}</code></td>
                    </tr>
                  )}
                  {binaryEntry.objectKey && (
                    <tr>
                      <th>Storage Key</th>
                      <td><code>{binaryEntry.objectKey}</code></td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
