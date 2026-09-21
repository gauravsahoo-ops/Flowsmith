import { useState, useEffect, useMemo, useRef } from 'react'
import SalesforceAdditionalFields from './SalesforceAdditionalFields'
import SearchableSelect from './SearchableSelect'

const RESOURCE_OPTIONS = [
  { value: 'Account', label: 'Account', desc: 'Represents an individual account, which is an organization or person involved with your business (such as customers, competitors, and partners)' },
  { value: 'Attachment', label: 'Attachment', desc: 'Represents a file that a has uploaded and attached to a parent object' },
  { value: 'Case', label: 'Case', desc: 'Represents a case, which is a customer issue or problem' },
  { value: 'Contact', label: 'Contact', desc: 'Represents a contact, which is an individual associated with an account' },
  { value: 'CustomObject', label: 'Custom Object', desc: 'Represents a custom object' },
  { value: 'Document', label: 'Document', desc: 'Represents a document' },
  { value: 'Flow', label: 'Flow', desc: 'Represents an autolaunched flow' },
  { value: 'Lead', label: 'Lead', desc: 'Represents a prospect or potential' },
  { value: 'Opportunity', label: 'Opportunity', desc: 'Represents an opportunity, which is a sale or pending deal' },
  { value: 'Search', label: 'Search', desc: 'Search records' },
  { value: 'Task', label: 'Task', desc: 'Represents a business activity such as making a phone call or other to-do items. In the user interface, and records are collectively referred to as activities.' },
  { value: 'User', label: 'User', desc: 'Represents a person, which is one user in system' },
  { value: 'CustomApiCall', label: 'Custom API Call', desc: 'Make a custom API call to Salesforce' },
]

// Curated 9 + search/flow/list/bulk fallbacks — backend ids
const ALL_OPS = {
  add_note: { label: 'Add Note', hint: 'Add note to an account', backend: 'create' },
  create: { label: 'Create', hint: 'Create a record', backend: 'create' },
  upsert: { label: 'Create or Update', hint: 'Create a new record, or update the current one if it already exists (upsert)', backend: 'upsert' },
  delete: { label: 'Delete', hint: 'Delete a record', backend: 'delete' },
  get: { label: 'Get', hint: 'Get a record', backend: 'get' },
  query: { label: 'Get Many', hint: 'Get many records', backend: 'query' },
  get_many: { label: 'Get Many', hint: 'Get many records', backend: 'query' },
  describe: { label: 'Get Summary', hint: "Returns an overview of the object's metadata", backend: 'describe' },
  update: { label: 'Update', hint: 'Update a record', backend: 'update' },
  custom_api_call: { label: 'Custom API Call', hint: 'Make a custom API call', backend: 'custom_api_call' },
  flow_invoke: { label: 'Invoke Flow', hint: 'Invoke an autolaunched Flow', backend: 'flow_invoke' },
  search: { label: 'Search', hint: 'Search records', backend: 'search' },
  list: { label: 'List Objects', hint: 'List all objects', backend: 'list' },
  bulk: { label: 'Bulk', hint: 'Bulk load', backend: 'bulk' },
}

export default function SalesforceNodeEditor({ node, onParamsChange, mapping = [], onPreview }) {
  const params = node.parameters || {}
  const paramsRef = useRef(params)
  paramsRef.current = params
  const rawOperation = params.operation || ''
  const objectName = params.object_name || ''
  const resource = params.resource || (['Account','Contact','Lead','Opportunity','Case','Task'].includes(objectName) ? objectName : objectName ? 'CustomObject' : 'Account')

  const [matrix, setMatrix] = useState(null)
  const [showAdvanced, setShowAdvanced] = useState(false)

  useEffect(() => {
    const headers = { Authorization: `Bearer ${localStorage.getItem('mat_token')}` }
    fetch('/api/connectors/salesforce/resources', { headers }).then(r => r.json()).then(j => {
      if (j.data?.resources) setMatrix(j.data.resources)
    }).catch(() => {})
  }, [])

  // Valid backend ops for current resource (single source)
  const validBackendOps = useMemo(() => {
    if (matrix && matrix[resource]) return matrix[resource]
    if (matrix && matrix[resource]) return matrix[resource]
    // Fallback: curated 9 + search for Search resource, flow for Flow
    if (resource === 'Search') return ['search','query']
    if (resource === 'Flow') return ['flow_invoke','custom_api_call']
    if (resource === 'CustomApiCall') return ['custom_api_call']
    if (resource === 'User') return ['get','query','describe']
    if (resource === 'Attachment' || resource === 'Document') return ['create','delete','get','query','describe']
    return ['create','upsert','delete','get','query','describe','update','custom_api_call']
  }, [matrix, resource])

  // Map backend ids to curated display values for dropdown
  const operationOptions = useMemo(() => {
    const opts = []
    // For Account, inject add_note as alias to create
    const withAlias = resource === 'Account' && validBackendOps.includes('create') ? ['add_note', ...validBackendOps] : validBackendOps
    // Deduplicate backend create vs add_note (both map to create) — keep both for UI but ensure values distinct
    const seenBackend = new Set()
    for (const backendOp of withAlias) {
      // Map backend id to curated value
      let curatedVal = backendOp
      if (backendOp === 'query') curatedVal = 'get_many'
      else if (backendOp === 'describe') curatedVal = 'describe'
      else if (backendOp === 'create') curatedVal = 'create'
      // For add_note alias, keep distinct
      if (backendOp === 'add_note') curatedVal = 'add_note'
      const meta = ALL_OPS[curatedVal] || ALL_OPS[backendOp] || { label: backendOp, hint: '' }
      // Avoid duplicate backend create (Create vs Add Note both create) — keep both as distinct curated values
      if (backendOp !== 'add_note' && seenBackend.has(meta.backend)) {
        // For create already seen via add_note, skip second create? Keep both but they share backend — allow duplicate
        if (meta.backend === 'create' && opts.some(o => o.backend === 'create')) {
          // Keep Add Note separate, skip duplicate Create? Actually we want both Add Note and Create distinct, so allow
          if (curatedVal === 'create' && opts.some(o => o.value === 'add_note')) {
            // allow Create as second entry
          } else {
            continue
          }
        }
      }
      if (backendOp !== 'add_note') seenBackend.add(meta.backend)
      opts.push({ value: curatedVal, label: meta.label, hint: meta.hint, backend: meta.backend })
    }
    // Ensure unique values
    const uniq = []
    const seenVal = new Set()
    for (const o of opts) {
      if (!seenVal.has(o.value)) { uniq.push(o); seenVal.add(o.value) }
    }
    return uniq
  }, [validBackendOps, resource])

  // Normalize raw operation to curated value for display
  const operation = useMemo(() => {
    if (!rawOperation) return operationOptions[0]?.value || 'create'
    if (operationOptions.some(o => o.value === rawOperation)) return rawOperation
    // Map backend ids to curated
    if (rawOperation === 'query') return 'get_many'
    if (rawOperation === 'describe') return 'describe'
    if (rawOperation === 'custom_api_call') return 'custom_api_call'
    if (rawOperation === 'flow_invoke') return 'flow_invoke'
    if (rawOperation === 'search') return 'search'
    // Legacy execute → default to first valid
    if (rawOperation === 'execute' || rawOperation === '') return operationOptions[0]?.value || 'create'
    return rawOperation
  }, [rawOperation, operationOptions])


  const getTargetObject = (res, objName) => {
    if (res === 'CustomObject') return objName || 'Recruitment__c'
    if (res === 'CustomApiCall' || res === 'Flow' || res === 'Search') return objName || res
    return objName || res
  }

  const handleChange = (key, value) => {
    const next = { ...params, [key]: value }
    // Keep SOQL in sync when Custom Object name changes and operation is Get Many
    if (key === 'object_name' && (params.operation === 'get_many' || params.operation === 'query')) {
      const target = value || (params.resource === 'CustomObject' ? 'Recruitment__c' : params.resource || 'Account')
      if (next.soql && next.soql.includes('FROM')) {
        next.soql = next.soql.replace(/FROM\s+\S+/i, `FROM ${target}`)
      } else {
        const fields = target === 'Account' ? 'Id, Name, Type, LastModifiedDate' : 'Id, Name'
        next.soql = `SELECT ${fields} FROM ${target}`
      }
    }
    onParamsChange(next)
  }

  const handleOperationChange = (val) => {
    const next = { ...params, operation: val, resource }
    const targetObj = getTargetObject(resource, objectName)
    if (val === 'add_note') {
      next.object_name = 'Note'
      next.resource = 'Account'
      if (!next.record || typeof next.record !== 'object') next.record = { ParentId: '', Title: '', Body: '' }
      // Strip Id from record — Salesforce rejects create when Id is in the body
      if (next.record && typeof next.record === 'object') {
        const cleaned = { ...next.record }
        delete cleaned.Id
        delete cleaned.id
        next.record = cleaned
      }
    } else if (val === 'create') {
      if ((next.object_name || '').toLowerCase() === 'note') next.object_name = resource === 'CustomObject' ? '' : resource
      if (!next.record || typeof next.record !== 'object') next.record = { Name: '' }
      // Strip Id from record — Salesforce rejects create when Id is in the body
      if (next.record && typeof next.record === 'object') {
        const cleaned = { ...next.record }
        delete cleaned.Id
        delete cleaned.id
        next.record = cleaned
      }
    } else if (val === 'get_many' || val === 'query') {      const fields = targetObj === 'Account' ? 'Id, Name, Type, LastModifiedDate' : 'Id, Name'
      // Always regenerate SOQL for CustomObject to avoid Account fallback
      if (resource === 'CustomObject' || !next.soql || next.soql.includes('FROM Account') || next.soql.includes('LIMIT')) {
        next.soql = `SELECT ${fields} FROM ${targetObj}`
        next.max_pages = 100
      }
    } else if (val === 'custom_api_call') {
      next.resource = resource
      if (!next.custom_api_url) next.custom_api_url = '/services/data/v63.0/sobjects/Account'
      if (!next.custom_api_method) next.custom_api_method = 'GET'
    } else if (val === 'flow_invoke') {
      next.resource = 'Flow'
      if (!next.flow_api_name) next.flow_api_name = ''
    } else if (val === 'describe') {
      if (!next.object_name) next.object_name = resource === 'CustomObject' ? '' : resource
    } else if (val === 'search') {
      next.resource = 'Search'
      if (!next.search_field) next.search_field = 'Email'
    }
    onParamsChange(next)
  }

  const handleResourceChange = (val) => {
    let nextOp = params.operation
    const newValid = matrix?.[val] || (val === 'Search' ? ['search','query'] : val === 'Flow' ? ['flow_invoke'] : ['create','upsert','delete','get','query','describe','update'])
    const curatedForNew = newValid.includes('query') ? 'get_many' : newValid[0]
    const isValid = newValid.includes(ALL_OPS[nextOp]?.backend || nextOp) || newValid.includes(nextOp) || (val === 'Account' && nextOp === 'add_note')
    if (!isValid) nextOp = curatedForNew || newValid[0] || 'create'
    if (val === 'CustomObject') {
      const target = objectName || 'Recruitment__c'
      const fields = target === 'Account' ? 'Id, Name, Type, LastModifiedDate' : 'Id, Name'
      const soql = `SELECT ${fields} FROM ${target}`
      onParamsChange({ ...params, resource: val, object_name: objectName || '', operation: nextOp, soql })
    } else if (val === 'CustomApiCall') {
      onParamsChange({ ...params, resource: val, object_name: '', operation: 'custom_api_call', custom_api_url: params.custom_api_url || '/services/data/v63.0/sobjects/Account' })
    } else if (val === 'Search') {
      onParamsChange({ ...params, resource: val, object_name: '', operation: 'search' })
    } else if (val === 'Flow') {
      onParamsChange({ ...params, resource: val, object_name: val, operation: 'flow_invoke' })
    } else {
      const target = val
      const fields = target === 'Account' ? 'Id, Name, Type, LastModifiedDate' : 'Id, Name'
      const soql = (nextOp === 'get_many' || nextOp === 'query') ? `SELECT ${fields} FROM ${target}` : params.soql
      onParamsChange({ ...params, resource: val, object_name: val, operation: nextOp, ...(soql ? { soql } : {}) })
    }
  }

  // Auto-fix stale SOQL that still points to Account when Custom Object is Recruitment__c (critical bug)
  const currentSoql = params.soql
  useEffect(() => {
    if ((operation === 'get_many' || operation === 'query') && resource === 'CustomObject' && objectName && currentSoql) {
      const expectedFrom = `FROM ${objectName}`
      if (!currentSoql.includes(expectedFrom)) {
        const fields = objectName === 'Account' ? 'Id, Name, Type, LastModifiedDate' : 'Id, Name'
        const newSoql = `SELECT ${fields} FROM ${objectName}`
        // Only update if SOQL is generic Account fallback
        if (currentSoql.includes('FROM Account') || currentSoql.includes('FROM My_Object__c')) {
          onParamsChange({ ...paramsRef.current, soql: newSoql })
        }
      }
    }
  }, [resource, objectName, operation, currentSoql, onParamsChange])


  return (
    <div className="sf-editor">
      <div className="sf-field">
        <label>
          <span>Resource <span className="required-badge">*</span></span>
          <SearchableSelect value={resource} onChange={handleResourceChange} options={RESOURCE_OPTIONS} placeholder="Select resource…" />
          <span className="hint">{RESOURCE_OPTIONS.find(r => r.value === resource)?.desc || ''}</span>
        </label>
      </div>

      <div className="sf-field">
        <label>
          <span>Object {resource !== 'CustomApiCall' && resource !== 'Flow' && <span className="required-badge">*</span>}</span>
          {resource === 'CustomObject' ? (
            <input type="text" value={objectName} onChange={e => handleChange('object_name', e.target.value)} placeholder="My_Object__c" style={{ flex: 1 }} />
          ) : resource === 'CustomApiCall' ? (
            <input type="text" value={params.custom_api_url || ''} onChange={e => handleChange('custom_api_url', e.target.value)} placeholder="/services/data/v63.0/sobjects/Account" style={{ flex: 1 }} />
          ) : resource === 'Flow' ? (
            <input type="text" value={params.flow_api_name || ''} onChange={e => handleChange('flow_api_name', e.target.value)} placeholder="My_Flow" style={{ flex: 1 }} />
          ) : resource === 'Search' ? (
            <input type="text" value={objectName} onChange={e => handleChange('object_name', e.target.value)} placeholder="Leave empty to search all objects" style={{ flex: 1 }} />
          ) : (
            <div style={{ display: 'flex', gap: 6 }}>
              <input type="text" value={objectName} onChange={e => handleChange('object_name', e.target.value)} placeholder={resource} style={{ flex: 1 }} />
            </div>
          )}
          <span className="hint">
            {resource === 'CustomObject' ? 'Custom object API name, e.g. My_Object__c' : resource === 'CustomApiCall' ? 'Custom Salesforce API endpoint' : resource === 'Flow' ? 'Flow API name' : `API name for ${resource}, e.g. ${resource}`}
          </span>
        </label>
      </div>

      <div className="sf-field">
        <label>
          <span>Operation <span className="required-badge">*</span></span>
          <SearchableSelect
            value={operation}
            onChange={handleOperationChange}
            options={
              !operationOptions.some(o => o.value === operation) && operation
                ? [...operationOptions, { value: operation, label: `${operation} (legacy)` }]
                : operationOptions
            }
            placeholder="Select operation…"
          />
          <span className="hint">{operationOptions.find(o => o.value === operation)?.hint || ALL_OPS[operation]?.hint || ''}</span>
        </label>
      </div>

      <div className="sf-primary">
        {operation === 'add_note' && (
          <>
            <label><span>Parent ID (Account) <span className="required-badge">*</span></span><input type="text" value={params.record?.ParentId || ''} onChange={e => handleChange('record', { ...(params.record || {}), ParentId: e.target.value })} placeholder="001..." /></label>
            <label><span>Title <span className="required-badge">*</span></span><input type="text" value={params.record?.Title || ''} onChange={e => handleChange('record', { ...(params.record || {}), Title: e.target.value })} placeholder="Note title" /></label>
            <label><span>Body</span><textarea value={params.record?.Body || ''} onChange={e => handleChange('record', { ...(params.record || {}), Body: e.target.value })} placeholder="Note content" rows={2} /></label>
          </>
        )}
        {['get', 'delete', 'update'].includes(operation) && (
          <label><span>Record ID <span className="required-badge">*</span></span><input type="text" value={params.record_id || ''} onChange={e => handleChange('record_id', e.target.value)} placeholder="a0B..." /></label>
        )}
        {operation === 'upsert' && (
          <>
            <label><span>External ID field <span className="required-badge">*</span></span><input type="text" value={params.external_id_field || ''} onChange={e => handleChange('external_id_field', e.target.value)} placeholder="Legacy_Id__c" /></label>
            <label><span>External ID value <span className="required-badge">*</span></span><input type="text" value={params.external_id || ''} onChange={e => handleChange('external_id', e.target.value)} placeholder="12345" /></label>
          </>
        )}
        {(operation === 'get_many' || operation === 'query') && (
          <label><span>SOQL query <span className="required-badge">*</span></span><textarea value={params.soql || ''} onChange={e => handleChange('soql', e.target.value)} placeholder={resource === 'Account' ? 'SELECT Id, Name, Type, LastModifiedDate FROM Account' : `SELECT Id, Name FROM ${resource === 'CustomObject' ? 'My_Object__c' : resource}`} rows={3} /></label>
        )}

        {operation === 'search' && (
          <>
            <label><span>Search field <span className="required-badge">*</span></span><input type="text" value={params.search_field || ''} onChange={e => handleChange('search_field', e.target.value)} placeholder="Email" /></label>
            <label><span>Search value <span className="required-badge">*</span></span><input type="text" value={params.search_value || ''} onChange={e => handleChange('search_value', e.target.value)} placeholder="{{ $json.email }}" /></label>
          </>
        )}
        {operation === 'custom_api_call' && (
          <>
            <label><span>Method <span className="required-badge">*</span></span>
              <select value={params.custom_api_method || 'GET'} onChange={e => handleChange('custom_api_method', e.target.value)}>
                <option value="GET">GET</option><option value="POST">POST</option><option value="PUT">PUT</option><option value="PATCH">PATCH</option><option value="DELETE">DELETE</option>
              </select>
            </label>
            <label><span>Path <span className="required-badge">*</span></span><input type="text" value={params.custom_api_url || ''} onChange={e => handleChange('custom_api_url', e.target.value)} placeholder="/services/data/v63.0/sobjects/Account" /></label>
            <label><span>Body (JSON)</span><textarea value={typeof params.custom_api_body === 'string' ? params.custom_api_body : JSON.stringify(params.custom_api_body || {}, null, 2)} onChange={e => { try { handleChange('custom_api_body', JSON.parse(e.target.value)) } catch { handleChange('custom_api_body', e.target.value) } }} placeholder='{"Name":"Acme"}' rows={3} /></label>
          </>
        )}
        {operation === 'flow_invoke' && (
          <>
            <label><span>Flow API Name <span className="required-badge">*</span></span><input type="text" value={params.flow_api_name || ''} onChange={e => handleChange('flow_api_name', e.target.value)} placeholder="My_Flow" /></label>
            <label><span>Flow Inputs (JSON)</span><textarea value={typeof params.flow_inputs === 'string' ? params.flow_inputs : JSON.stringify(params.flow_inputs || {}, null, 2)} onChange={e => { try { handleChange('flow_inputs', JSON.parse(e.target.value)) } catch { handleChange('flow_inputs', e.target.value) } }} placeholder='{"myVar":"value"}' rows={3} /></label>
          </>
        )}
        {operation === 'bulk' && (
          <>
            <label><span>Bulk operation <span className="required-badge">*</span></span>
              <select value={params.bulk_operation || 'insert'} onChange={e => handleChange('bulk_operation', e.target.value)}>
                <option value="insert">Insert</option><option value="update">Update</option><option value="upsert">Upsert</option><option value="delete">Delete</option>
              </select>
            </label>
            <label><span>Records</span><textarea value={typeof params.records === 'string' ? params.records : JSON.stringify(params.records || [], null, 2)} onChange={e => { try { handleChange('records', JSON.parse(e.target.value)) } catch { handleChange('records', e.target.value) } }} placeholder='[{"Name": "Acme"}]' rows={4} /></label>
          </>
        )}
      </div>

      {['create', 'add_note', 'update', 'upsert'].includes(operation) && (
        <SalesforceAdditionalFields node={node} onParamsChange={onParamsChange} mapping={mapping} onPreview={onPreview} />
      )}

      <div className="sf-advanced">
        <button type="button" className="sf-advanced-toggle" onClick={() => setShowAdvanced(v => !v)}>
          <span className="sf-caret">{showAdvanced ? '▾' : '▸'}</span>
          Advanced Options
        </button>
        {showAdvanced && (
          <div className="sf-advanced-body">
            <label><span>Timeout (seconds)</span><input type="number" min={1} value={params.timeout_seconds ?? 30} onChange={e => handleChange('timeout_seconds', Number(e.target.value))} /></label>
            {(operation === 'get_many' || operation === 'query') && (
              <label><span>Max pages (100 = unlimited)</span><input type="number" min={1} max={100} value={params.max_pages ?? 100} onChange={e => handleChange('max_pages', Number(e.target.value))} /></label>
            )}
            {['get', 'update', 'upsert', 'delete', 'search', 'add_note'].includes(operation) && (
              <label><span>Record fields (JSON)</span><textarea value={typeof params.record === 'string' ? params.record : JSON.stringify(params.record || {}, null, 2)} onChange={e => { try { handleChange('record', JSON.parse(e.target.value)) } catch { handleChange('record', e.target.value) } }} placeholder='{"Custom_Field__c": "value"}' rows={2} /><span className="hint">Rarely needed — use Additional Fields above.</span></label>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
