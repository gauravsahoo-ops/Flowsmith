import { useState, useCallback, useMemo } from 'react'
import MappingField from './MappingField'

export const formatToInput = (format) => {
  if (!format) return 'text'
  switch (format) {
    case 'uri': return 'url'
    case 'url': return 'url'
    case 'email': return 'email'
    case 'date-time': return 'datetime-local'
    case 'date': return 'date'
    case 'color': return 'color'
    case 'password': return 'password'
    default: return 'text'
  }
}

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

  if (!entries.length && schema.additionalProperties) {
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
  const valueType = schema.additionalProperties?.type || 'string'
  const entries = Object.entries(value || {})
  const [expanded, setExpanded] = useState(true)

  const update = (key, val) => {
    onChange({ ...(value || {}), [key]: val })
  }

  const remove = (key) => {
    const next = { ...(value || {}) }
    delete next[key]
    onChange(next)
  }

  const addRow = () => {
    const key = `key${entries.length + 1}`
    onChange({ ...(value || {}), [key]: '' })
  }

  return (
    <fieldset className="map-field">
      <legend>
        <button type="button" onClick={() => setExpanded(!expanded)} className="toggle">
          {expanded ? '▼' : '▶'} {path}
        </button>
        {schema.title && <span>{schema.title}</span>}
        <button type="button" className="add-btn" onClick={addRow}>+ Add</button>
      </legend>
      {schema.description && <p className="hint">{schema.description}</p>}
      {expanded && (
        <div className="map-rows">
          {entries.map(([key, val]) => (
            <div key={key} className="map-row">
              <input
                className="map-key"
                value={key}
                onChange={(e) => {
                  const next = { ...(value || {}) }
                  delete next[key]
                  next[e.target.value || key] = val
                  onChange(next)
                }}
              />
              <MapValueInput
                type={valueType}
                value={val}
                onChange={(v) => update(key, v)}
              />
              <button type="button" className="remove-btn" onClick={() => remove(key)}>✕</button>
            </div>
          ))}
        </div>
      )}
    </fieldset>
  )
}

function MapValueInput({ type, value, onChange }) {
  if (type === 'boolean') {
    return (
      <select value={String(value)} onChange={(e) => onChange(e.target.value === 'true')}>
        <option value="false">false</option>
        <option value="true">true</option>
      </select>
    )
  }
  if (type === 'number' || type === 'integer') {
    return (
      <input
        type="number"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
      />
    )
  }
  return <input type="text" value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
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
                <button type="button" className="remove-btn" onClick={() => removeItem(index)}>✕</button>
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

export function getDefaultForSchema(schema) {
  if (!schema) return null
  switch (schema.type) {
    case 'string': return schema.default ?? (schema.enum?.[0] ?? '')
    case 'number':
    case 'integer': return schema.default ?? 0
    case 'boolean': return schema.default ?? false
    case 'object': return {}
    case 'array': return []
    default: return null
  }
}

export function resolveRef(schema, rootSchema) {
  if (!schema || !schema.$ref) return schema
  const name = schema.$ref.split('/').pop()
  return (rootSchema?.$defs || {})[name] || schema
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
