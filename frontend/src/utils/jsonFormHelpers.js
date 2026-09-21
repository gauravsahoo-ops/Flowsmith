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
