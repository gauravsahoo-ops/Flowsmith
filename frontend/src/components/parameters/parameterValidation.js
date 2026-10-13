/**
 * Validates a single parameter value against the metadata emitted by the
 * backend ParameterSchemaBuilder.
 *
 * Returns `null` when valid, or a human-readable message when not. Never
 * invents a value — an empty optional field is valid, an empty required field
 * is not.
 */
export function validateField(field, value) {
  if (!field) return null

  const { name, type, required, minimum, maximum, min_length: minLength, max_length: maxLength, pattern, min_items: minItems } = field
  const empty = value === undefined || value === null || value === ''
  const label = field.title || name || 'This field'

  if (empty) {
    if (required) return `${label} is required.`
    return null
  }

  if (type === 'number') {
    const n = typeof value === 'number' ? value : Number(value)
    if (Number.isNaN(n)) return `${label} must be a number.`
    if (minimum !== undefined && minimum !== null && n < minimum) {
      return `${label} must be at least ${minimum}.`
    }
    if (maximum !== undefined && maximum !== null && n > maximum) {
      return `${label} must be at most ${maximum}.`
    }
    return null
  }

  if (type === 'string' || type === 'select') {
    const s = String(value)
    if (minLength !== undefined && minLength !== null && s.length < minLength) {
      return `${label} must be at least ${minLength} character${minLength === 1 ? '' : 's'}.`
    }
    if (maxLength !== undefined && maxLength !== null && s.length > maxLength) {
      return `${label} must be at most ${maxLength} characters.`
    }
    if (pattern) {
      let re
      try {
        re = new RegExp(pattern)
      } catch {
        return null // an invalid server-side pattern must not block the user
      }
      if (!re.test(s)) return `${label} does not match the required format.`
    }
    if (type === 'select' && Array.isArray(field.enum) && field.enum.length > 0) {
      if (!field.enum.some((option) => String(option) === s)) {
        return `${label} must be one of the available options.`
      }
    }
    return null
  }

  if (type === 'list' && Array.isArray(value)) {
    if (minItems !== undefined && minItems !== null && value.length < minItems) {
      return `${label} needs at least ${minItems} item${minItems === 1 ? '' : 's'}.`
    }
  }

  return null
}

/**
 * Evaluates a field's `show_if` rule against the current form state.
 *
 * Supported shapes:
 *   { operation: ['query'] }            -> visible when operation is in the list
 *   { operation: ['!delete'] }          -> visible unless operation is 'delete'
 *   { field: ['a', 'b'] }               -> visible when that field's value is in the list
 *   { field: { equals: 'x' } }          -> visible when that field's value === x
 *
 * A missing rule means the field is always visible.
 */
export function isFieldVisible(field, state = {}) {
  const rule = field?.show_if
  if (!rule || typeof rule !== 'object') return true

  const entries = Object.entries(rule)
  if (entries.length === 0) return true

  return entries.every(([key, expected]) => {
    const actual = state[key]
    const actualStr = actual === undefined || actual === null ? '' : String(actual)

    if (Array.isArray(expected)) {
      const positives = expected.filter((v) => !String(v).startsWith('!'))
      const negatives = expected.filter((v) => String(v).startsWith('!')).map((v) => String(v).slice(1))

      // A negated-only rule means "visible unless one of these".
      if (positives.length === 0) return !negatives.includes(actualStr)

      if (!positives.some((v) => String(v) === actualStr)) return false
      if (negatives.includes(actualStr)) return false
      return true
    }

    if (expected && typeof expected === 'object') {
      if ('equals' in expected) return String(expected.equals) === actualStr
      if ('not_equals' in expected) return String(expected.not_equals) !== actualStr
      return true
    }

    return String(expected) === actualStr
  })
}

/**
 * Groups fields for rendering: the main form, the advanced accordion, and the
 * currently-visible subset. Operation-scoped fields that are hidden are dropped.
 */
export function groupFields(fields, state) {
  const visible = (fields || []).filter((f) => isFieldVisible(f, state))
  return {
    visible,
    main: visible.filter((f) => !f.advanced && f.group !== 'advanced'),
    advanced: visible.filter((f) => f.advanced || f.group === 'advanced'),
  }
}
