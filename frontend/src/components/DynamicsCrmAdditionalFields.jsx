import { useMemo, useState } from 'react'
import MappingInput from './MappingField'

// Curated standard attribute catalogs for Microsoft Dataverse CRM entities
const ENTITY_FALLBACK_FIELDS = {
  contacts: [
    { name: 'firstname', label: 'First Name', type: 'string' },
    { name: 'lastname', label: 'Last Name', type: 'string', required: true },
    { name: 'emailaddress1', label: 'Primary Email', type: 'email' },
    { name: 'telephone1', label: 'Business Phone', type: 'phone' },
    { name: 'mobilephone', label: 'Mobile Phone', type: 'phone' },
    { name: 'jobtitle', label: 'Job Title', type: 'string' },
    { name: 'parentcustomerid@odata.bind', label: 'Parent Account (OData Bind)', type: 'lookup' },
    { name: 'address1_line1', label: 'Street Address', type: 'string' },
    { name: 'address1_city', label: 'City', type: 'string' },
    { name: 'address1_stateorprovince', label: 'State / Province', type: 'string' },
    { name: 'address1_postalcode', label: 'ZIP / Postal Code', type: 'string' },
    { name: 'address1_country', label: 'Country', type: 'string' },
    { name: 'description', label: 'Description / Notes', type: 'textarea' },
    { name: 'donotemail', label: 'Do Not Allow Bulk Emails', type: 'boolean' },
  ],
  accounts: [
    { name: 'name', label: 'Account Name', type: 'string', required: true },
    { name: 'telephone1', label: 'Main Phone', type: 'phone' },
    { name: 'websiteurl', label: 'Website URL', type: 'url' },
    { name: 'emailaddress1', label: 'Email', type: 'email' },
    { name: 'revenue', label: 'Annual Revenue', type: 'currency' },
    { name: 'numberofemployees', label: 'Number of Employees', type: 'integer' },
    { name: 'industrycode', label: 'Industry Code', type: 'picklist' },
    { name: 'address1_line1', label: 'Street Address', type: 'string' },
    { name: 'address1_city', label: 'City', type: 'string' },
    { name: 'address1_stateorprovince', label: 'State / Province', type: 'string' },
    { name: 'address1_postalcode', label: 'Postal Code', type: 'string' },
    { name: 'address1_country', label: 'Country', type: 'string' },
    { name: 'description', label: 'Description', type: 'textarea' },
  ],
  leads: [
    { name: 'subject', label: 'Topic / Subject', type: 'string', required: true },
    { name: 'firstname', label: 'First Name', type: 'string' },
    { name: 'lastname', label: 'Last Name', type: 'string', required: true },
    { name: 'companyname', label: 'Company Name', type: 'string' },
    { name: 'emailaddress1', label: 'Business Email', type: 'email' },
    { name: 'telephone1', label: 'Business Phone', type: 'phone' },
    { name: 'mobilephone', label: 'Mobile Phone', type: 'phone' },
    { name: 'jobtitle', label: 'Job Title', type: 'string' },
    { name: 'estimatedamount', label: 'Est. Budget Amount', type: 'currency' },
    { name: 'description', label: 'Lead Notes', type: 'textarea' },
  ],
  opportunities: [
    { name: 'name', label: 'Opportunity Topic', type: 'string', required: true },
    { name: 'estimatedvalue', label: 'Est. Revenue', type: 'currency' },
    { name: 'estimatedclosedate', label: 'Est. Close Date', type: 'date' },
    { name: 'closeprobability', label: 'Close Probability (%)', type: 'integer' },
    { name: 'parentcontactid@odata.bind', label: 'Contact (OData Bind)', type: 'lookup' },
    { name: 'parentaccountid@odata.bind', label: 'Account (OData Bind)', type: 'lookup' },
    { name: 'description', label: 'Opportunity Description', type: 'textarea' },
  ],
  incidents: [
    { name: 'title', label: 'Case Title', type: 'string', required: true },
    { name: 'customerid_contact@odata.bind', label: 'Customer Contact (OData Bind)', type: 'lookup' },
    { name: 'customerid_account@odata.bind', label: 'Customer Account (OData Bind)', type: 'lookup' },
    { name: 'prioritycode', label: 'Priority (1=High, 2=Normal, 3=Low)', type: 'integer' },
    { name: 'caseorigincode', label: 'Case Origin (1=Phone, 2=Email, 3=Web)', type: 'integer' },
    { name: 'description', label: 'Case Problem Description', type: 'textarea' },
  ],
  tasks: [
    { name: 'subject', label: 'Task Subject', type: 'string', required: true },
    { name: 'scheduledend', label: 'Due Date', type: 'datetime' },
    { name: 'prioritycode', label: 'Priority (1=High, 2=Normal, 3=Low)', type: 'integer' },
    { name: 'description', label: 'Task Instructions', type: 'textarea' },
  ],
  systemusers: [
    { name: 'fullname', label: 'Full Name', type: 'string' },
    { name: 'domainname', label: 'Domain Name', type: 'string' },
    { name: 'internalemailaddress', label: 'Primary Email', type: 'email' },
    { name: 'title', label: 'Job Title', type: 'string' },
  ],
}

export default function DynamicsCrmAdditionalFields({ node, onParamsChange, mapping = [], onPreview }) {
  const params = node.parameters || {}
  const entity = (params.entity || 'contacts').toLowerCase().trim()
  const data = (params.data && typeof params.data === 'object' && !Array.isArray(params.data))
    ? params.data
    : (params.record && typeof params.record === 'object' && !Array.isArray(params.record))
      ? params.record
      : {}
  const operation = params.operation || 'create'

  const [expanded, setExpanded] = useState({})

  const showAdditional = ['create', 'update', 'upsert'].includes(operation)

  const effectiveFields = useMemo(() => {
    return ENTITY_FALLBACK_FIELDS[entity] || [
      { name: 'name', label: 'Name', type: 'string' },
      { name: 'description', label: 'Description', type: 'textarea' },
      { name: 'emailaddress1', label: 'Email', type: 'email' },
      { name: 'telephone1', label: 'Phone', type: 'phone' },
    ]
  }, [entity])

  const addedFieldNames = Object.keys(data)

  const isFieldExpanded = (fieldName) => !!expanded[fieldName]

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
    const nextField = effectiveFields.find(f => !used.has(f.name))
    const name = nextField ? nextField.name : `custom_field_${Date.now()}`
    const nextData = { ...data, [name]: '' }
    onParamsChange({ ...params, data: nextData, record: nextData })
    setExpanded(prev => ({ ...prev, [name]: true }))
  }

  const handleFieldNameChange = (oldName, newName) => {
    if (!newName || oldName === newName) return
    const nextData = { ...data }
    const value = nextData[oldName]
    delete nextData[oldName]
    nextData[newName] = value ?? ''
    onParamsChange({ ...params, data: nextData, record: nextData })
    setExpanded(prev => {
      const copy = { ...prev }
      const wasOpen = copy[oldName]
      delete copy[oldName]
      copy[newName] = wasOpen ?? true
      return copy
    })
  }

  const handleFieldValueChange = (fieldName, value) => {
    const nextData = { ...data, [fieldName]: value }
    onParamsChange({ ...params, data: nextData, record: nextData })
  }

  const handleRemove = (fieldName, e) => {
    if (e) e.stopPropagation()
    const nextData = { ...data }
    delete nextData[fieldName]
    onParamsChange({ ...params, data: nextData, record: nextData })
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
          Record Fields
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

      {addedFieldNames.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '16px 8px', color: 'var(--muted)', fontSize: 12 }}>
          <p style={{ margin: '0 0 8px 0' }}>No columns added yet.</p>
          <button type="button" className="ghost" onClick={handleAddEmpty} style={{ fontSize: 12 }}>
            + Add Field
          </button>
        </div>
      ) : (
        <>
          {addedFieldNames.map((fieldName, index) => {
            const meta = effectiveFields.find(f => f.name === fieldName)
            const value = data[fieldName]
            const usedNames = new Set(addedFieldNames.filter(n => n !== fieldName))
            const fieldOptions = effectiveFields.filter(f => !usedNames.has(f.name))
            const isOpen = isFieldExpanded(fieldName)
            const fieldTitle = `Field ${index + 1}`
            const fieldSubtitle = meta?.label || fieldName

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
                   style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                </div>

                {isOpen && (
                  <div className="sf-custom-field-body">
                    <label className="sf-custom-field-label">
                      <span>Column / Field Name</span>
                      <select
                        value={fieldName}
                        onChange={e => handleFieldNameChange(fieldName, e.target.value)}
                      >
                        {fieldName && !effectiveFields.some(f => f.name === fieldName) && (
                          <option value={fieldName}>{fieldName} (Custom)</option>
                        )}
                        {fieldOptions.map(f => (
                          <option key={f.name} value={f.name}>
                            {f.label ? `${f.label} (${f.name})` : f.name}
                          </option>
                        ))}
                        <option value={`custom_attr_${Date.now()}`}>+ Custom Column Name…</option>
                      </select>
                    </label>

                    <label className="sf-custom-field-label">
                      <span>Value (or Expression)</span>
                      <MappingInput
                        value={typeof value === 'object' ? JSON.stringify(value) : (value ?? '')}
                        onChange={(v) => handleFieldValueChange(fieldName, v)}
                        mapping={mapping}
                        onPreview={onPreview}
                        schema={{ title: meta?.label || fieldName }}
                        path={`data.${fieldName}`}
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
        </>
      )}
    </div>
  )
}
