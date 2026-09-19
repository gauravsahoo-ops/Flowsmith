import { useEffect, useState } from 'react'
import { api } from '../api'

// Live Salesforce object/field discovery (Phase 9): populates the
// generic salesforce node's object_name from the connected org and
// shows a searchable field reference for dynamic configuration.
// Salesforce → Operation → Object → Schema → Fields.

const WRITE_OPS = new Set(['create', 'add_note', 'update', 'upsert', 'bulk'])
const ALIAS_TO_BACKEND = { add_note: 'create', get_many: 'query', custom_api_call: 'query', get_summary: 'describe' }

export default function SalesforceDiscovery({ node, onParamsChange }) {
  const params = node.parameters || {}
  const rawOp = params.operation || 'query'
  const operation = ALIAS_TO_BACKEND[rawOp] || rawOp

  const [fields, setFields] = useState([])
  const [schemaLabel, setSchemaLabel] = useState('')
  const [schemaError, setSchemaError] = useState('')
  const [loadingSchema, setLoadingSchema] = useState(false)

  const objectName = params.object_name || ''
  const showFields =
    WRITE_OPS.has(rawOp) || WRITE_OPS.has(operation) || operation === 'describe' || operation === 'search'

  useEffect(() => {
    let alive = true
    setFields([])
    setSchemaError('')
    if (!showFields || !objectName) return () => { alive = false }
    setLoadingSchema(true)
    api
      .salesforceObjectSchema(objectName)
      .then((data) => {
        if (!alive) return
        setFields(data.fields || [])
        setSchemaLabel(data.label || data.name || objectName)
      })
      .catch((err) => {
        if (!alive) return
        setSchemaError(err.message || 'Cannot load fields')
      })
      .finally(() => {
        if (alive) setLoadingSchema(false)
      })
    return () => {
      alive = false
    }
  }, [objectName, showFields])

  function setObject(name) {
    onParamsChange({ ...params, object_name: name })
  }

  return (
    <div className="sf-discovery">
      <label>
        Object
        <input
          value={objectName}
          placeholder="Object API name (e.g. Account, My_Object__c)"
          onChange={(e) => setObject(e.target.value)}
        />
      </label>

      {showFields && objectName && (
        <>
          {loadingSchema && <p className="hint">Loading fields…</p>}
          {schemaError && <p className="hint">Field discovery unavailable ({schemaError}).</p>}
          {!loadingSchema && !schemaError && fields.length > 0 && (
            <p className="hint">✓ Discovered {fields.length} fields for {schemaLabel || objectName}.</p>
          )}
        </>
      )}
    </div>
  )
}
