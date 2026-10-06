import { useState, useCallback, useMemo } from 'react'
import MappingField from './MappingField'
import { formatToInput, getDefaultForSchema, resolveRef } from '../utils/jsonFormHelpers'

const TYPE_COMPONENTS = {
  string: StringField,
  number: NumberField,
  integer: NumberField,
  boolean: BooleanField,
  object: ObjectField,
  array: ArrayField,
  color: ColorField,
}

function StringField({ schema, value, onChange, path, mapping = [], onPreview, error }) {
  const { format, enum: enumValues, title, description } = schema
  const Input = formatToInput(format)

  if (enumValues && enumValues.length) {
    return (
      <label className="select-field">
        <span>{title || path}</span>
        <select
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value || undefined)}
          className={error ? 'invalid' : ''}
        >
          <option value="">-- select --</option>
          {enumValues.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
        {error && <span className="field-error">{error}</span>}
        {description && <span className="hint">{description}</span>}
      </label>
    )
  }

  if (mapping.length > 0 || onPreview) {
    return <MappingField schema={schema} value={value} onChange={onChange} path={path} mapping={mapping} onPreview={onPreview} error={error} />
  }

  return (
    <label className="text-field">
      <span>{title || path}</span>
      <input
        type={Input}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || undefined)}
        placeholder={description}
        className={error ? 'invalid' : ''}
      />
      {error && <span className="field-error">{error}</span>}
    </label>
  )
}

function NumberField({ schema, value, onChange, path, error }) {
  const { title, description, minimum, maximum, step } = schema
  return (
    <label className="number-field">
      <span>{title || path}</span>
      <input
        type="number"
        value={value ?? ''}
        onChange={(e) => {
          const v = e.target.value
          onChange(v === '' ? undefined : Number(v))
        }}
        min={minimum}
        max={maximum}
        step={step ?? (schema.type === 'integer' ? 1 : 0.1)}
        placeholder={description}
        className={error ? 'invalid' : ''}
      />
      {error && <span className="field-error">{error}</span>}
    </label>
  )
}

function BooleanField({ schema, value, onChange, path, error }) {
  const { title, description, format } = schema
  const inputType = format === 'password' ? 'password' : 'checkbox'
  return (
    <label className="check">
      <input
        type={inputType}
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{title || path}</span>
      {error && <span className="field-error">{error}</span>}
      {description && <span className="hint">{description}</span>}
    </label>
  )
}

function ColorField({ schema, value, onChange, path }) {
  const { title, description } = schema
  return (
    <label className="text-field">
      <span>{title || path}</span>
      <input
        type="color"
        value={value ?? '#ffffff'}
        onChange={(e) => onChange(e.target.value)}
        title={description}
      />
    </label>
  )
}

function ObjectField({ schema, value, onChange, path, rootSchema, errors }) {
  const { properties = {}, required = [] } = schema
  const entries = Object.entries(properties)
  const [expanded, setExpanded] = useState(true)

  if (!entries.length) {
    return (
      <MapField schema={schema} value={value} onChange={onChange} path={path} rootSchema={rootSchema} />
    )
  }

  const handleChange = (key, val) => {
    onChange({ ...(value || {}), [key]: val })
  }

  return (
    <fieldset className="object-field">
      <legend>
        <button type="button" onClick={() => setExpanded(!expanded)} className="toggle">
          {expanded ? '▼' : '▶'} {path}
        </button>
        {schema.title && <span>{schema.title}</span>}
      </legend>
      {schema.description && <p className="hint">{schema.description}</p>}
      {expanded && (
        <div className="object-fields">
          {entries.map(([key, propSchema]) => (
            <div key={key} className="object-field-row">
              {required.includes(key) && <span className="required-badge" title="Required">*</span>}
              <SchemaField
                schema={propSchema}
                value={value?.[key]}
                onChange={(v) => handleChange(key, v)}
                path={key}
                rootSchema={rootSchema}
                errors={errors}
              />
            </div>
          ))}
        </div>
      )}
    </fieldset>
  )
}

function MapField({ schema, value, onChange, path }) {
  const [expanded, setExpanded] = useState(true)
  const isStringVal = typeof value === 'string'
  const [mode, setMode] = useState(isStringVal ? 'json' : 'fields')
  const [rawJson, setRawJson] = useState(() => {
    if (value === undefined || value === null) return ''
    if (typeof value === 'string') return value
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return ''
    }
  })
  const [jsonError, setJsonError] = useState(null)

  const entries = useMemo(() => {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return Object.entries(value)
    }
    return []
  }, [value])

  const handleFieldUpdate = (key, val) => {
    const current = (value && typeof value === 'object' && !Array.isArray(value)) ? { ...value } : {}
    current[key] = val
    onChange(current)
    try {
      setRawJson(JSON.stringify(current, null, 2))
      setJsonError(null)
    } catch (err) { console.error('[flowsmith] components/JsonForm.jsx', err) }
  }

  const handleKeyRename = (oldKey, newKey) => {
    const current = (value && typeof value === 'object' && !Array.isArray(value)) ? { ...value } : {}
    const val = current[oldKey]
    delete current[oldKey]
    current[newKey] = val
    onChange(current)
    try {
      setRawJson(JSON.stringify(current, null, 2))
      setJsonError(null)
    } catch (err) { console.error('[flowsmith] components/JsonForm.jsx', err) }
  }

  const handleRemove = (key) => {
    const current = (value && typeof value === 'object' && !Array.isArray(value)) ? { ...value } : {}
    delete current[key]
    onChange(current)
    try {
      setRawJson(JSON.stringify(current, null, 2))
      setJsonError(null)
    } catch (err) { console.error('[flowsmith] components/JsonForm.jsx', err) }
  }

  const handleAddField = () => {
    const current = (value && typeof value === 'object' && !Array.isArray(value)) ? { ...value } : {}
    let base = 'field'
    let counter = entries.length + 1
    while (`${base}_${counter}` in current) {
      counter++
    }
    const newKey = `${base}_${counter}`
    current[newKey] = ''
    onChange(current)
    try {
      setRawJson(JSON.stringify(current, null, 2))
      setJsonError(null)
    } catch (err) { console.error('[flowsmith] components/JsonForm.jsx', err) }
  }

  const handleJsonChange = (e) => {
    const text = e.target.value
    setRawJson(text)
    if (!text.trim()) {
      setJsonError(null)
      onChange({})
      return
    }
    if (text.trim().startsWith('{{') && text.trim().endsWith('}}')) {
      setJsonError(null)
      onChange(text.trim())
      return
    }
    try {
      const parsed = JSON.parse(text)
      setJsonError(null)
      onChange(parsed)
    } catch {
      setJsonError('Invalid JSON format')
    }
  }

  const switchMode = (newMode) => {
    if (newMode === 'fields') {
      if (rawJson.trim()) {
        try {
          const parsed = JSON.parse(rawJson)
          if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
            onChange(parsed)
            setJsonError(null)
            setMode('fields')
            return
          }
        } catch {
          setJsonError('Cannot convert text to fields. Fix JSON or stay in JSON mode.')
          return
        }
      } else {
        onChange({})
        setJsonError(null)
        setMode('fields')
        return
      }
    } else {
      if (value && typeof value === 'object') {
        setRawJson(JSON.stringify(value, null, 2))
      }
      setMode('json')
    }
  }

  return (
    <fieldset className="map-field">
      <legend>
        <button type="button" onClick={() => setExpanded(!expanded)} className="toggle">
          {expanded ? '▼' : '▶'}
        </button>
        <span>{schema.title || path}</span>
        <div className="map-legend-actions">
          <div className="map-mode-toggle">
            <button
              type="button"
              className={`map-mode-btn ${mode === 'fields' ? 'active' : ''}`}
              onClick={() => switchMode('fields')}
              title="Key-Value fields view"
            >
              Fields
            </button>
            <button
              type="button"
              className={`map-mode-btn ${mode === 'json' ? 'active' : ''}`}
              onClick={() => switchMode('json')}
              title="Raw JSON code view"
            >
              JSON
            </button>
          </div>
          {mode === 'fields' && (
            <button type="button" className="add-btn" onClick={handleAddField}>
              + Add Field
            </button>
          )}
        </div>
      </legend>
      {schema.description && <p className="hint">{schema.description}</p>}
      {expanded && (
        <div className="map-body">
          {mode === 'fields' ? (
            entries.length === 0 ? (
              <div className="map-empty-state">
                <span className="map-empty-hint">No fields added yet.</span>
                <button type="button" className="btn-add-field" onClick={handleAddField}>
                  + Add Field
                </button>
              </div>
            ) : (
              <div className="map-rows">
                {entries.map(([key, val], idx) => (
                  <div key={key || idx} className="map-row">
                    <input
                      className="map-key"
                      placeholder="Column name (e.g. firstname)"
                      value={key}
                      onChange={(e) => handleKeyRename(key, e.target.value)}
                    />
                    <input
                      className="map-val"
                      placeholder="Value or {{ expr }}"
                      value={typeof val === 'object' ? JSON.stringify(val) : (val ?? '')}
                      onChange={(e) => handleFieldUpdate(key, e.target.value)}
                    />
                    <button
                      type="button"
                      className="remove-btn"
                      title="Remove field"
                      onClick={() => handleRemove(key)}
                     style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
                  </div>
                ))}
              </div>
            )
          ) : (
            <div className="map-json-editor">
              <textarea
                className="map-json-textarea"
                rows={6}
                value={rawJson}
                onChange={handleJsonChange}
                placeholder={'{\n  "firstname": "John",\n  "lastname": "Doe",\n  "emailaddress1": "john@example.com"\n}'}
                spellCheck={false}
              />
              {jsonError && <span className="map-json-error" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>{jsonError}</span>}
            </div>
          )}
        </div>
      )}
    </fieldset>
  )
}

function ArrayField({ schema, value, onChange, path, rootSchema, errors }) {
  const { items, title, description } = schema
  const arr = Array.isArray(value) ? value : []
  const [expanded, setExpanded] = useState(true)

  const addItem = () => {
    const defaultVal = getDefaultForSchema(items)
    onChange([...arr, defaultVal])
  }

  const removeItem = (index) => {
    const newArr = arr.filter((_, i) => i !== index)
    onChange(newArr)
  }

  const onItemChange = (index, val) => {
    const newArr = [...arr]
    newArr[index] = val
    onChange(newArr)
  }

  return (
    <fieldset className="array-field">
      <legend>
        <button type="button" onClick={() => setExpanded(!expanded)} className="toggle">
          {expanded ? '▼' : '▶'} {path} [{arr.length}]
        </button>
        {title && <span>{title}</span>}
        <button type="button" className="add-btn" onClick={addItem}>+ Add</button>
      </legend>
      {description && <p className="hint">{description}</p>}
      {expanded && (
        <div className="array-items">
          {arr.map((item, index) => (
            <div key={index} className="array-item">
              <div className="array-item-header">
                <span>[{index}]</span>
                <button type="button" className="remove-btn" onClick={() => removeItem(index)} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
              </div>
              <SchemaField
                schema={items}
                value={item}
                onChange={(v) => onItemChange(index, v)}
                path={`${path}[${index}]`}
                rootSchema={rootSchema}
                errors={errors}
              />
            </div>
          ))}
        </div>
      )}
    </fieldset>
  )
}


export function SchemaField({ schema, value, onChange, path, rootSchema, mapping = [], onPreview, errors }) {
  const resolved = resolveRef(schema, rootSchema || schema)
  const type = resolved?.type ?? 'string'
  const Component = TYPE_COMPONENTS[type] || StringField
  const fieldError = errors?.[path]

  if (resolved?.oneOf || resolved?.anyOf) {
    return <OneOfField schema={resolved} value={value} onChange={onChange} path={path} errors={errors} />
  }

  return <Component schema={resolved} value={value} onChange={onChange} path={path} rootSchema={rootSchema} mapping={mapping} onPreview={onPreview} error={fieldError} errors={errors} />
}

function OneOfField({ schema, value, onChange, path, rootSchema, errors }) {
  const options = schema.oneOf || schema.anyOf || []
  const [selectedType, setSelectedType] = useState(0)

  const getTypeLabel = (s, i) => s?.title || s?.type || `Option ${i + 1}`

  return (
    <div className="oneof-field">
      <label>
        <span>{path}</span>
        <select value={selectedType} onChange={(e) => setSelectedType(Number(e.target.value))}>
          {options.map((s, i) => (
            <option key={i} value={i}>{getTypeLabel(s, i)}</option>
          ))}
        </select>
      </label>
      {options[selectedType] && (
        <SchemaField
          schema={options[selectedType]}
          value={value}
          onChange={onChange}
          path={path}
          rootSchema={rootSchema}
          errors={errors}
        />
      )}
    </div>
  )
}

function validate(schema, value) {
  const errors = {}

  if (schema?.required && schema.type === 'object') {
    for (const req of schema.required) {
      if (value?.[req] === undefined || value?.[req] === '' || value?.[req] === null) {
        errors[req] = `${req} is required`
      }
    }
  }

  if (schema?.type === 'string' && schema.minLength != null) {
    const len = (value ?? '').length
    if (len > 0 && len < schema.minLength) {
      errors[''] = `Minimum length is ${schema.minLength}`
    }
  }

  if (schema?.type === 'object' && value && typeof value === 'object') {
    for (const [key, propSchema] of Object.entries(schema.properties || {})) {
      const childErrors = validate(propSchema, value[key])
      for (const [k, v] of Object.entries(childErrors)) {
        errors[k ? `${key}.${k}` : key] = v
      }
    }
  }

  if (schema?.type === 'array' && Array.isArray(value)) {
    value.forEach((item, i) => {
      const childErrors = validate(schema.items, item)
      for (const [k, v] of Object.entries(childErrors)) {
        errors[`${i}${k ? `.${k}` : ''}`] = v
      }
    })
  }

  return errors
}

export function JsonForm({ schema, value, onChange, onError, mapping = [], onPreview, hiddenKeys = [] }) {
  const [errors, setErrors] = useState({})

  const filteredSchema = useMemo(() => {
    if (!hiddenKeys.length || !schema?.properties) return schema
    const next = { ...schema, properties: { ...schema.properties } }
    for (const k of hiddenKeys) delete next.properties[k]
    if (next.required) next.required = next.required.filter(k => !hiddenKeys.includes(k))
    return next
  }, [schema, hiddenKeys])

  const filteredValue = useMemo(() => {
    if (!hiddenKeys.length || !value) return value
    const next = { ...value }
    for (const k of hiddenKeys) delete next[k]
    return next
  }, [value, hiddenKeys])

  const handleChange = useCallback((newValue) => {
    // Merge back hidden keys from original value
    let merged = newValue
    if (hiddenKeys.length && value) {
      merged = { ...newValue }
      for (const k of hiddenKeys) if (value[k] !== undefined) merged[k] = value[k]
    }
    onChange?.(merged)
    const newErrors = validate(filteredSchema, merged)
    setErrors(newErrors)
    onError?.(newErrors)
  }, [filteredSchema, onChange, onError, hiddenKeys, value])

  const errorCount = Object.keys(errors).length

  return (
    <div className="json-form">
      <SchemaField
        schema={filteredSchema}
        value={filteredValue}
        onChange={handleChange}
        path=""
        rootSchema={filteredSchema}
        mapping={mapping}
        onPreview={onPreview}
        errors={errors}
      />
      {errorCount > 0 && (
        <div className="form-error-summary">
          {errorCount} validation error{errorCount !== 1 ? 's' : ''}
        </div>
      )}
    </div>
  )
}

export default JsonForm
