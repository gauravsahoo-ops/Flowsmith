import { useState, useMemo } from 'react'
import SearchableSelect from './SearchableSelect'
import DynamicsCrmAdditionalFields from './DynamicsCrmAdditionalFields'

const RESOURCE_OPTIONS = [
  { value: 'Contact', entity: 'contacts', label: 'Contact', desc: 'Represents an individual person such as a customer, partner, or contact' },
  { value: 'Account', entity: 'accounts', label: 'Account', desc: 'Represents a company or business customer account' },
  { value: 'Lead', entity: 'leads', label: 'Lead', desc: 'Represents a prospective customer or sales lead' },
  { value: 'Opportunity', entity: 'opportunities', label: 'Opportunity', desc: 'Represents a potential revenue-generating sale or deal' },
  { value: 'Case', entity: 'incidents', label: 'Case / Incident', desc: 'Represents a customer support case or incident' },
  { value: 'Task', entity: 'tasks', label: 'Task', desc: 'Represents a scheduled to-do item or CRM activity' },
  { value: 'SystemUser', entity: 'systemusers', label: 'System User', desc: 'Represents an internal Dynamics 365 / Dataverse system user' },
  { value: 'CustomTable', entity: '', label: 'Custom Table', desc: 'Specify any custom Dataverse table logical name (e.g. cr841_project)' },
  { value: 'Action', entity: '', label: 'Unbound Action', desc: 'Execute a Dataverse unbound custom action or function' },
]

const ALL_OPS = {
  create: { label: 'Create', hint: 'Create a new record in Dataverse' },
  update: { label: 'Update', hint: 'Update an existing record by GUID' },
  upsert: { label: 'Create or Update (Upsert)', hint: 'Create a new record or update an existing one using an alternate key' },
  get: { label: 'Get', hint: 'Retrieve a single record by primary key GUID' },
  query: { label: 'Get Many (Query)', hint: 'Query records using OData filters, select, orderby, or FetchXML' },
  search: { label: 'Search', hint: 'Search records matching keyword across entity fields' },
  delete: { label: 'Delete', hint: 'Delete a record by primary key GUID' },
  execute_action: { label: 'Execute Action', hint: 'Execute an unbound custom action or function' },
}

export default function DynamicsCrmNodeEditor({ node, onParamsChange, mapping = [], onPreview }) {
  const params = node.parameters || {}
  const rawOperation = (params.operation || 'create').toLowerCase()
  const rawEntity = (params.entity || 'contacts').toLowerCase()

  const [showAdvanced, setShowAdvanced] = useState(false)
  const [queryMode, setQueryMode] = useState(params.fetch_xml ? 'fetchxml' : 'odata')

  // Identify resource matching current entity
  const resource = useMemo(() => {
    if (rawOperation === 'execute_action' || params.resource === 'Action') return 'Action'
    if (params.resource === 'CustomTable') return 'CustomTable'
    const found = RESOURCE_OPTIONS.find(r => r.entity && r.entity === rawEntity)
    if (found) return found.value
    return 'Contact'
  }, [rawEntity, rawOperation, params.resource])

  // Operation options based on resource
  const operationOptions = useMemo(() => {
    if (resource === 'Action') {
      return [{ value: 'execute_action', label: 'Execute Action', hint: ALL_OPS.execute_action.hint }]
    }
    return [
      { value: 'create', label: ALL_OPS.create.label, hint: ALL_OPS.create.hint },
      { value: 'update', label: ALL_OPS.update.label, hint: ALL_OPS.update.hint },
      { value: 'upsert', label: ALL_OPS.upsert.label, hint: ALL_OPS.upsert.hint },
      { value: 'get', label: ALL_OPS.get.label, hint: ALL_OPS.get.hint },
      { value: 'query', label: ALL_OPS.query.label, hint: ALL_OPS.query.hint },
      { value: 'search', label: ALL_OPS.search.label, hint: ALL_OPS.search.hint },
      { value: 'delete', label: ALL_OPS.delete.label, hint: ALL_OPS.delete.hint },
      { value: 'execute_action', label: ALL_OPS.execute_action.label, hint: ALL_OPS.execute_action.hint },
    ]
  }, [resource])

  const operation = useMemo(() => {
    if (resource === 'Action') return 'execute_action'
    if (operationOptions.some(o => o.value === rawOperation)) return rawOperation
    return 'create'
  }, [resource, operationOptions, rawOperation])

  const handleChange = (key, value) => {
    const next = { ...params, [key]: value }
    onParamsChange(next)
  }

  const handleResourceChange = (val) => {
    const resOpt = RESOURCE_OPTIONS.find(r => r.value === val)
    if (val === 'Action') {
      onParamsChange({
        ...params,
        resource: 'Action',
        operation: 'execute_action',
        action_name: params.action_name || 'WhoAmI',
      })
    } else if (val === 'CustomTable') {
      onParamsChange({
        ...params,
        resource: 'CustomTable',
        entity: params.entity || '',
        operation: operation === 'execute_action' ? 'query' : operation,
      })
    } else {
      const defaultEntity = resOpt?.entity || 'contacts'
      onParamsChange({
        ...params,
        resource: val,
        entity: defaultEntity,
        operation: operation === 'execute_action' ? 'create' : operation,
      })
    }
  }

  const handleOperationChange = (val) => {
    const next = { ...params, operation: val }
    if (val === 'execute_action' && !next.action_name) {
      next.action_name = 'WhoAmI'
    }
    onParamsChange(next)
  }

  // Raw Record JSON sync
  const rawRecordJson = useMemo(() => {
    const recordData = params.data || params.record || {}
    try {
      return JSON.stringify(recordData, null, 2)
    } catch {
      return ''
    }
  }, [params.data, params.record])

  const handleRawRecordChange = (text) => {
    try {
      const parsed = JSON.parse(text)
      onParamsChange({ ...params, data: parsed, record: parsed })
    } catch {
      // Allow partial typing
      onParamsChange({ ...params, data: text, record: text })
    }
  }

  return (
    <div className="sf-editor">
      {/* 1. Resource Selector */}
      <div className="sf-field">
        <label>
          <span>Resource <span className="required-badge">*</span></span>
          <SearchableSelect
            value={resource}
            onChange={handleResourceChange}
            options={RESOURCE_OPTIONS}
            placeholder="Select resource…"
          />
          <span className="hint">{RESOURCE_OPTIONS.find(r => r.value === resource)?.desc || ''}</span>
        </label>
      </div>

      {/* 2. Table / Entity Logical Name */}
      {resource !== 'Action' && (
        <div className="sf-field">
          <label>
            <span>Table / Entity Set Name <span className="required-badge">*</span></span>
            <input
              type="text"
              value={params.entity ?? (RESOURCE_OPTIONS.find(r => r.value === resource)?.entity || '')}
              onChange={e => handleChange('entity', e.target.value)}
              placeholder="e.g. contacts, accounts, or cr841_projects"
            />
            <span className="hint">
              {resource === 'CustomTable'
                ? 'Enter custom Dataverse table logical name (e.g. cr841_project or new_equipment)'
                : `Dataverse entity set name for ${resource} (e.g. ${RESOURCE_OPTIONS.find(r => r.value === resource)?.entity || 'contacts'})`}
            </span>
          </label>
        </div>
      )}

      {/* 3. Operation Selector */}
      <div className="sf-field">
        <label>
          <span>Operation <span className="required-badge">*</span></span>
          <SearchableSelect
            value={operation}
            onChange={handleOperationChange}
            options={operationOptions}
            placeholder="Select operation…"
          />
          <span className="hint">{operationOptions.find(o => o.value === operation)?.hint || ''}</span>
        </label>
      </div>

      {/* 4. Primary Operation Inputs */}
      <div className="sf-primary">
        {/* Record ID for Get, Update, Delete */}
        {['get', 'update', 'delete'].includes(operation) && (
          <label>
            <span>Record ID (GUID) <span className="required-badge">*</span></span>
            <input
              type="text"
              value={params.record_id || ''}
              onChange={e => handleChange('record_id', e.target.value)}
              placeholder="00000000-0000-0000-0000-000000000000"
            />
            <span className="hint">The primary key GUID of the Dataverse record.</span>
          </label>
        )}

        {/* Alternate Key for Upsert */}
        {operation === 'upsert' && (
          <>
            <label>
              <span>Alternate Key Field <span className="required-badge">*</span></span>
              <input
                type="text"
                value={params.key_field || ''}
                onChange={e => handleChange('key_field', e.target.value)}
                placeholder="emailaddress1 or cr841_externalid"
              />
              <span className="hint">Name of the alternate key column defined on the table.</span>
            </label>
            <label>
              <span>Alternate Key Value <span className="required-badge">*</span></span>
              <input
                type="text"
                value={params.key_value || ''}
                onChange={e => handleChange('key_value', e.target.value)}
                placeholder="john@contoso.com"
              />
              <span className="hint">Value of the alternate key to match existing record.</span>
            </label>
          </>
        )}

        {/* Query (OData or FetchXML) */}
        {operation === 'query' && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ fontSize: 12, fontWeight: 600 }}>Query Mode</span>
              <div className="map-mode-toggle">
                <button
                  type="button"
                  className={`map-mode-btn ${queryMode === 'odata' ? 'active' : ''}`}
                  onClick={() => setQueryMode('odata')}
                >
                  OData Filters
                </button>
                <button
                  type="button"
                  className={`map-mode-btn ${queryMode === 'fetchxml' ? 'active' : ''}`}
                  onClick={() => setQueryMode('fetchxml')}
                >
                  FetchXML
                </button>
              </div>
            </div>

            {queryMode === 'odata' ? (
              <>
                <label>
                  <span>Filter Query ($filter)</span>
                  <input
                    type="text"
                    value={params.filter || ''}
                    onChange={e => handleChange('filter', e.target.value)}
                    placeholder="statecode eq 0 and emailaddress1 ne null"
                  />
                  <span className="hint">Standard OData filter expression.</span>
                </label>
                <label>
                  <span>Select Fields ($select)</span>
                  <input
                    type="text"
                    value={typeof params.select === 'string' ? params.select : (params.select || []).join(',')}
                    onChange={e => handleChange('select', e.target.value)}
                    placeholder="fullname,emailaddress1,telephone1"
                  />
                  <span className="hint">Comma-separated column names to return.</span>
                </label>
                <label>
                  <span>Expand Relations ($expand)</span>
                  <input
                    type="text"
                    value={params.expand || ''}
                    onChange={e => handleChange('expand', e.target.value)}
                    placeholder="parentcustomerid_account($select=name)"
                  />
                  <span className="hint">Navigation properties to expand inline.</span>
                </label>
                <label>
                  <span>Sort Order ($orderby)</span>
                  <input
                    type="text"
                    value={params.orderby || ''}
                    onChange={e => handleChange('orderby', e.target.value)}
                    placeholder="createdon desc"
                  />
                  <span className="hint">Ordering expression.</span>
                </label>
                <label>
                  <span>Max Records ($top)</span>
                  <input
                    type="number"
                    min={1}
                    max={5000}
                    value={params.top ?? 50}
                    onChange={e => handleChange('top', Number(e.target.value))}
                  />
                </label>
              </>
            ) : (
              <label>
                <span>FetchXML Query <span className="required-badge">*</span></span>
                <textarea
                  value={params.fetch_xml || ''}
                  onChange={e => handleChange('fetch_xml', e.target.value)}
                  placeholder={`<fetch top="50">\n  <entity name="contact">\n    <attribute name="fullname" />\n    <filter>\n      <condition attribute="statecode" operator="eq" value="0" />\n    </filter>\n  </entity>\n</fetch>`}
                  rows={6}
                  style={{ fontFamily: 'monospace', fontSize: 11 }}
                />
                <span className="hint">Native Dataverse FetchXML query string. Overrides OData parameters.</span>
              </label>
            )}
          </>
        )}

        {/* Search */}
        {operation === 'search' && (
          <>
            <label>
              <span>Search Term <span className="required-badge">*</span></span>
              <input
                type="text"
                value={params.query || params.search_term || ''}
                onChange={e => handleChange('query', e.target.value)}
                placeholder="Contoso or john@example.com"
              />
              <span className="hint">Keywords or email matching records across standard text columns.</span>
            </label>
            <label>
              <span>Select Fields ($select)</span>
              <input
                type="text"
                value={typeof params.select === 'string' ? params.select : (params.select || []).join(',')}
                onChange={e => handleChange('select', e.target.value)}
                placeholder="fullname,emailaddress1,telephone1"
              />
            </label>
            <label>
              <span>Max Records ($top)</span>
              <input
                type="number"
                min={1}
                max={500}
                value={params.top ?? 50}
                onChange={e => handleChange('top', Number(e.target.value))}
              />
            </label>
          </>
        )}

        {/* Execute Action */}
        {operation === 'execute_action' && (
          <>
            <label>
              <span>Action Name <span className="required-badge">*</span></span>
              <input
                type="text"
                value={params.action_name || ''}
                onChange={e => handleChange('action_name', e.target.value)}
                placeholder="WhoAmI or custom action name"
              />
              <span className="hint">Name of the Dataverse unbound action or function.</span>
            </label>
            <label>
              <span>Action Parameters (JSON)</span>
              <textarea
                value={typeof params.payload === 'string' ? params.payload : JSON.stringify(params.payload || {}, null, 2)}
                onChange={e => {
                  try {
                    handleChange('payload', JSON.parse(e.target.value))
                  } catch {
                    handleChange('payload', e.target.value)
                  }
                }}
                placeholder='{}'
                rows={4}
                style={{ fontFamily: 'monospace', fontSize: 11 }}
              />
              <span className="hint">JSON payload sent to the action.</span>
            </label>
          </>
        )}
      </div>

      {/* 5. Additional Fields (Accordion matching Salesforce) */}
      {['create', 'update', 'upsert'].includes(operation) && (
        <DynamicsCrmAdditionalFields
          node={node}
          onParamsChange={onParamsChange}
          mapping={mapping}
          onPreview={onPreview}
        />
      )}

      {/* 6. Advanced Options Drawer */}
      <div className="sf-advanced" style={{ marginTop: 12 }}>
        <button
          type="button"
          className="sf-advanced-toggle"
          onClick={() => setShowAdvanced(v => !v)}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--muted)',
            fontSize: 12,
            fontWeight: 500,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 0'
          }}
        >
          <span className="sf-caret">{showAdvanced ? '▾' : '▸'}</span>
          Advanced Options
        </button>

        {showAdvanced && (
          <div className="sf-advanced-body" style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <label>
              <span>Timeout (seconds)</span>
              <input
                type="number"
                min={1}
                max={300}
                value={params.timeout_seconds ?? 30}
                onChange={e => handleChange('timeout_seconds', Number(e.target.value))}
              />
            </label>

            {['create', 'update', 'upsert'].includes(operation) && (
              <label>
                <span>Raw Record Data (JSON)</span>
                <textarea
                  value={rawRecordJson}
                  onChange={e => handleRawRecordChange(e.target.value)}
                  placeholder='{"firstname": "John", "lastname": "Doe"}'
                  rows={4}
                  style={{ fontFamily: 'monospace', fontSize: 11 }}
                />
                <span className="hint">Bidirectionally synced with Record Fields above.</span>
              </label>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
