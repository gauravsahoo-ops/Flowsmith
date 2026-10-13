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
    if (params.csv_content && !params.file_name) return 'inline'
    return 'upload'
  }

  const [sourceMode, setSourceMode] = useState(getInitialSourceMode())
  const [downloadUrl, setDownloadUrl] = useState(params.download_url || '')
  const [filePath, setFilePath] = useState(params.file_path || '')
  const [csvContent, setCsvContent] = useState(params.csv_content || '')
  const [archiveInnerFile, setArchiveInnerFile] = useState(params.archive_inner_file || '')
  const [delimiter, setDelimiter] = useState(params.delimiter || '')
  const [hasHeader, setHasHeader] = useState(params.has_header !== false)
  const [batchSize, setBatchSize] = useState(params.batch_size || 1000)
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
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  const processUploadedFile = (file) => {
    if (!file) return
    const name = file.name
    const sizeStr = formatBytes(file.size)
    setFileName(name)
    setFileSize(sizeStr)

    const lowerName = name.toLowerCase()
    const isArchive = lowerName.endsWith('.zip') || lowerName.endsWith('.gz') || lowerName.endsWith('.tgz') || lowerName.endsWith('.tar')
    const isTsv = lowerName.endsWith('.tsv') || lowerName.endsWith('.tab')

    // If TSV detected and delimiter is empty, offer auto tab
    if (isTsv && !delimiter) {
      setDelimiter('\t')
      updateParam('delimiter', '\t')
    }

    const reader = new FileReader()
    if (isArchive) {
      // Read archive files as DataURL (base64) so backend can unpack bytes
      reader.onload = (event) => {
        const content = event.target?.result
        if (typeof content === 'string') {
          setCsvContent(content)
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
      // Read plain tabular text
      reader.onload = (event) => {
        const content = event.target?.result
        if (typeof content === 'string') {
          setCsvContent(content)
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
    setCsvContent('')
    updateMultipleParams({
      csv_content: '',
      file_name: '',
      file_size: '',
    })
  }

  return (
    <div className="csv-node-editor" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', padding: '0.5rem' }}>
      {/* Title & Format Capability Banner */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(76, 86, 106, 0.25) 0%, rgba(46, 52, 64, 0.4) 100%)',
        padding: '0.85rem 1rem',
        borderRadius: '8px',
        border: '1px solid #434c5e',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.4rem',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '0.95rem', fontWeight: 700, color: '#eceff4' }}>
            Delimited & Archive Ingest Engine
          </span>
          <span style={{ fontSize: '0.72rem', background: '#3b4252', color: '#88c0d0', padding: '0.2rem 0.5rem', borderRadius: '4px', fontWeight: 600 }}>
            v1.0 Enterprise
          </span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#2e3440', color: '#81a1c1', border: '1px solid #3b4252' }}>CSV</span>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#2e3440', color: '#a3be8c', border: '1px solid #3b4252' }}>TSV (Tab-Separated)</span>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#2e3440', color: '#ebcb8b', border: '1px solid #3b4252' }}>Zipped CSV</span>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#2e3440', color: '#d08770', border: '1px solid #3b4252' }}>Zipped TSV</span>
          <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', borderRadius: '3px', background: '#2e3440', color: '#b48ead', border: '1px solid #3b4252' }}>GZ / TAR</span>
        </div>
      </div>

      {/* Source Selection Mode Tabs */}
      <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2e3440)' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', fontSize: '0.92rem', fontWeight: 600, color: '#eceff4' }}>
          Input Source Options
        </h4>

        {/* Source Mode Selector Buttons */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.35rem', marginBottom: '1rem' }}>
          {[
            { id: 'upload', label: 'Import File', desc: 'CSV, TSV, ZIP' },
            { id: 'url', label: 'Download Link', desc: 'Remote URL' },
            { id: 'file_path', label: 'File Path', desc: 'Disk / Container' },
            { id: 'inline', label: 'Inline Content', desc: 'Raw / Text' },
          ].map((mode) => {
            const isActive = sourceMode === mode.id
            return (
              <button
                key={mode.id}
                type="button"
                onClick={() => handleSourceModeChange(mode.id)}
                style={{
                  padding: '0.5rem 0.4rem',
                  borderRadius: '6px',
                  background: isActive ? '#3b4252' : '#242933',
                  border: isActive ? '1px solid #88c0d0' : '1px solid #2e3440',
                  color: isActive ? '#88c0d0' : '#d8dee9',
                  cursor: 'pointer',
                  textAlign: 'center',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.15rem',
                  alignItems: 'center',
                  transition: 'all 0.15s ease',
                }}
              >
                <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>{mode.label}</span>
                <span style={{ fontSize: '0.68rem', color: isActive ? '#eceff4' : '#6c778c' }}>{mode.desc}</span>
              </button>
            )
          })}
        </div>

        {/* Option A: Import / Upload File */}
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
                transition: 'border-color 0.2s ease, background 0.2s ease',
              }}
              onClick={() => document.getElementById('csv-file-picker')?.click()}
            >
              <input
                id="csv-file-picker"
                type="file"
                accept=".csv,.tsv,.tab,.txt,.zip,.gz,.tgz,.tar,text/csv,text/tab-separated-values,application/zip,application/gzip,application/x-zip-compressed"
                onChange={handleFileInputChange}
                style={{ display: 'none' }}
              />
              <div style={{ fontSize: '1.25rem', marginBottom: '0.35rem' }}>📂</div>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e5e9f0' }}>
                Click to browse or drop file here
              </div>
              <div style={{ fontSize: '0.72rem', color: '#81a1c1', marginTop: '0.25rem' }}>
                Supports .csv, .tsv, .zip (zipped CSV/TSV), .gz, and .tar archives
              </div>
            </div>

            {fileName && (
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '0.6rem 0.85rem',
                borderRadius: '6px',
                background: '#2b303c',
                border: '1px solid #3b4252',
              }}>
                <div>
                  <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#a3be8c', display: 'block' }}>
                    ✓ Loaded: {fileName}
                  </span>
                  {fileSize && (
                    <span style={{ fontSize: '0.72rem', color: '#81a1c1' }}>
                      Size: {fileSize}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={handleClearUploadedFile}
                  style={{
                    padding: '0.25rem 0.5rem',
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

            {fileName && (fileName.toLowerCase().endsWith('.zip') || fileName.toLowerCase().endsWith('.tar')) && (
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
                  Archive Inner Filename (Optional)
                </label>
                <input
                  type="text"
                  value={archiveInnerFile}
                  placeholder="e.g. contacts.tsv (auto-extracts first tabular file if left empty)"
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
            )}
          </div>
        )}

        {/* Option B: Download Link (URL) */}
        {sourceMode === 'url' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
                Remote Download Link (HTTP / HTTPS)
              </label>
              <input
                type="text"
                value={downloadUrl}
                placeholder="https://example.com/data/contacts.csv or https://example.com/archive.zip"
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
              <span style={{ fontSize: '0.74rem', color: '#81a1c1', marginTop: '0.35rem', display: 'block' }}>
                Flowsmith securely downloads and streams this link at execution time. Supports CSV, TSV, and Zipped archives (.zip, .gz).
              </span>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
                Archive Inner Filename (Optional for ZIP / TAR)
              </label>
              <input
                type="text"
                value={archiveInnerFile}
                placeholder="e.g. export.tsv (auto-detects first tabular file if empty)"
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
          </div>
        )}

        {/* Option C: Server File Path */}
        {sourceMode === 'file_path' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
                Filesystem or Container File Path
              </label>
              <input
                type="text"
                value={filePath}
                placeholder="e.g. flowsmith_salesforce_contact_10000.csv or /data/contacts.zip or contacts.tsv"
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

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
                Archive Inner Filename (Optional for ZIP / TAR)
              </label>
              <input
                type="text"
                value={archiveInnerFile}
                placeholder="e.g. inner_contacts.csv"
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
          </div>
        )}

        {/* Option D: Inline Content */}
        {sourceMode === 'inline' && (
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
              Raw CSV / TSV Text or Expression
            </label>
            <textarea
              rows={6}
              value={csvContent.startsWith('data:') ? '/* Base64 data loaded */' : csvContent}
              placeholder="FirstName,LastName,Email\nJohn,Doe,john@example.com"
              onChange={(e) => {
                setCsvContent(e.target.value)
                updateParam('csv_content', e.target.value)
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

      {/* Parser & Dialect Configuration */}
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
            id="csv-has-header"
            checked={hasHeader}
            onChange={(e) => {
              setHasHeader(e.target.checked)
              updateParam('has_header', e.target.checked)
            }}
          />
          <label htmlFor="csv-has-header" style={{ fontSize: '0.85rem', color: '#d8dee9', cursor: 'pointer' }}>
            First row contains column headers
          </label>
        </div>
      </div>

      {/* Target Schema & Visual Field Mapping */}
      <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2e3440)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
          <h4 style={{ margin: 0, fontSize: '0.92rem', fontWeight: 600, color: '#eceff4' }}>
            Salesforce Field Mapping ({targetObject})
          </h4>
          <span style={{ fontSize: '0.75rem', color: '#81a1c1' }}>12 Standard Fields</span>
        </div>

        <div style={{ maxHeight: '280px', overflowY: 'auto', border: '1px solid #3b4252', borderRadius: '4px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem', textAlign: 'left' }}>
            <thead>
              <tr style={{ background: '#2e3440', color: '#d8dee9', borderBottom: '1px solid #434c5e' }}>
                <th style={{ padding: '0.5rem' }}>Salesforce Field</th>
                <th style={{ padding: '0.5rem' }}>Field Type</th>
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
            id="csv-persist-db"
            checked={persistToDb}
            onChange={(e) => {
              setPersistToDb(e.target.checked)
              updateParam('persist_to_db', e.target.checked)
            }}
          />
          <label htmlFor="csv-persist-db" style={{ fontSize: '0.85rem', color: '#d8dee9', cursor: 'pointer' }}>
            Persist staged records to PostgreSQL database (table: staged_contacts)
          </label>
        </div>
      </div>
    </div>
  )
}
