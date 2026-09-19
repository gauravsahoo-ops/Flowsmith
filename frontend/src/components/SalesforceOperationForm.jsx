const OPERATION_FIELDS = {
  search: ['object_name', 'search_field', 'search_value'],
  get: ['object_name', 'record_id'],
  create: ['object_name', 'record'],
  update: ['object_name', 'record_id', 'record'],
  upsert: ['object_name', 'external_id_field', 'external_id', 'record'],
  delete: ['object_name', 'record_id'],
  query: ['soql'],
  describe: ['object_name'],
  list: [],
  bulk: ['object_name', 'bulk_operation', 'records', 'external_id_field'],
}

const FIELD_PLACEHOLDERS = {
  object_name: 'Account',
  search_field: 'Email',
  search_value: '{{ $json.email }}',
  record_id: 'a0B...',
  external_id_field: 'Legacy_Id__c',
  external_id: '12345',
  soql: 'SELECT Id, Name FROM Account LIMIT 10',
}

export default function SalesforceOperationForm({ node, onParamsChange }) {
  const params = node.parameters || {}
  const operation = params.operation || 'query'
  const objectName = params.object_name || ''

  const handleChange = (key, value) => {
    onParamsChange({ ...params, [key]: value })
  }

  const visibleFields = OPERATION_FIELDS[operation] || []

  // For create/update/upsert, record is handled via Additional Fields, so hide generic record field
  const showGenericRecord = visibleFields.includes('record') && !['create', 'update', 'upsert'].includes(operation)

  return (
    <div className="sf-operation-form">
      {/* Credential is handled globally, not here */}

      {/* Object - for most operations */}
      {visibleFields.includes('object_name') && (
        <label>
          <span>Object {operation !== 'list' && <span className="required-badge">*</span>}</span>
          <input
            type="text"
            value={objectName}
            onChange={e => handleChange('object_name', e.target.value)}
            placeholder={FIELD_PLACEHOLDERS.object_name}
            list="sf-objects"
          />
          <span className="hint">Salesforce object API name, e.g. Account, Contact, Lead</span>
        </label>
      )}

      {/* Search specific */}
      {operation === 'search' && (
        <>
          <label>
            <span>Search field <span className="required-badge">*</span></span>
            <input
              type="text"
              value={params.search_field || ''}
              onChange={e => handleChange('search_field', e.target.value)}
              placeholder={FIELD_PLACEHOLDERS.search_field}
            />
          </label>
          <label>
            <span>Search value <span className="required-badge">*</span></span>
            <input
              type="text"
              value={params.search_value || ''}
              onChange={e => handleChange('search_value', e.target.value)}
              placeholder={FIELD_PLACEHOLDERS.search_value}
            />
            <span className="hint">Supports expressions like {`{{ $json.email }}`}</span>
          </label>
        </>
      )}

      {/* Get/Delete/Update record_id */}
      {['get', 'delete', 'update'].includes(operation) && (
        <label>
          <span>Record ID <span className="required-badge">*</span></span>
          <input
            type="text"
            value={params.record_id || ''}
            onChange={e => handleChange('record_id', e.target.value)}
            placeholder={FIELD_PLACEHOLDERS.record_id}
          />
        </label>
      )}

      {/* Upsert external id */}
      {operation === 'upsert' && (
        <>
          <label>
            <span>External ID field <span className="required-badge">*</span></span>
            <input
              type="text"
              value={params.external_id_field || ''}
              onChange={e => handleChange('external_id_field', e.target.value)}
              placeholder={FIELD_PLACEHOLDERS.external_id_field}
            />
          </label>
          <label>
            <span>External ID value <span className="required-badge">*</span></span>
            <input
              type="text"
              value={params.external_id || ''}
              onChange={e => handleChange('external_id', e.target.value)}
              placeholder={FIELD_PLACEHOLDERS.external_id}
            />
          </label>
        </>
      )}

      {/* Query SOQL */}
      {operation === 'query' && (
        <label>
          <span>SOQL query <span className="required-badge">*</span></span>
          <textarea
            value={params.soql || ''}
            onChange={e => handleChange('soql', e.target.value)}
            placeholder={FIELD_PLACEHOLDERS.soql}
            rows={3}
          />
        </label>
      )}

      {/* Bulk */}
      {operation === 'bulk' && (
        <>
          <label>
            <span>Bulk operation <span className="required-badge">*</span></span>
            <select value={params.bulk_operation || 'insert'} onChange={e => handleChange('bulk_operation', e.target.value)}>
              <option value="insert">Insert</option>
              <option value="update">Update</option>
              <option value="upsert">Upsert</option>
              <option value="delete">Delete</option>
            </select>
          </label>
          <label>
            <span>Records</span>
            <textarea
              value={typeof params.records === 'string' ? params.records : JSON.stringify(params.records || [], null, 2)}
              onChange={e => {
                try {
                  const parsed = JSON.parse(e.target.value)
                  handleChange('records', parsed)
                } catch {
                  handleChange('records', e.target.value)
                }
              }}
              placeholder='[{"Name": "Acme"}]'
              rows={4}
            />
          </label>
          {params.bulk_operation === 'upsert' && (
            <label>
              <span>External ID field (upsert)</span>
              <input
                type="text"
                value={params.external_id_field || ''}
                onChange={e => handleChange('external_id_field', e.target.value)}
                placeholder={FIELD_PLACEHOLDERS.external_id_field}
              />
            </label>
          )}
        </>
      )}

      {/* Generic record for non-create/update/upsert is handled via Additional Fields component, so hide here */}
      {showGenericRecord && (
        <label>
          <span>Record fields</span>
          <textarea
            value={typeof params.record === 'string' ? params.record : JSON.stringify(params.record || {}, null, 2)}
            onChange={e => {
              try {
                const parsed = JSON.parse(e.target.value)
                handleChange('record', parsed)
              } catch {
                handleChange('record', e.target.value)
              }
            }}
            placeholder='{"Name": "Acme"}'
            rows={3}
          />
        </label>
      )}

      {/* Name field for create - special handling for Account Create */}
      {operation === 'create' && (
        <label>
          <span>Name <span className="required-badge">*</span></span>
          <input
            type="text"
            value={params.record?.Name || ''}
            onChange={e => handleChange('record', { ...(params.record || {}), Name: e.target.value })}
            placeholder="Acme Inc."
          />
        </label>
      )}
    </div>
  )
}
