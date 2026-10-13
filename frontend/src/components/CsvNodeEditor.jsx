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

  const [filePath, setFilePath] = useState(params.file_path || '')
  const [csvContent, setCsvContent] = useState(params.csv_content || '')
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
  const [fileName, setFileName] = useState('')

  const updateParam = (key, value) => {
    onParamsChange({
      ...params,
      [key]: value,
    })
  }

  const handleMappingChange = (targetField, sourceCol) => {
    const nextMapping = { ...fieldMapping, [sourceCol]: targetField }
    setFieldMapping(nextMapping)
    updateParam('field_mapping', nextMapping)
  }

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFileName(file.name)
    const reader = new FileReader()
    reader.onload = (event) => {
      const content = event.target?.result
      if (typeof content === 'string') {
        setCsvContent(content)
        updateParam('csv_content', content)
      }
    }
    reader.readAsText(file)
  }

  return (
    <div className="csv-node-editor" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', padding: '0.5rem' }}>
      {/* File Source Section */}
      <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2e3440)' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', fontSize: '0.95rem', fontWeight: 600, color: '#eceff4' }}>
          CSV Input Source
        </h4>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
              Upload CSV File
            </label>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={handleFileUpload}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '4px',
                background: '#242933',
                color: '#e5e9f0',
                border: '1px solid #3b4252',
                fontSize: '0.85rem'
              }}
            />
            {fileName && (
              <span style={{ fontSize: '0.75rem', color: '#a3be8c', marginTop: '0.25rem', display: 'block' }}>
                Loaded file: {fileName}
              </span>
            )}
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: '#88c0d0', marginBottom: '0.25rem' }}>
              Or File System Path
            </label>
            <input
              type="text"
              value={filePath}
              placeholder="e.g. flowsmith_salesforce_contact_10000.csv or /data/contacts.csv"
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
                fontSize: '0.85rem'
              }}
            />
          </div>
        </div>
      </div>

      {/* Parser & Dialect Configuration */}
      <div className="form-section" style={{ background: 'var(--color-bg-secondary, #1e222d)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--color-border, #2e3440)' }}>
        <h4 style={{ margin: '0 0 0.75rem 0', fontSize: '0.95rem', fontWeight: 600, color: '#eceff4' }}>
          Parser & Dialect Settings
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
                fontSize: '0.85rem'
              }}
            >
              <option value="">Auto-Detect (, \t ; |)</option>
              <option value=",">Comma (,)</option>
              <option value="&#9;">Tab (\t)</option>
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
                fontSize: '0.85rem'
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
          <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600, color: '#eceff4' }}>
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
                <th style={{ padding: '0.5rem' }}>CSV Source Column</th>
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
        <h4 style={{ margin: '0 0 0.75rem 0', fontSize: '0.95rem', fontWeight: 600, color: '#eceff4' }}>
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
                fontSize: '0.85rem'
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
                fontSize: '0.85rem'
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
