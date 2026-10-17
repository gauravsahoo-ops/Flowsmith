import React, { useState } from 'react'
import { getToken } from '../api'

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

const SF_LEAD_FIELDS = [
  { field: 'LastName', label: 'Last Name', required: true, type: 'String (80)' },
  { field: 'FirstName', label: 'First Name', required: false, type: 'String (40)' },
  { field: 'Company', label: 'Company Name', required: true, type: 'String (255)' },
  { field: 'Email', label: 'Email Address', required: false, type: 'Email (80)' },
  { field: 'Phone', label: 'Phone', required: false, type: 'Phone (40)' },
  { field: 'Status', label: 'Status', required: false, type: 'Picklist (40)' },
  { field: 'Title', label: 'Title / Role', required: false, type: 'String (128)' },
  { field: 'LeadSource', label: 'Lead Source', required: false, type: 'Picklist (40)' },
  { field: 'City', label: 'City', required: false, type: 'String (40)' },
  { field: 'State', label: 'State', required: false, type: 'String (80)' },
  { field: 'PostalCode', label: 'Postal Code', required: false, type: 'String (20)' },
  { field: 'Country', label: 'Country', required: false, type: 'String (80)' },
]

const SF_ACCOUNT_FIELDS = [
  { field: 'Name', label: 'Account Name', required: true, type: 'String (255)' },
  { field: 'AccountNumber', label: 'Account Number', required: false, type: 'String (40)' },
  { field: 'Industry', label: 'Industry', required: false, type: 'Picklist (40)' },
  { field: 'AnnualRevenue', label: 'Annual Revenue', required: false, type: 'Currency (18,0)' },
  { field: 'Phone', label: 'Phone', required: false, type: 'Phone (40)' },
  { field: 'Website', label: 'Website URL', required: false, type: 'URL (255)' },
  { field: 'BillingStreet', label: 'Billing Street', required: false, type: 'String (255)' },
  { field: 'BillingCity', label: 'Billing City', required: false, type: 'String (40)' },
  { field: 'BillingState', label: 'Billing State', required: false, type: 'String (80)' },
  { field: 'BillingPostalCode', label: 'Billing Postal Code', required: false, type: 'String (20)' },
  { field: 'BillingCountry', label: 'Billing Country', required: false, type: 'String (80)' },
]

function getStandardFieldsForObject(objType) {
  if (objType === 'Lead') return SF_LEAD_FIELDS
  if (objType === 'Account') return SF_ACCOUNT_FIELDS
  if (objType === 'Custom') return []
  return SF_CONTACT_FIELDS
}

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
  const [targetObject, setTargetObject] = useState(params.target_object || 'Contact')

  const activeStandardFields = getStandardFieldsForObject(targetObject)

  const [customTargetFields, setCustomTargetFields] = useState(() => {
    const fromParams = Array.isArray(params.custom_target_fields) ? params.custom_target_fields : []
    const knownFields = new Set([
      ...activeStandardFields.map(f => f.field),
      ...fromParams.map(f => f.field),
    ])
    const extra = []
    if (params.field_mapping && typeof params.field_mapping === 'object') {
      for (const targetName of Object.values(params.field_mapping)) {
        if (targetName && typeof targetName === 'string' && !knownFields.has(targetName)) {
          knownFields.add(targetName)
          extra.push({
            field: targetName,
            label: targetName,
            type: 'Custom (String)',
            required: false,
            isCustom: true,
          })
        }
      }
    }
    return [...fromParams, ...extra]
  })

  // Combined active target fields (standard + custom)
  const allTargetFields = [...activeStandardFields, ...customTargetFields]

  const defaultMapping = allTargetFields.reduce((acc, f) => {
    acc[f.field] = f.field
    return acc
  }, {})

  const [fieldMapping, setFieldMapping] = useState(
    params.field_mapping && Object.keys(params.field_mapping).length > 0
      ? params.field_mapping
      : defaultMapping
  )

  // State for adding a new target field
  const [showAddTargetModal, setShowAddTargetModal] = useState(false)
  const [newTargetName, setNewTargetName] = useState('')
  const [newTargetType, setNewTargetType] = useState('String (255)')
  const [newTargetRequired, setNewTargetRequired] = useState(false)
  const [newTargetSourceCol, setNewTargetSourceCol] = useState('')
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

  const handleMappingChange = (targetField, sourceCol) => {
    const nextMapping = { ...fieldMapping }
    // Clean up any other source column previously assigned to this targetField
    for (const [k, v] of Object.entries(nextMapping)) {
      if (v === targetField) {
        delete nextMapping[k]
      }
    }
    if (sourceCol && sourceCol.trim()) {
      nextMapping[sourceCol.trim()] = targetField
    }
    setFieldMapping(nextMapping)
    updateParam('field_mapping', nextMapping)
  }

  const handleAddTargetField = (e) => {
    e?.preventDefault()
    const trimmed = (newTargetName || '').trim()
    if (!trimmed) return

    if (allTargetFields.some(f => f.field.toLowerCase() === trimmed.toLowerCase())) {
      alert(`Target field "${trimmed}" already exists in the mapping table.`)
      return
    }

    const newFieldObj = {
      field: trimmed,
      label: trimmed,
      type: newTargetType || 'String (255)',
      required: Boolean(newTargetRequired),
      isCustom: true,
    }

    const nextCustomFields = [...customTargetFields, newFieldObj]
    setCustomTargetFields(nextCustomFields)

    const sourceCol = (newTargetSourceCol || trimmed).trim()
    const nextMapping = { ...fieldMapping }
    if (sourceCol) {
      nextMapping[sourceCol] = trimmed
    }
    setFieldMapping(nextMapping)

    updateMultipleParams({
      custom_target_fields: nextCustomFields,
      field_mapping: nextMapping,
    })

    setNewTargetName('')
    setNewTargetSourceCol('')
    setNewTargetRequired(false)
    setShowAddTargetModal(false)
  }

  const handleRemoveCustomTargetField = (targetFieldToRemove) => {
    const nextCustomFields = customTargetFields.filter(f => f.field !== targetFieldToRemove)
    setCustomTargetFields(nextCustomFields)

    const nextMapping = { ...fieldMapping }
    for (const [k, v] of Object.entries(nextMapping)) {
      if (v === targetFieldToRemove) {
        delete nextMapping[k]
      }
    }
    setFieldMapping(nextMapping)

    updateMultipleParams({
      custom_target_fields: nextCustomFields,
      field_mapping: nextMapping,
    })
  }

  const handleAddAllUnmappedColumns = () => {
    if (!previewColumns || previewColumns.length === 0) return
    const currentMappedSources = new Set(Object.keys(fieldMapping))
    const currentTargetNames = new Set(allTargetFields.map(f => f.field.toLowerCase()))

    const newCustoms = []
    const nextMapping = { ...fieldMapping }

    for (const col of previewColumns) {
      if (!currentMappedSources.has(col) && !currentTargetNames.has(col.toLowerCase())) {
        newCustoms.push({
          field: col,
          label: col,
          type: 'Auto-Detected',
          required: false,
          isCustom: true,
        })
        nextMapping[col] = col
        currentTargetNames.add(col.toLowerCase())
      }
    }

    if (newCustoms.length === 0) return

    const combinedCustoms = [...customTargetFields, ...newCustoms]
    setCustomTargetFields(combinedCustoms)
    setFieldMapping(nextMapping)

    updateMultipleParams({
      custom_target_fields: combinedCustoms,
      field_mapping: nextMapping,
    })
  }

  const handleAutoMapAll = () => {
    const nextMapping = allTargetFields.reduce((acc, f) => {
      const match = previewColumns.find(c => c.toLowerCase() === f.field.toLowerCase())
      const sourceCol = match || f.field
      acc[sourceCol] = f.field
      return acc
    }, {})
    setFieldMapping(nextMapping)
    updateParam('field_mapping', nextMapping)
  }

  const handleClearMapping = () => {
    setFieldMapping({})
    updateParam('field_mapping', {})
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
    padding: '0.55rem 0.75rem',
    borderRadius: 'var(--radius-sm)',
    background: 'var(--panel-2)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    fontSize: '0.84rem',
    fontFamily: 'inherit',
    outline: 'none',
    boxShadow: 'var(--shadow-xs)',
    transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
  }

  const labelStyle = {
    display: 'block',
    fontSize: '0.78rem',
    fontWeight: 600,
    color: 'var(--text-secondary)',
    marginBottom: '0.35rem',
    letterSpacing: '-0.01em',
  }

  const cardStyle = {
    background: 'var(--panel)',
    padding: '1rem',
    borderRadius: 'var(--radius-md)',
    border: '1px solid var(--border)',
    boxShadow: 'var(--shadow-card)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  }

  return (
    <div className="flowsmith-dataload-editor" style={{ display: 'flex', flexDirection: 'column', gap: '1rem', padding: '0.25rem' }}>
      {/* Node Identity Banner */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(79, 70, 229, 0.12) 0%, rgba(37, 99, 235, 0.06) 100%)',
        padding: '1rem 1.2rem',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.6rem',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
              <span style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.01em' }}>
                Flowsmith DataLoad
              </span>
              <span style={{
                fontSize: '0.68rem',
                background: 'var(--panel-3)',
                color: 'var(--text-secondary)',
                padding: '0.15rem 0.45rem',
                borderRadius: 'var(--radius-xs)',
                fontWeight: 600,
                border: '1px solid var(--border)',
              }}>
                flowsmith.data_load
              </span>
            </div>
            <div style={{ fontSize: '0.74rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
              Import, download, extract, parse, validate, and transform files for downstream workflows.
            </div>
          </div>
          <span style={{
            fontSize: '0.72rem',
            background: 'rgba(5, 150, 105, 0.12)',
            color: 'var(--green)',
            padding: '0.2rem 0.55rem',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid rgba(5, 150, 105, 0.3)',
            fontWeight: 600,
          }}>
            Production Ready
          </span>
        </div>

        {/* Supported Formats Tags */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginTop: '0.1rem' }}>
          {[
            { label: 'CSV', color: 'var(--blue)' },
            { label: 'TSV', color: 'var(--green)' },
            { label: 'ZIP (Single & Multi-File)', color: 'var(--amber)' },
            { label: 'Nested Archives', color: 'var(--accent)' },
            { label: 'GZIP (.gz)', color: 'var(--purple)' },
          ].map((tag) => (
            <span
              key={tag.label}
              style={{
                fontSize: '0.68rem',
                padding: '0.15rem 0.5rem',
                borderRadius: 'var(--radius-xs)',
                background: 'var(--panel-2)',
                color: tag.color,
                border: '1px solid var(--border)',
                fontWeight: 500,
              }}
            >
              {tag.label}
            </span>
          ))}
        </div>
      </div>

      {/* Two Mandatory Input Modes Selector */}
      <div className="form-section" style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h4 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: 'var(--text)' }}>
            Source Mode
          </h4>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Select ingestion mechanism</span>
        </div>

        {/* Segmented Control */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem' }}>
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
                  padding: '0.65rem 0.5rem',
                  borderRadius: 'var(--radius-sm)',
                  background: isActive ? 'var(--accent-subtle)' : 'var(--panel-2)',
                  border: isActive ? '1px solid var(--accent)' : '1px solid var(--border)',
                  color: isActive ? 'var(--text)' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  textAlign: 'center',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.2rem',
                  alignItems: 'center',
                  transition: 'all 0.15s ease',
                  boxShadow: isActive ? '0 0 0 1px var(--accent-subtle)' : 'none',
                }}
              >
                <span style={{ fontSize: '0.78rem', fontWeight: 600 }}>{mode.label}</span>
                <span style={{ fontSize: '0.67rem', color: isActive ? 'var(--text-secondary)' : 'var(--muted)' }}>{mode.desc}</span>
              </button>
            )
          })}
        </div>

        {/* Option A: Upload File */}
        {sourceMode === 'upload' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '0.25rem' }}>
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={handleDrop}
              style={{
                border: isDragOver ? '2px dashed var(--accent)' : '2px dashed var(--border-strong)',
                borderRadius: 'var(--radius-md)',
                padding: '1.4rem',
                textAlign: 'center',
                background: isDragOver ? 'rgba(79, 70, 229, 0.08)' : 'var(--panel-2)',
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
              <div style={{
                width: 40,
                height: 40,
                borderRadius: '50%',
                background: 'rgba(79, 70, 229, 0.12)',
                color: 'var(--accent)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '0.5rem',
              }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
              </div>
              <div style={{ fontSize: '0.86rem', fontWeight: 600, color: 'var(--text)' }}>
                Choose file or drag & drop here
              </div>
              <div style={{ fontSize: '0.74rem', color: 'var(--text-dim)', marginTop: '0.25rem', maxWidth: 440, marginInline: 'auto' }}>
                Supports CSV, TSV, and ZIP archives (.zip, .gz, .tar). Files are stored securely in Flowsmith ObjectStore.
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
              <label style={labelStyle}>
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
                style={inputStyle}
              />
            </div>

            {/* SSRF & Security Guard Indicator */}
            <div style={{
              background: 'rgba(5, 150, 105, 0.08)',
              border: '1px solid rgba(5, 150, 105, 0.25)',
              borderRadius: 'var(--radius-sm)',
              padding: '0.55rem 0.85rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '0.74rem',
              color: 'var(--text-secondary)',
            }}>
              <span style={{ color: 'var(--green)', fontSize: '0.9rem' }}>🔒</span>
              <span><strong>SSRF Guard Active:</strong> Rejects loopback, private networks (RFC 1918), and cloud metadata destinations. Validates DNS and redirects.</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
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

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
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
                fontFamily: 'var(--font-mono)',
                fontSize: '0.8rem',
                lineHeight: 1.5,
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
      <div className="form-section" style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h4 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: 'var(--text)' }}>
            Archive & ZIP Extraction Settings
          </h4>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Multi-file unpacking rules</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
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

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
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
      <div className="form-section" style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h4 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: 'var(--text)' }}>
            Parser & Delimiter Settings
          </h4>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Dialect & batch options</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.75rem' }}>
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

      {/* Target Schema & Visual Field Mapping */}
      <div className="form-section" style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <h4 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: 'var(--text)' }}>
                Field Mapping
              </h4>
              <select
                value={targetObject}
                onChange={(e) => {
                  const newObj = e.target.value
                  setTargetObject(newObj)
                  updateParam('target_object', newObj)
                }}
                style={{
                  ...inputStyle,
                  width: 'auto',
                  padding: '0.2rem 0.5rem',
                  fontSize: '0.74rem',
                  fontWeight: 600,
                  color: 'var(--accent)',
                }}
              >
                <option value="Contact">Salesforce Contact</option>
                <option value="Lead">Salesforce Lead</option>
                <option value="Account">Salesforce Account</option>
                <option value="Custom">Custom Schema / Table</option>
              </select>
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '0.15rem' }}>
              Map input columns to target schema fields ({allTargetFields.length} target fields configured)
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={() => setShowAddTargetModal(!showAddTargetModal)}
              style={{
                padding: '0.3rem 0.65rem',
                borderRadius: 'var(--radius-xs)',
                background: showAddTargetModal ? 'var(--accent)' : 'var(--panel-2)',
                border: '1px solid var(--accent)',
                color: showAddTargetModal ? '#fff' : 'var(--accent)',
                fontSize: '0.72rem',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '0.3rem',
              }}
            >
              <span>+</span> Add Target Field
            </button>
            {previewColumns && previewColumns.length > 0 && (
              <button
                type="button"
                onClick={handleAddAllUnmappedColumns}
                title="Create target fields automatically for all unmapped columns in CSV"
                style={{
                  padding: '0.3rem 0.65rem',
                  borderRadius: 'var(--radius-xs)',
                  background: 'var(--panel-2)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-secondary)',
                  fontSize: '0.72rem',
                  fontWeight: 500,
                  cursor: 'pointer',
                }}
              >
                + Map All CSV Columns ({previewColumns.length})
              </button>
            )}
            <button
              type="button"
              onClick={handleAutoMapAll}
              style={{
                padding: '0.3rem 0.65rem',
                borderRadius: 'var(--radius-xs)',
                background: 'var(--panel-2)',
                border: '1px solid var(--border)',
                color: 'var(--accent)',
                fontSize: '0.72rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Auto-Map All
            </button>
            <button
              type="button"
              onClick={handleClearMapping}
              style={{
                padding: '0.3rem 0.65rem',
                borderRadius: 'var(--radius-xs)',
                background: 'var(--panel-2)',
                border: '1px solid var(--border)',
                color: 'var(--text-dim)',
                fontSize: '0.72rem',
                cursor: 'pointer',
              }}
            >
              Clear
            </button>
          </div>
        </div>

        {/* Datalist for autocomplete on detected CSV columns */}
        {previewColumns && previewColumns.length > 0 && (
          <datalist id="dataload-csv-columns-list">
            {previewColumns.map((col) => (
              <option key={col} value={col} />
            ))}
          </datalist>
        )}

        {/* Add Target Field Modal / Form */}
        {showAddTargetModal && (
          <div
            style={{
              padding: '0.75rem',
              marginTop: '0.75rem',
              borderRadius: 'var(--radius-xs)',
              background: 'var(--panel-2)',
              border: '1px solid var(--accent, #3b82f6)',
            }}
          >
            <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text)', marginBottom: '0.5rem' }}>
              Define New Target Field (Schema Destination)
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.2fr 1fr auto auto', gap: '0.5rem', alignItems: 'flex-end' }}>
              <div>
                <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)', display: 'block', marginBottom: '0.2rem' }}>
                  Target Field Name *
                </label>
                <input
                  type="text"
                  placeholder="e.g. AccountId or Custom_Field__c"
                  value={newTargetName}
                  onChange={(e) => setNewTargetName(e.target.value)}
                  style={{ ...inputStyle, width: '100%', fontSize: '0.76rem', padding: '0.35rem 0.5rem' }}
                  autoFocus
                />
              </div>
              <div>
                <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)', display: 'block', marginBottom: '0.2rem' }}>
                  Source CSV Column
                </label>
                <input
                  type="text"
                  placeholder="Column in CSV file"
                  list="dataload-csv-columns-list"
                  value={newTargetSourceCol}
                  onChange={(e) => setNewTargetSourceCol(e.target.value)}
                  style={{ ...inputStyle, width: '100%', fontSize: '0.76rem', padding: '0.35rem 0.5rem' }}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.7rem', color: 'var(--text-dim)', display: 'block', marginBottom: '0.2rem' }}>
                  Data Type
                </label>
                <select
                  value={newTargetType}
                  onChange={(e) => setNewTargetType(e.target.value)}
                  style={{ ...inputStyle, width: '100%', fontSize: '0.76rem', padding: '0.35rem 0.5rem' }}
                >
                  <option value="String (255)">String / Text</option>
                  <option value="Number / Integer">Number (Integer)</option>
                  <option value="Decimal / Currency">Decimal / Currency</option>
                  <option value="Email">Email Address</option>
                  <option value="Phone">Phone</option>
                  <option value="Boolean">Boolean (true/false)</option>
                  <option value="Date / DateTime">Date / DateTime</option>
                  <option value="Text (Long)">Long Text / JSON</option>
                </select>
              </div>
              <div style={{ paddingBottom: '0.35rem' }}>
                <label style={{ fontSize: '0.72rem', color: 'var(--text)', display: 'flex', alignItems: 'center', gap: '0.3rem', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={newTargetRequired}
                    onChange={(e) => setNewTargetRequired(e.target.checked)}
                  />
                  Required?
                </label>
              </div>
              <div style={{ display: 'flex', gap: '0.3rem', paddingBottom: '0.1rem' }}>
                <button
                  type="button"
                  onClick={handleAddTargetField}
                  disabled={!newTargetName.trim()}
                  style={{
                    padding: '0.35rem 0.75rem',
                    borderRadius: 'var(--radius-xs)',
                    background: newTargetName.trim() ? 'var(--accent)' : 'var(--panel-3)',
                    border: 'none',
                    color: '#fff',
                    fontSize: '0.74rem',
                    fontWeight: 600,
                    cursor: newTargetName.trim() ? 'pointer' : 'not-allowed',
                  }}
                >
                  Add Field
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowAddTargetModal(false)
                    setNewTargetName('')
                    setNewTargetSourceCol('')
                  }}
                  style={{
                    padding: '0.35rem 0.55rem',
                    borderRadius: 'var(--radius-xs)',
                    background: 'var(--panel-3)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-dim)',
                    fontSize: '0.74rem',
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        <div style={{ maxHeight: '320px', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', marginTop: '0.75rem' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem', textAlign: 'left' }}>
            <thead>
              <tr style={{ background: 'var(--panel-3)', color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}>
                <th style={{ padding: '0.55rem 0.75rem', fontWeight: 600 }}>Target Field</th>
                <th style={{ padding: '0.55rem 0.75rem', fontWeight: 600 }}>Type</th>
                <th style={{ padding: '0.55rem 0.75rem', fontWeight: 600 }}>Source Column</th>
                <th style={{ padding: '0.55rem 0.5rem', fontWeight: 600, width: '40px', textAlign: 'center' }}></th>
              </tr>
            </thead>
            <tbody>
              {allTargetFields.map((f) => {
                const currentSource = Object.keys(fieldMapping).find(k => fieldMapping[k] === f.field) || f.field
                return (
                  <tr key={f.field} style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--panel)' }}>
                    <td style={{ padding: '0.5rem 0.75rem', color: 'var(--text)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                        <span>
                          {f.label ? `${f.label} (${f.field})` : f.field}
                        </span>
                        {f.required && (
                          <span style={{ color: 'var(--red)', fontWeight: 'bold' }}>*</span>
                        )}
                        {f.isCustom && (
                          <span style={{
                            fontSize: '0.65rem',
                            padding: '0.1rem 0.35rem',
                            background: 'rgba(59, 130, 246, 0.15)',
                            color: 'var(--accent)',
                            borderRadius: '2px',
                            fontWeight: 600,
                          }}>
                            Custom
                          </span>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '0.5rem 0.75rem', color: 'var(--text-dim)', fontSize: '0.74rem' }}>{f.type}</td>
                    <td style={{ padding: '0.5rem 0.75rem' }}>
                      <input
                        type="text"
                        value={currentSource}
                        list="dataload-csv-columns-list"
                        placeholder="Column name in CSV"
                        onChange={(e) => handleMappingChange(f.field, e.target.value)}
                        style={{
                          width: '100%',
                          padding: '0.35rem 0.6rem',
                          background: 'var(--panel-2)',
                          border: '1px solid var(--border)',
                          borderRadius: 'var(--radius-xs)',
                          color: 'var(--text)',
                          fontSize: '0.78rem',
                          outline: 'none',
                        }}
                      />
                    </td>
                    <td style={{ padding: '0.5rem 0.5rem', textAlign: 'center' }}>
                      {f.isCustom && (
                        <button
                          type="button"
                          onClick={() => handleRemoveCustomTargetField(f.field)}
                          title="Remove custom target field"
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--red, #ef4444)',
                            cursor: 'pointer',
                            fontSize: '0.85rem',
                            padding: '0.2rem',
                            lineHeight: 1,
                          }}
                        >
                          ✕
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
