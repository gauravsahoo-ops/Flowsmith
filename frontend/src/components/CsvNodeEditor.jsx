import React, { useState, useEffect } from 'react'

const SF_CONTACT_FIELDS = [
  { field: 'LastName', label: 'Last Name', required: true, type: 'String (80)' },
  { field: 'FirstName', label: 'First Name', required: false, type: 'String (40)' },
  { field: 'Email', label: 'Email Address', required: false, type: 'Email (80)' },
  { field: 'Phone', label: 'Phone', required: false, type: 'Phone (40)' },
  { field: 'Department', label: 'Department', required: false, type: 'String (80)' },
  { field: 'Title', label: 'Title / Role', required: false, type: 'String (128)' },
  { field: 'MailingStreet', label: 'Mailing Street', required: false, type: 'String (255)' },
  { field: 'MailingCity', label: 'Mailing City', required: false, type: 'String (40)' },
  { field: 'MailingState', label: 'Mailing State', required: false, type: 'String (80)' },
  { field: 'MailingPostalCode', label: 'Mailing Postal Code', required: false, type: 'String (20)' },
  { field: 'MailingCountry', label: 'Mailing Country', required: false, type: 'String (80)' },
  { field: 'Description', label: 'Description / Notes', required: false, type: 'Text (32k)' },
]

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
  const [batchSize, setBatchSize] = useState(params.batch_size || 1000)
  const [rowLimit, setRowLimit] = useState(params.row_limit || 0)
  const [targetObject, setTargetObject] = useState(params.target_object || 'Contact')
  const [duplicatePolicy, setDuplicatePolicy] = useState(params.duplicate_policy || 'skip')
  const [dedupKey, setDedupKey] = useState(params.dedup_key || 'Email')
  const [persistToDb, setPersistToDb] = useState(params.persist_to_db !== false)

  const defaultMapping = SF_CONTACT_FIELDS.reduce((acc, f) => {
    acc[f.field] = f.field
    return acc
  }, {})

  const [fieldMapping, setFieldMapping] = useState(params.field_mapping || defaultMapping)
  const [fileName, setFileName] = useState(params.file_name || '')
  const [fileSize, setFileSize] = useState(params.file_size || '')
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

  const handleMappingChange = (targetField, sourceCol) => {
    const nextMapping = { ...fieldMapping, [sourceCol]: targetField }
    setFieldMapping(nextMapping)
    updateParam('field_mapping', nextMapping)
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
    const lines = rawText.split('\n').map(l => l.trim()).filter(Boolean).slice(0, 6)
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

    // Attempt uploading to Flowsmith files API to persist a secure file_id reference
    // rather than embedding the entire file in the workflow json definition
    try {
      const formData = new FormData()
      formData.append('file', file)
      setUploadProgress(50)

      const res = await fetch('/api/v1/files', {
        method: 'POST',
        body: formData,
      })

      if (res.ok) {
        const json = await res.json()
        const createdFileId = json.file_id || json.id || json.key
        if (createdFileId) {
          setFileId(createdFileId)
          setUploadProgress(100)
          setIsUploading(false)
          updateMultipleParams({
            file_id: createdFileId,
            file_name: name,
            file_size: sizeStr,
            source_type: 'upload',
            file_format: isArchive ? 'zip' : (isTsv ? 'tsv' : 'csv'),
          })

          // Also read sample for instant local preview if text
          if (!isArchive) {
            const reader = new FileReader()
            reader.onload = (e) => {
              const text = e.target?.result
              if (typeof text === 'string') {
                extractPreviewFromText(text, isTsv ? '\t' : (delimiter || ','))
              }
            }
            reader.readAsText(file.slice(0, 65536))
          }
          return
        }
      }
    } catch {
      // Fallback: local DataURL reading if backend files endpoint not available
    }

    // Fallback: Read as DataURL (archives) or Text (csv/tsv)
    const reader = new FileReader()
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
            file_format: 'zip',
          })
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
            file_format: isTsv ? 'tsv' : 'csv',
          })
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
    setPreviewRows([])
    setPreviewColumns([])
    updateMultipleParams({
      file_id: '',
      file_name: '',
      file_size: '',
      csv_content: '',
    })
  }

  return (
    <div className="flowsmith-dataload-editor" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', padding: '0.5rem' }}>
      {/* Node Identity Banner */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(30, 42, 60, 0.7) 0%, rgba(20, 26, 38, 0.9) 100%)',
        padding: '0.9rem 1.1rem',
        borderRadius: '8px',
        border: '1px solid #3b4252',
        boxShadow: '0 4px 12px rgba(0, 0, 0, 0.2)',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.5rem',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ fontSize: '1.05rem', fontWeight: 700, color: '#88c0d0', letterSpacing: '-0.01em' }}>
                Flowsmith DataLoad
              </span>
              <span style={{ fontSize: '0.7rem', background: '#434c5e', color: '#eceff4', padding: '0.15rem 0.45rem', borderRadius: '4px', fontWeight: 600 }}>
                flowsmith.data_load
              </span>
            </div>
            <div style={{ fontSize: '0.74rem', color: '#d8dee9', marginTop: '0.15rem' }}>
              Import, download, extract, parse, validate, and transform files for downstream workflows.
            </div>
          </div>
          <span style={{ fontSize: '0.72rem', background: 'rgba(163, 190, 140, 0.2)', color: '#a3be8c', padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid #a3be8c' }}>
            Production Ready
          </span>
        </div>

        {/* Supported Formats Tags */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', marginTop: '0.2rem' }}>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#242933', color: '#81a1c1', border: '1px solid #3b4252' }}>CSV</span>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#242933', color: '#a3be8c', border: '1px solid #3b4252' }}>TSV</span>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#242933', color: '#ebcb8b', border: '1px solid #3b4252' }}>ZIP (Single & Multi-File)</span>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#242933', color: '#d08770', border: '1px solid #3b4252' }}>Nested Archives</span>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#242933', color: '#b48ead', border: '1px solid #3b4252' }}>GZIP (.gz)</span>
        </div>
      </div>

      {/* Two Mandatory Input Modes Selector */}
      <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2e3440)' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', fontSize: '0.92rem', fontWeight: 600, color: '#eceff4' }}>
          Source Mode
        </h4>

        {/* Segmented Control */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.4rem', marginBottom: '1rem' }}>
          {[
            { id: 'upload', label: 'Option A: Upload File', desc: 'Direct / ObjectStore' },
            { id: 'url', label: 'Option B: Download URL', desc: 'Remote HTTP / HTTPS' },
            { id: 'file_path', label: 'Local File Path', desc: 'Container / Disk' },
            { id: 'inline', label: 'Inline Content', desc: 'Raw / Expression' },
          ].map((mode) => {
            const isActive = sourceMode === mode.id
            return (
              <button
                key={mode.id}
                type="button"
                onClick={() => handleSourceModeChange(mode.id)}
                style={{
                  padding: '0.6rem 0.4rem',
                  borderRadius: '6px',
                  background: isActive ? '#3b4252' : '#242933',
                  border: isActive ? '1px solid #88c0d0' : '1px solid #2e3440',
                  color: isActive ? '#88c0d0' : '#d8dee9',
                  cursor: 'pointer',
                  textAlign: 'center',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.2rem',
                  alignItems: 'center',
                  transition: 'all 0.15s ease',
                }}
              >
                <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>{mode.label}</span>
                <span style={{ fontSize: '0.67rem', color: isActive ? '#eceff4' : '#6c778c' }}>{mode.desc}</span>
              </button>
            )
          })}
        </div>

        {/* Option A: Upload File */}
        {sourceMode === 'upload' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={handleDrop}
              style={{
                border: isDragOver ? '2px dashed #88c0d0' : '2px dashed #434c5e',
                borderRadius: '8px',
                padding: '1.25rem',
                textAlign: 'center',
                background: isDragOver ? 'rgba(136, 192, 208, 0.08)' : '#242933',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
              }}
              onClick={() => document.getElementById('dataload-file-picker')?.click()}
            >
              <input
                id="dataload-file-picker"
                type="file"
                accept=".csv,.tsv,.tab,.txt,.zip,.gz,.tgz,.tar"
                onChange={handleFileInputChange}
                style={{ display: 'none' }}
              />
              <div style={{ fontSize: '1.4rem', marginBottom: '0.35rem' }}>📁</div>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e5e9f0' }}>
                Choose file or drag & drop here
              </div>
              <div style={{ fontSize: '0.72rem', color: '#81a1c1', marginTop: '0.25rem' }}>
                Supports CSV, TSV, and ZIP archives (.zip, .gz, .tar). Files are stored securely in Flowsmith ObjectStore.
              </div>
            </div>

            {isUploading && (
              <div style={{ background: '#242933', padding: '0.5rem', borderRadius: '4px', border: '1px solid #3b4252' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
                  <span>Uploading to ObjectStore...</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div style={{ background: '#3b4252', height: '4px', borderRadius: '2px', overflow: 'hidden' }}>
                  <div style={{ width: `${uploadProgress}%`, height: '100%', background: '#88c0d0', transition: 'width 0.2s' }} />
                </div>
              </div>
            )}

            {(fileName || fileId) && (
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '0.65rem 0.85rem',
                borderRadius: '6px',
                background: '#2b303c',
                border: '1px solid #3b4252',
              }}>
                <div>
                  <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#a3be8c', display: 'block' }}>
                    ✓ Loaded: {fileName || 'File'}
                  </span>
                  <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.72rem', color: '#81a1c1', marginTop: '0.15rem' }}>
                    {fileSize && <span>Size: {fileSize}</span>}
                    {fileId && <span>Ref ID: {fileId}</span>}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleClearUploadedFile}
                  style={{
                    padding: '0.25rem 0.6rem',
                    background: '#bf616a',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '4px',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                  }}
                >
                  Clear File
                </button>
              </div>
            )}
          </div>
        )}

        {/* Option B: Download from URL */}
        {sourceMode === 'url' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
                Download URL (Supports Expressions)
              </label>
              <input
                type="text"
                value={downloadUrl}
                placeholder="https://example.com/data/contacts.csv or {{ $json.export_url }}"
                onChange={(e) => {
                  setDownloadUrl(e.target.value)
                  updateParam('download_url', e.target.value)
                }}
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  borderRadius: '4px',
                  background: '#242933',
                  color: '#e5e9f0',
                  border: '1px solid #3b4252',
                  fontSize: '0.85rem',
                }}
              />
            </div>

            {/* SSRF & Security Guard Indicator */}
            <div style={{
              background: 'rgba(163, 190, 140, 0.1)',
              border: '1px solid #4c566a',
              borderRadius: '4px',
              padding: '0.45rem 0.75rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              fontSize: '0.74rem',
              color: '#d8dee9',
            }}>
              <span style={{ color: '#a3be8c' }}>🔒</span>
              <span><strong>SSRF Guard Active:</strong> Rejects loopback, private networks (RFC 1918), and cloud metadata destinations. Validates DNS and redirects.</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
                  Authentication Type
                </label>
                <select
                  value={authType}
                  onChange={(e) => {
                    setAuthType(e.target.value)
                    updateParam('auth_type', e.target.value)
                  }}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: '4px',
                    background: '#242933',
                    color: '#e5e9f0',
                    border: '1px solid #3b4252',
                    fontSize: '0.85rem',
                  }}
                >
                  <option value="none">None (Public Download)</option>
                  <option value="bearer">Bearer Token</option>
                  <option value="basic">Basic Auth (user:pass)</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
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
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: '4px',
                    background: authType === 'none' ? '#1e222d' : '#242933',
                    color: '#e5e9f0',
                    border: '1px solid #3b4252',
                    fontSize: '0.85rem',
                  }}
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
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
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: '4px',
                    background: '#242933',
                    color: '#e5e9f0',
                    border: '1px solid #3b4252',
                    fontSize: '0.85rem',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
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
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: '4px',
                    background: '#242933',
                    color: '#e5e9f0',
                    border: '1px solid #3b4252',
                    fontSize: '0.85rem',
                  }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Local File Path */}
        {sourceMode === 'file_path' && (
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
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
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
              }}
            />
          </div>
        )}

        {/* Inline Content */}
        {sourceMode === 'inline' && (
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
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
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
                fontFamily: 'monospace',
              }}
            />
          </div>
        )}
      </div>

      {/* Structure Preview Panel (when preview data is present) */}
      {previewColumns.length > 0 && (
        <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid #434c5e' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <h4 style={{ margin: 0, fontSize: '0.88rem', fontWeight: 600, color: '#88c0d0' }}>
              Detected Structure Preview ({previewColumns.length} columns)
            </h4>
            <span style={{ fontSize: '0.72rem', color: '#a3be8c' }}>Showing first {previewRows.length} rows</span>
          </div>
          <div style={{ overflowX: 'auto', maxHeight: '160px', border: '1px solid #2e3440', borderRadius: '4px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.76rem', textAlign: 'left' }}>
              <thead>
                <tr style={{ background: '#2e3440', color: '#d8dee9' }}>
                  {previewColumns.map((col) => (
                    <th key={col} style={{ padding: '0.35rem 0.5rem', borderBottom: '1px solid #3b4252' }}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? '#242933' : '#1e222d' }}>
                    {previewColumns.map((col) => (
                      <td key={col} style={{ padding: '0.35rem 0.5rem', color: '#eceff4', borderBottom: '1px solid #2e3440' }}>{row[col]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Archive Configuration (Shown for ZIP / TAR) */}
      <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2e3440)' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', fontSize: '0.92rem', fontWeight: 600, color: '#eceff4' }}>
          Archive & ZIP Extraction Settings
        </h4>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
              Process Mode
            </label>
            <select
              value={archiveProcessMode}
              onChange={(e) => {
                setArchiveProcessMode(e.target.value)
                updateParam('archive_process_mode', e.target.value)
              }}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
              }}
            >
              <option value="single">Process Single File (Default)</option>
              <option value="combine">Combine All Matching Files</option>
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
              Header Match Policy (Combine Mode)
            </label>
            <select
              value={archiveHeaderMode}
              onChange={(e) => {
                setArchiveHeaderMode(e.target.value)
                updateParam('archive_header_mode', e.target.value)
              }}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
              }}
            >
              <option value="union">Union (Merge All Columns)</option>
              <option value="strict">Strict (Fail on Mismatch)</option>
              <option value="first">First File Headers Only</option>
            </select>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '0.75rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
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
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
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
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
              }}
            />
          </div>
        </div>
      </div>

      {/* Parser & Delimiter Settings */}
      <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2e3440)' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', fontSize: '0.92rem', fontWeight: 600, color: '#eceff4' }}>
          Parser & Delimiter Settings
        </h4>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
              Delimiter
            </label>
            <select
              value={delimiter}
              onChange={(e) => {
                setDelimiter(e.target.value)
                updateParam('delimiter', e.target.value)
              }}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
              }}
            >
              <option value="">Auto-Detect (, \t ; |)</option>
              <option value="&#9;">Tab (\t) — TSV</option>
              <option value=",">Comma (,) — CSV</option>
              <option value=";">Semicolon (;)</option>
              <option value="|">Pipe (|)</option>
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
              Batch Size
            </label>
            <input
              type="number"
              min="100"
              max="10000"
              step="100"
              value={batchSize}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10) || 1000
                setBatchSize(val)
                updateParam('batch_size', val)
              }}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
              }}
            />
          </div>
        </div>

        <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <input
            type="checkbox"
            id="dataload-has-header"
            checked={hasHeader}
            onChange={(e) => {
              setHasHeader(e.target.checked)
              updateParam('has_header', e.target.checked)
            }}
          />
          <label htmlFor="dataload-has-header" style={{ fontSize: '0.85rem', color: '#d8dee9', cursor: 'pointer' }}>
            First row contains column headers
          </label>
        </div>
      </div>

      {/* Target Schema & Visual Field Mapping */}
      <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2e3440)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
          <h4 style={{ margin: 0, fontSize: '0.92rem', fontWeight: 600, color: '#eceff4' }}>
            Field Mapping ({targetObject})
          </h4>
          <span style={{ fontSize: '0.75rem', color: '#81a1c1' }}>12 Standard Target Fields</span>
        </div>

        <div style={{ maxHeight: '260px', overflowY: 'auto', border: '1px solid #3b4252', borderRadius: '4px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem', textAlign: 'left' }}>
            <thead>
              <tr style={{ background: '#2e3440', color: '#d8dee9', borderBottom: '1px solid #434c5e' }}>
                <th style={{ padding: '0.5rem' }}>Target Field</th>
                <th style={{ padding: '0.5rem' }}>Type</th>
                <th style={{ padding: '0.5rem' }}>Source Column</th>
              </tr>
            </thead>
            <tbody>
              {SF_CONTACT_FIELDS.map((sfField) => {
                const currentSource = Object.keys(fieldMapping).find(k => fieldMapping[k] === sfField.field) || sfField.field
                return (
                  <tr key={sfField.field} style={{ borderBottom: '1px solid #2e3440', background: '#242933' }}>
                    <td style={{ padding: '0.5rem', color: '#eceff4' }}>
                      {sfField.label} ({sfField.field})
                      {sfField.required && (
                        <span style={{ color: '#bf616a', marginLeft: '0.25rem', fontWeight: 'bold' }}>*</span>
                      )}
                    </td>
                    <td style={{ padding: '0.5rem', color: '#81a1c1' }}>{sfField.type}</td>
                    <td style={{ padding: '0.5rem' }}>
                      <input
                        type="text"
                        value={currentSource}
                        onChange={(e) => handleMappingChange(sfField.field, e.target.value)}
                        style={{
                          width: '100%',
                          padding: '0.25rem 0.5rem',
                          background: '#2e3440',
                          border: '1px solid #4c566a',
                          borderRadius: '3px',
                          color: '#88c0d0',
                          fontSize: '0.8rem',
                        }}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Duplicate Handling & Database Staging */}
      <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2e3440)' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', fontSize: '0.92rem', fontWeight: 600, color: '#eceff4' }}>
          Duplicate Policy & Database Persistence
        </h4>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
              Duplicate Policy
            </label>
            <select
              value={duplicatePolicy}
              onChange={(e) => {
                setDuplicatePolicy(e.target.value)
                updateParam('duplicate_policy', e.target.value)
              }}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
              }}
            >
              <option value="skip">Skip Duplicate Rows (Preserve First)</option>
              <option value="update">Update / Overwrite Duplicates</option>
              <option value="error">Raise Error on Duplicates</option>
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
              Duplicate Key
            </label>
            <input
              type="text"
              value={dedupKey}
              onChange={(e) => {
                setDedupKey(e.target.value)
                updateParam('dedup_key', e.target.value)
              }}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem',
              }}
            />
          </div>
        </div>

        <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <input
            type="checkbox"
            id="dataload-persist-db"
            checked={persistToDb}
            onChange={(e) => {
              setPersistToDb(e.target.checked)
              updateParam('persist_to_db', e.target.checked)
            }}
          />
          <label htmlFor="dataload-persist-db" style={{ fontSize: '0.85rem', color: '#d8dee9', cursor: 'pointer' }}>
            Persist staged records to PostgreSQL database (table: staged_contacts)
          </label>
        </div>
      </div>
    </div>
  )
}
