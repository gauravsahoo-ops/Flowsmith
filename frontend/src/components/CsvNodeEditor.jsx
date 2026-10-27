import React, { useState } from 'react'
import { getToken } from '../api'

export default function CsvNodeEditor({ node, onParamsChange }) {
  const params = node.parameters || {}

  // Determine initial source mode
  const getInitialSourceMode = () => {
    if (params.download_url && params.download_url.trim()) return 'url'
    if (params.file_path && params.file_path.trim()) return 'file_path'
    if (params.source_mode) return params.source_mode
    if (params.csv_content && !params.file_name && !params.file_id) return 'inline'
    return 'upload'
  }

  const [sourceMode, setSourceMode] = useState(getInitialSourceMode())
  const [downloadUrl, setDownloadUrl] = useState(params.download_url || '')
  const [authType, setAuthType] = useState(params.auth_type || 'none')
  const [authToken, setAuthToken] = useState(params.auth_token || '')
  const [timeoutSeconds, setTimeoutSeconds] = useState(params.timeout_seconds || 30)
  const [maxDownloadBytes, setMaxDownloadBytes] = useState(params.max_download_bytes || 52428800)

  const [fileId, setFileId] = useState(params.file_id || '')
  const [filePath, setFilePath] = useState(params.file_path || '')
  const [csvContent, setCsvContent] = useState(params.csv_content || '')
  const [archiveInnerFile, setArchiveInnerFile] = useState(params.archive_inner_file || '')
  const [archivePattern, setArchivePattern] = useState(params.archive_pattern || '*')
  const [archiveProcessMode, setArchiveProcessMode] = useState(params.archive_process_mode || 'single')
  const [archiveHeaderMode, setArchiveHeaderMode] = useState(params.archive_header_mode || 'union')

  const [delimiter, setDelimiter] = useState(params.delimiter || '')
  const [hasHeader, setHasHeader] = useState(params.has_header !== false)
  const [batchSize, setBatchSize] = useState(params.batch_size !== undefined && params.batch_size !== null ? params.batch_size : 1000)
  const [rowLimit, setRowLimit] = useState(params.row_limit || 0)

  const [fileName, setFileName] = useState(params.file_name || '')
  const [fileSize, setFileSize] = useState(params.file_size || '')
  const [uploadError, setUploadError] = useState(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isUploading, setIsUploading] = useState(false)
  const [previewRows, setPreviewRows] = useState([])
  const [previewColumns, setPreviewColumns] = useState([])

  const updateParam = (key, value) => {
    onParamsChange({
      ...params,
      [key]: value,
    })
  }

  const updateMultipleParams = (updates) => {
    onParamsChange({
      ...params,
      ...updates,
    })
  }

  const handleSourceModeChange = (mode) => {
    setSourceMode(mode)
    updateParam('source_mode', mode)
  }

  const formatBytes = (bytes) => {
    if (!bytes || bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  // Quick client-side preview extractor for text tabular files
  const extractPreviewFromText = (rawText, delimHint = ',') => {
    if (!rawText) return
    const sampleText = rawText.length > 8192 ? rawText.slice(0, 8192) : rawText
    const lines = sampleText.split(/\r?\n/).map(l => l.trim()).filter(Boolean).slice(0, 6)
    if (!lines.length) return
    const effectiveDelim = delimHint || (lines[0].includes('\t') ? '\t' : ',')
    const headers = lines[0].split(effectiveDelim).map(h => h.replace(/^["']|["']$/g, '').trim())
    setPreviewColumns(headers)
    const samples = lines.slice(1).map((line, rIdx) => {
      const parts = line.split(effectiveDelim).map(p => p.replace(/^["']|["']$/g, '').trim())
      const obj = { _id: rIdx }
      headers.forEach((h, cIdx) => {
        obj[h] = parts[cIdx] || ''
      })
      return obj
    })
    setPreviewRows(samples)
  }

  const processUploadedFile = async (file) => {
    if (!file) return
    const name = file.name
    const sizeStr = formatBytes(file.size)
    setFileName(name)
    setFileSize(sizeStr)

    const lowerName = name.toLowerCase()
    const isArchive = lowerName.endsWith('.zip') || lowerName.endsWith('.gz') || lowerName.endsWith('.tgz') || lowerName.endsWith('.tar')
    const isTsv = lowerName.endsWith('.tsv') || lowerName.endsWith('.tab')

    if (isTsv && !delimiter) {
      setDelimiter('\t')
      updateParam('delimiter', '\t')
    }

    setIsUploading(true)
    setUploadProgress(20)
    setUploadError(null)

    // Attempt uploading to Flowsmith files API to persist a secure file_id reference
    let uploadSuccess = false
    try {
      setIsUploading(true)
      setUploadProgress(10)
      const formData = new FormData()
      formData.append('file', file)
      setUploadProgress(40)

      const headers = {}
      const token = getToken()
      if (token) headers.Authorization = `Bearer ${token}`

      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 60000)

      const res = await fetch('/api/files', {
        method: 'POST',
        headers,
        body: formData,
        signal: controller.signal,
      })
      clearTimeout(timeoutId)

      if (res.ok) {
        const json = await res.json()
        const createdFileId = json.data?.id || json.file_id || json.id || json.key
        if (createdFileId) {
          uploadSuccess = true
          setFileId(createdFileId)
          setUploadError(null)
          setUploadProgress(100)
          setIsUploading(false)
          updateMultipleParams({
            file_id: createdFileId,
            file_name: name,
            file_size: sizeStr,
            source_type: 'upload',
            source_mode: 'upload',
            file_format: isArchive ? 'zip' : (isTsv ? 'tsv' : 'csv'),
            csv_content: '',
          })

          if (!isArchive) {
            const reader = new FileReader()
            reader.onload = (e) => {
              const text = e.target?.result
              if (typeof text === 'string') {
                extractPreviewFromText(text, isTsv ? '\t' : (delimiter || ','))
              }
            }
            reader.readAsText(file.slice(0, 32768))
          }
          return
        }
      } else {
        let errDetail = `Upload failed (HTTP ${res.status})`
        if (res.status === 413) {
          errDetail = `File exceeds server upload limit (HTTP 413 Request Entity Too Large). The file (${sizeStr}) is larger than the server proxy limit (default 1 MB). Please configure 'client_max_body_size 50M;' in your server Nginx configuration.`
        } else if (res.status === 401) {
          errDetail = 'Authentication required. Please log in again.'
        } else {
          try {
            const j = await res.json()
            errDetail = j.detail || j.message || errDetail
          } catch {}
        }
        setUploadError(errDetail)
        setIsUploading(false)
        setUploadProgress(0)
      }
    } catch (err) {
      const isAbort = err?.name === 'AbortError'
      setUploadError(isAbort ? 'Upload timed out after 60s. Please check network speed or file size.' : `Upload failed: ${err.message || 'Network error'}`)
      setIsUploading(false)
      setUploadProgress(0)
    }

    if (uploadSuccess) return

    // Never embed files larger than 64 KB into workflow JSON
    if (file.size > 65536) {
      setIsUploading(false)
      setUploadProgress(0)
      return
    }

    // Small file (< 64 KB) fallback for local offline testing
    const reader = new FileReader()
    reader.onerror = () => {
      setIsUploading(false)
      setUploadProgress(0)
    }
    if (isArchive) {
      reader.onload = (event) => {
        const content = event.target?.result
        if (typeof content === 'string') {
          setCsvContent(content)
          setUploadProgress(100)
          setIsUploading(false)
          updateMultipleParams({
            csv_content: content,
            file_name: name,
            file_size: sizeStr,
            source_type: 'upload',
            source_mode: 'upload',
            file_format: 'zip',
          })
        } else {
          setIsUploading(false)
        }
      }
      reader.readAsDataURL(file)
    } else {
      reader.onload = (event) => {
        const content = event.target?.result
        if (typeof content === 'string') {
          setCsvContent(content)
          setUploadProgress(100)
          setIsUploading(false)
          extractPreviewFromText(content, isTsv ? '\t' : (delimiter || ','))
          updateMultipleParams({
            csv_content: content,
            file_name: name,
            file_size: sizeStr,
            source_type: 'upload',
            source_mode: 'upload',
            file_format: isTsv ? 'tsv' : 'csv',
          })
        } else {
          setIsUploading(false)
        }
      }
      reader.readAsText(file)
    }
  }

  const handleFileInputChange = (e) => {
    const file = e.target.files?.[0]
    processUploadedFile(file)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files?.[0]
    processUploadedFile(file)
  }

  const handleClearUploadedFile = () => {
    setFileName('')
    setFileSize('')
    setFileId('')
    setCsvContent('')
    setUploadError(null)
    setPreviewRows([])
    setPreviewColumns([])
    updateMultipleParams({
      file_id: '',
      file_name: '',
      file_size: '',
      csv_content: '',
      source_type: '',
      source_mode: 'upload',
    })
  }

  // Common input style using Flowsmith tokens
  const inputStyle = {
    width: '100%',
    height: '36px',
    borderRadius: '7px',
    fontSize: '11.5px',
    fontFamily: 'inherit',
  }

  const labelStyle = {
    display: 'block',
    fontSize: '9.5px',
    fontWeight: 600,
    color: 'var(--text-dim)',
    marginBottom: '6px',
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
  }

  const cardStyle = {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  }

  return (
    <div className="flowsmith-dataload-editor" style={{ display: 'flex', flexDirection: 'column', gap: '0', padding: '0' }}>
      <div className="dl-intro">
        <div className="dl-intro-row">
          <span className="dl-intro-title">CSV Parser</span>
          <span className="dl-intro-code">csv_parser</span>
          <span className="dl-intro-formats">CSV · TSV · ZIP · TAR · GZIP</span>
        </div>
        <p className="dl-intro-copy">
          Download, import, and parse delimited files into clean records.
        </p>
      </div>

      {/* Source selection */}
      <div className="form-section dl-section" style={cardStyle}>
        <div className="dl-section-head">
          <h4 className="dl-section-title">Source</h4>
          <span className="dl-section-hint">Select ingestion mechanism</span>
        </div>

        <div className="dl-source-options" role="group" aria-label="Source mode">
          {[
            { id: 'upload', label: 'Upload file', desc: 'Object storage' },
            { id: 'url', label: 'Download URL', desc: 'HTTP / HTTPS' },
            { id: 'file_path', label: 'Local path', desc: 'Container disk' },
            { id: 'inline', label: 'Inline text', desc: 'Raw / expression' },
          ].map((mode) => {
            const isActive = sourceMode === mode.id
            return (
              <button
                key={mode.id}
                type="button"
                aria-pressed={isActive}
                onClick={() => handleSourceModeChange(mode.id)}
                className={`dl-source-option${isActive ? ' is-active' : ''}`}
              >
                <span className="dl-source-label">{mode.label}</span>
                <span className="dl-source-desc">{mode.desc}</span>
              </button>
            )
          })}
        </div>

        {/* Option A: Upload File */}
        {sourceMode === 'upload' && (
          <div className="dl-stack">
            <div
              className={`dl-dropzone${isDragOver ? ' is-dragover' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={handleDrop}
              onClick={() => document.getElementById('dataload-file-picker')?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  document.getElementById('dataload-file-picker')?.click()
                }
              }}
              role="button"
              tabIndex={0}
              aria-label="Choose or drop a CSV file"
            >
              <input
                id="dataload-file-picker"
                type="file"
                accept=".csv,.tsv,.tab,.txt,.zip,.gz,.tgz,.tar"
                onChange={handleFileInputChange}
                style={{ display: 'none' }}
              />
              <div className="dl-drop-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
              </div>
              <div className="dl-drop-title">Drop a file here or browse</div>
              <div className="dl-drop-copy">
                CSV, TSV, or ZIP archives. Files are stored securely in Flowsmith ObjectStore.
              </div>
            </div>

            {isUploading && (
              <div style={{ background: 'var(--panel-2)', padding: '0.65rem 0.85rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--accent)', marginBottom: '0.35rem', fontWeight: 600 }}>
                  <span>Uploading to ObjectStore...</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div style={{ background: 'var(--panel-3)', height: '4px', borderRadius: '2px', overflow: 'hidden' }}>
                  <div style={{ width: `${uploadProgress}%`, height: '100%', background: 'var(--gradient-brand)', transition: 'width 0.2s' }} />
                </div>
              </div>
            )}

            {uploadError && (
              <div style={{
                background: 'rgba(225, 29, 72, 0.1)',
                border: '1px solid rgba(225, 29, 72, 0.3)',
                borderRadius: 'var(--radius-sm)',
                padding: '0.75rem 0.9rem',
                color: 'var(--text)',
                fontSize: '0.78rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.25rem',
              }}>
                <span style={{ fontWeight: 600, color: 'var(--red)' }}>⚠ File Upload Error</span>
                <span style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>{uploadError}</span>
              </div>
            )}

            {(fileName || fileId) && (
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '0.75rem 0.95rem',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--panel-2)',
                border: '1px solid var(--border-strong)',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <div style={{
                    width: 32,
                    height: 32,
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(5, 150, 105, 0.15)',
                    color: 'var(--green)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.84rem', fontWeight: 600, color: 'var(--text)', display: 'block' }}>
                      {fileName || 'Loaded File'}
                    </span>
                    <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '0.15rem' }}>
                      {fileSize && <span>Size: {fileSize}</span>}
                      {fileId && <span>Ref ID: <code style={{ fontSize: '0.7rem' }}>{fileId.slice(0, 12)}...</code></span>}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleClearUploadedFile}
                  style={{
                    padding: '0.35rem 0.75rem',
                    background: 'rgba(225, 29, 72, 0.12)',
                    color: 'var(--red)',
                    border: '1px solid rgba(225, 29, 72, 0.25)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.35rem',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                  Clear File
                </button>
              </div>
            )}
          </div>
        )}

        {/* Option B: Download from URL */}
        {sourceMode === 'url' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', marginTop: '0.25rem' }}>
            <div>
              <label style={labelStyle} htmlFor="dataload-download-url">
                Download URL
              </label>
              <input
                id="dataload-download-url"
                type="text"
                className="dl-input dl-input-mono"
                value={downloadUrl}
                placeholder="https://example.com/data/contacts.csv or {{ $json.export_url }}"
                onChange={(e) => {
                  setDownloadUrl(e.target.value)
                  updateParam('download_url', e.target.value)
                }}
                style={inputStyle}
              />
              <span className="dl-field-hint">Supports literal URLs and <code>{'{{ expressions }}'}</code>.</span>
            </div>

            {/* SSRF & Security Guard Indicator */}
            <div className="dl-callout dl-callout-safe">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <span><strong>SSRF Guard Active:</strong> Rejects loopback, private networks (RFC 1918), and cloud metadata destinations. Validates DNS and redirects.</span>
            </div>

            <div className="dl-grid dl-grid-2">
              <div>
                <label style={labelStyle}>
                  Authentication Type
                </label>
                <select
                  value={authType}
                  onChange={(e) => {
                    setAuthType(e.target.value)
                    updateParam('auth_type', e.target.value)
                  }}
                  style={inputStyle}
                >
                  <option value="none">None (Public Download)</option>
                  <option value="bearer">Bearer Token</option>
                  <option value="basic">Basic Auth (user:pass)</option>
                </select>
              </div>

              <div>
                <label style={labelStyle}>
                  Auth Token / Secret
                </label>
                <input
                  type="password"
                  value={authToken}
                  placeholder={authType === 'basic' ? 'username:password' : 'Bearer token or expression'}
                  onChange={(e) => {
                    setAuthToken(e.target.value)
                    updateParam('auth_token', e.target.value)
                  }}
                  disabled={authType === 'none'}
                  style={{
                    ...inputStyle,
                    opacity: authType === 'none' ? 0.6 : 1,
                  }}
                />
              </div>
            </div>

            <div className="dl-grid dl-grid-2">
              <div>
                <label style={labelStyle}>
                  Timeout (Seconds)
                </label>
                <input
                  type="number"
                  min="1"
                  max="300"
                  value={timeoutSeconds}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value) || 30.0
                    setTimeoutSeconds(val)
                    updateParam('timeout_seconds', val)
                  }}
                  style={inputStyle}
                />
              </div>

              <div>
                <label style={labelStyle}>
                  Max Download Size (MB)
                </label>
                <input
                  type="number"
                  min="1"
                  max="200"
                  value={Math.round(maxDownloadBytes / (1024 * 1024))}
                  onChange={(e) => {
                    const mb = parseInt(e.target.value, 10) || 50
                    const bytes = mb * 1024 * 1024
                    setMaxDownloadBytes(bytes)
                    updateParam('max_download_bytes', bytes)
                  }}
                  style={inputStyle}
                />
              </div>
            </div>
          </div>
        )}

        {/* Local File Path */}
        {sourceMode === 'file_path' && (
          <div style={{ marginTop: '0.25rem' }}>
            <label style={labelStyle}>
              Filesystem or Container File Path
            </label>
            <input
              type="text"
              value={filePath}
              placeholder="e.g. /data/contacts.tsv or contacts.zip"
              onChange={(e) => {
                setFilePath(e.target.value)
                updateParam('file_path', e.target.value)
              }}
              style={inputStyle}
            />
          </div>
        )}

        {/* Inline Content */}
        {sourceMode === 'inline' && (
          <div style={{ marginTop: '0.25rem' }}>
            <label style={labelStyle}>
              Raw Text or Expression
            </label>
            <textarea
              rows={5}
              value={csvContent.startsWith('data:') ? '/* Binary DataURL loaded */' : csvContent}
              placeholder="FirstName,LastName,Email\nAda,Lovelace,ada@example.com"
              onChange={(e) => {
                setCsvContent(e.target.value)
                updateParam('csv_content', e.target.value)
                extractPreviewFromText(e.target.value, delimiter || ',')
              }}
              style={{
                ...inputStyle,
                height: 'auto',
                minHeight: 96,
                padding: '8px 10px',
                fontFamily: 'var(--font-mono)',
                fontSize: '10.5px',
                lineHeight: 1.55,
                resize: 'vertical',
              }}
            />
          </div>
        )}
      </div>

      {/* Structure Preview Panel (when preview data is present) */}
      {previewColumns.length > 0 && (
        <div className="form-section" style={cardStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h4 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: 'var(--text)' }}>
              Detected Structure Preview ({previewColumns.length} columns)
            </h4>
            <span style={{ fontSize: '0.72rem', color: 'var(--green)', fontWeight: 500 }}>
              Showing first {previewRows.length} rows
            </span>
          </div>
          <div style={{ overflowX: 'auto', maxHeight: '180px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.76rem', textAlign: 'left' }}>
              <thead>
                <tr style={{ background: 'var(--panel-3)', color: 'var(--text-secondary)' }}>
                  {previewColumns.map((col) => (
                    <th key={col} style={{ padding: '0.45rem 0.65rem', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? 'var(--panel)' : 'var(--panel-2)' }}>
                    {previewColumns.map((col) => (
                      <td key={col} style={{ padding: '0.45rem 0.65rem', color: 'var(--text)', borderBottom: '1px solid var(--border-subtle)' }}>{row[col]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Archive Configuration (Shown for ZIP / TAR) */}
      <div className="form-section dl-section" style={cardStyle}>
        <div className="dl-section-head">
          <h4 className="dl-section-title">Archive extraction</h4>
          <span className="dl-section-hint">ZIP, TAR, and GZIP only</span>
        </div>
        <div className="dl-grid dl-grid-2">
          <div>
            <label style={labelStyle}>
              Process Mode
            </label>
            <select
              value={archiveProcessMode}
              onChange={(e) => {
                setArchiveProcessMode(e.target.value)
                updateParam('archive_process_mode', e.target.value)
              }}
              style={inputStyle}
            >
              <option value="single">Process Single File (Default)</option>
              <option value="combine">Combine All Matching Files</option>
            </select>
          </div>

          <div>
            <label style={labelStyle}>
              Header Match Policy (Combine Mode)
            </label>
            <select
              value={archiveHeaderMode}
              onChange={(e) => {
                setArchiveHeaderMode(e.target.value)
                updateParam('archive_header_mode', e.target.value)
              }}
              style={inputStyle}
            >
              <option value="union">Union (Merge All Columns)</option>
              <option value="strict">Strict (Fail on Mismatch)</option>
              <option value="first">First File Headers Only</option>
            </select>
          </div>
        </div>

        <div className="dl-grid dl-grid-2">
          <div>
            <label style={labelStyle}>
              Target Entry Filename (Optional)
            </label>
            <input
              type="text"
              value={archiveInnerFile}
              placeholder="e.g. data/contacts.csv"
              onChange={(e) => {
                setArchiveInnerFile(e.target.value)
                updateParam('archive_inner_file', e.target.value)
              }}
              style={inputStyle}
            />
          </div>

          <div>
            <label style={labelStyle}>
              Path / Glob Pattern Filter
            </label>
            <input
              type="text"
              value={archivePattern}
              placeholder="e.g. *.csv or **/*.tsv"
              onChange={(e) => {
                setArchivePattern(e.target.value)
                updateParam('archive_pattern', e.target.value)
              }}
              style={inputStyle}
            />
          </div>
        </div>
      </div>

      {/* Parser & Delimiter Settings */}
      <div className="form-section dl-section" style={cardStyle}>
        <div className="dl-section-head">
          <h4 className="dl-section-title">Parsing</h4>
          <span className="dl-section-hint">Dialect and batch options</span>
        </div>
        <div className="dl-grid dl-grid-3">
          <div>
            <label style={labelStyle}>
              Delimiter
            </label>
            <select
              value={delimiter}
              onChange={(e) => {
                setDelimiter(e.target.value)
                updateParam('delimiter', e.target.value)
              }}
              style={inputStyle}
            >
              <option value="">Auto-Detect (, \t ; |)</option>
              <option value="&#9;">Tab (\t) — TSV</option>
              <option value=",">Comma (,) — CSV</option>
              <option value=";">Semicolon (;)</option>
              <option value="|">Pipe (|)</option>
            </select>
          </div>

          <div>
            <label style={labelStyle}>
              Batch Size
            </label>
            <input
              type="number"
              min="1"
              max="10000"
              step="1"
              value={batchSize}
              onChange={(e) => {
                const raw = e.target.value
                if (raw === '') {
                  setBatchSize('')
                  return
                }
                const parsed = parseInt(raw, 10)
                const val = isNaN(parsed) ? 1 : Math.max(1, Math.min(10000, parsed))
                setBatchSize(val)
                updateParam('batch_size', val)
              }}
              onBlur={() => {
                if (batchSize === '' || isNaN(Number(batchSize)) || Number(batchSize) < 1) {
                  setBatchSize(1000)
                  updateParam('batch_size', 1000)
                }
              }}
              placeholder="1000"
              style={inputStyle}
            />
            <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '0.25rem', display: 'block' }}>
              1 – 10,000 items
            </span>
          </div>

          <div>
            <label style={labelStyle}>
              Row Limit (0 = All)
            </label>
            <input
              type="number"
              min="0"
              max="1000000"
              step="1"
              value={rowLimit}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10) || 0
                setRowLimit(val)
                updateParam('row_limit', val)
              }}
              placeholder="0"
              style={inputStyle}
            />
            <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '0.25rem', display: 'block' }}>
              0 for unlimited
            </span>
          </div>
        </div>

        <div style={{ marginTop: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <input
            type="checkbox"
            id="dataload-has-header"
            checked={hasHeader}
            onChange={(e) => {
              setHasHeader(e.target.checked)
              updateParam('has_header', e.target.checked)
            }}
            style={{ width: 16, height: 16, accentColor: 'var(--accent)', cursor: 'pointer' }}
          />
          <label htmlFor="dataload-has-header" style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
            First row contains column headers
          </label>
        </div>
      </div>
    </div>
  )
}
