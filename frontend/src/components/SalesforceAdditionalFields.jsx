import { useEffect, useMemo, useState, useRef } from 'react'
import { api } from '../api'
import MappingInput from './MappingField'

export default function SalesforceAdditionalFields({ node, onParamsChange, mapping = [], onPreview }) {
  const params = node.parameters || {}
  const objectName = params.object_name || ''
  const record = params.record || {}
  const operation = params.operation || 'query'

  const [fields, setFields] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState({})

  const showAdditional = ['create', 'update', 'upsert'].includes(operation)

  useEffect(() => {
    if (!objectName) { setFields([]); return }
    let alive = true
    setLoading(true)
    setError('')
    api.salesforceObjectSchema(objectName)
      .then(data => { if (alive) setFields(data.fields || []) })
      .catch(err => { if (alive) { setError(err.message || 'Cannot load fields'); setFields([]) } })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [objectName])

  const fallbackFields = useMemo(() => {
    if (fields.length > 0) return []
    if (objectName === 'Account') {
      return [
        { name: 'Name', label: 'Account Name', type: 'string', required: true },
        { name: 'Phone', label: 'Phone', type: 'phone' },
        { name: 'Industry', label: 'Industry', type: 'picklist', picklist_values: ['Agriculture','Apparel','Banking','Biotechnology'] },
        { name: 'Website', label: 'Website', type: 'url' },
      ]
    }
    if (objectName === 'Recruitment__c') {
      return [
        { name: 'Name', label: 'Name', type: 'string', required: true },
        { name: 'Email__c', label: 'Email Address', type: 'string' },
        { name: 'CompanyName__c', label: 'Company Name', type: 'string' },
        { name: 'NoticePeriod__c', label: 'Notice Period', type: 'string' },
        { name: 'CommuteFromLocation__c', label: 'Commute from Location', type: 'string' },
        { name: 'LineManager__c', label: 'Line Manager', type: 'string' },
        { name: 'ReasonForLeaving__c', label: 'Reason for Leaving', type: 'string' },
        { name: 'AnnualSalary__c', label: 'Annual Salary', type: 'string' },
        { name: 'BonusBenefits__c', label: 'Bonus / Benefits', type: 'string' },
        { name: 'ExternalInterviews__c', label: 'External Interviews', type: 'string' },
        { name: 'FirstName__c', label: 'First Name', type: 'string' },
        { name: 'LastName__c', label: 'Last Name', type: 'string' },
        { name: 'KeyNotes__c', label: 'Key Notes', type: 'textarea' },
        { name: 'Participants__c', label: 'Participants', type: 'string' },
        { name: 'Responsibilities__c', label: 'Responsibilities', type: 'textarea' },
        { name: 'Skills__c', label: 'Skills', type: 'textarea' },
        { name: 'OrganizerEmail__c', label: 'Organizer Email', type: 'string' },
        { name: 'OrganizerName__c', label: 'Organizer Name', type: 'string' },
        { name: 'OwnerId', label: 'Owner ID', type: 'reference', reference_to: ['User'] },
        { name: 'CreatedById', label: 'Created By ID', type: 'reference', reference_to: ['User'] },
        { name: 'CreatedDate', label: 'Created Date', type: 'datetime' },
        { name: 'LastModifiedById', label: 'Last Modified By ID', type: 'reference', reference_to: ['User'] },
        { name: 'LastModifiedDate', label: 'Last Modified Date', type: 'datetime' },
        { name: 'LastActivityDate', label: 'Last Activity Date', type: 'date' },
        { name: 'LastReferencedDate', label: 'Last Referenced Date', type: 'datetime' },
        { name: 'LastViewedDate', label: 'Last Viewed Date', type: 'datetime' },
        { name: 'IsDeleted', label: 'Deleted', type: 'boolean' },
        { name: 'SystemModstamp', label: 'System Modstamp', type: 'datetime' },
      ]
    }
    return []
  }, [fields, objectName])

  const effectiveFields = fields.length > 0 ? fields : fallbackFields

  const addedFieldNames = Object.keys(record)

  const isFieldExpanded = (fieldName) => {
    return !!expanded[fieldName]
  }

  const toggleField = (fieldName) => {
    setExpanded(prev => ({
      ...prev,
      [fieldName]: !prev[fieldName]
    }))
  }

  const collapseAll = () => {
    setExpanded({})
  }

  const expandAll = () => {
    const next = {}
    addedFieldNames.forEach(name => { next[name] = true })
    setExpanded(next)
  }

  const allCollapsed = addedFieldNames.length > 0 && addedFieldNames.every(name => !expanded[name])

  if (!showAdditional) return null

  const handleAddEmpty = () => {
    const used = new Set(addedFieldNames)
    const next = effectiveFields.find(f => !used.has(f.name))
    const name = next ? next.name : `custom_field_${Date.now()}`
    onParamsChange({ ...params, record: { ...record, [name]: '' } })
    setExpanded(prev => ({ ...prev, [name]: true }))
  }

  const handleFieldNameChange = (oldName, newName) => {
    if (!newName || oldName === newName) return
    const next = { ...record }
    const value = next[oldName]
    delete next[oldName]
    next[newName] = value ?? ''
    onParamsChange({ ...params, record: next })
    setExpanded(prev => {
      const copy = { ...prev }
      const wasOpen = copy[oldName]
      delete copy[oldName]
      copy[newName] = wasOpen ?? true
      return copy
    })
  }

  const handleFieldValueChange = (fieldName, value) => {
    onParamsChange({ ...params, record: { ...record, [fieldName]: value } })
  }

  const handleRemove = (fieldName, e) => {
    if (e) e.stopPropagation()
    const next = { ...record }
    delete next[fieldName]
    onParamsChange({ ...params, record: next })
    setExpanded(prev => {
      const copy = { ...prev }
      delete copy[fieldName]
      return copy
    })
  }

  return (
    <div className="sf-additional">
      <div className="sf-additional-head">
        <h4>
          Fields
          {addedFieldNames.length > 0 && (
            <span className="sf-fields-count">({addedFieldNames.length})</span>
          )}
        </h4>
        <div className="sf-additional-line" />
        {addedFieldNames.length > 0 && (
          <div className="sf-head-actions">
            <button
              type="button"
              className="ghost small"
              onClick={allCollapsed ? expandAll : collapseAll}
              title={allCollapsed ? "Expand all fields" : "Collapse all fields"}
              style={{ fontSize: 11, padding: '2px 8px' }}
            >
              {allCollapsed ? "Expand all" : "Collapse all"}
            </button>
          </div>
        )}
      </div>

      {loading && <p className="hint">Loading fields for {objectName}…</p>}
      {error && <p className="hint">Field discovery unavailable ({error})</p>}

      {addedFieldNames.map((fieldName, index) => {
        const meta = effectiveFields.find(f => f.name === fieldName)
        const value = record[fieldName]
        const usedNames = new Set(addedFieldNames.filter(n => n !== fieldName))
        const fieldOptions = effectiveFields.filter(f => !usedNames.has(f.name))
        const isOpen = isFieldExpanded(fieldName)
        const fieldTitle = `Custom Field ${index + 1}`
        const fieldSubtitle = meta?.label || (fieldName && fieldName !== fieldTitle ? fieldName : '')

        return (
          <div key={fieldName} className={`sf-custom-field ${isOpen ? 'is-open' : 'is-collapsed'}`}>
            <div
              className="sf-custom-field-header"
              onClick={() => toggleField(fieldName)}
              title={isOpen ? "Click to collapse" : "Click to expand"}
            >
              <span className={`sf-custom-field-arrow ${isOpen ? 'open' : ''}`}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </span>
              <span className="sf-custom-field-title">{fieldTitle}</span>
              {fieldSubtitle && (
                <span className="sf-custom-field-meta" title={fieldSubtitle}>
                  {fieldSubtitle}
                </span>
              )}
              <button
                type="button"
                className="ghost small sf-field-remove"
                onClick={(e) => handleRemove(fieldName, e)}
                title="Remove field"
              >
                ✕
              </button>
            </div>

            {isOpen && (
              <div className="sf-custom-field-body">
                <label className="sf-custom-field-label">
                  <span>Field Name or ID</span>
                  <select
                    value={fieldName}
                    onChange={e => handleFieldNameChange(fieldName, e.target.value)}
                  >
                    {fieldName && !fieldOptions.some(f => f.name === fieldName) && (
                      <option value={fieldName}>{meta?.label || fieldName} ({fieldName})</option>
                    )}
                    {fieldOptions.map(f => (
                      <option key={f.name} value={f.name}>
                        {f.label && f.label !== f.name ? `${f.label} (${f.name})` : f.name}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="sf-custom-field-label">
                  <span>Value</span>
                  <MappingInput
                    value={value ?? ''}
                    onChange={(v) => handleFieldValueChange(fieldName, v)}
                    mapping={mapping}
                    onPreview={onPreview}
                    schema={{ title: meta?.label || fieldName }}
                    path={`record.${fieldName}`}
                  />
                </label>
              </div>
            )}
          </div>
        )
      })}

      <button className="ghost" onClick={handleAddEmpty} style={{ marginTop: 8 }}>
        + Add Field
      </button>
    </div>
  )
}
