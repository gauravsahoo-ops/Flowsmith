import { describe, it, expect } from 'vitest'
import { validateField, isFieldVisible, groupFields } from './parameterValidation'

const base = (over = {}) => ({ name: 'x', title: 'X', type: 'string', ...over })

describe('validateField', () => {
  it('accepts an empty optional field', () => {
    expect(validateField(base({ required: false }), '')).toBeNull()
    expect(validateField(base({ required: false }), undefined)).toBeNull()
    expect(validateField(base({ required: false }), null)).toBeNull()
  })

  it('rejects an empty required field with a labelled message', () => {
    expect(validateField(base({ required: true }), '')).toBe('X is required.')
    expect(validateField(base({ required: true, title: 'SOQL' }), undefined)).toBe('SOQL is required.')
  })

  it('accepts a non-empty required field', () => {
    expect(validateField(base({ required: true }), 'value')).toBeNull()
  })

  describe('numeric bounds', () => {
    const num = (over = {}) => base({ type: 'number', title: 'Timeout', ...over })

    it('rejects non-numeric input', () => {
      expect(validateField(num(), 'abc')).toBe('Timeout must be a number.')
    })

    it('enforces minimum and maximum inclusively', () => {
      expect(validateField(num({ minimum: 1 }), 1)).toBeNull()
      expect(validateField(num({ minimum: 1 }), 0)).toBe('Timeout must be at least 1.')
      expect(validateField(num({ maximum: 300 }), 300)).toBeNull()
      expect(validateField(num({ maximum: 300 }), 301)).toBe('Timeout must be at most 300.')
    })

    it('coerces numeric strings', () => {
      expect(validateField(num({ minimum: 1 }), '5')).toBeNull()
      expect(validateField(num({ minimum: 1 }), '0')).toBe('Timeout must be at least 1.')
    })
  })

  describe('string constraints', () => {
    it('enforces min/max length', () => {
      expect(validateField(base({ min_length: 3 }), 'ab')).toBe('X must be at least 3 characters.')
      expect(validateField(base({ min_length: 1 }), 'a')).toBeNull()
      expect(validateField(base({ max_length: 4 }), 'abcde')).toBe('X must be at most 4 characters.')
      expect(validateField(base({ min_length: 1 }), '')).toBeNull() // empty + optional
    })

    it('enforces a pattern', () => {
      expect(validateField(base({ pattern: '^SELECT' }), 'SELECT 1')).toBeNull()
      expect(validateField(base({ pattern: '^SELECT' }), 'DELETE 1')).toBe(
        'X does not match the required format.',
      )
    })

    it('never blocks the user on an invalid server-side pattern', () => {
      expect(validateField(base({ pattern: '([' }), 'anything')).toBeNull()
    })
  })

  describe('select options', () => {
    it('rejects a value outside the declared enum', () => {
      expect(validateField(base({ type: 'select', enum: ['a', 'b'] }), 'c')).toBe(
        'X must be one of the available options.',
      )
      expect(validateField(base({ type: 'select', enum: ['a', 'b'] }), 'a')).toBeNull()
    })
  })

  describe('array constraints', () => {
    it('enforces min_items', () => {
      expect(validateField(base({ type: 'list', min_items: 1 }), [])).toBe('X needs at least 1 item.')
      expect(validateField(base({ type: 'list', min_items: 1 }), ['a'])).toBeNull()
    })
  })

  it('returns null for unknown fields', () => {
    expect(validateField(undefined, 'x')).toBeNull()
    expect(validateField(null, 'x')).toBeNull()
  })

  it('does not validate booleans against string rules', () => {
    expect(validateField(base({ type: 'boolean' }), false)).toBeNull()
    expect(validateField(base({ type: 'boolean', required: true }), false)).toBeNull()
  })
})

describe('isFieldVisible', () => {
  it('shows a field with no rule', () => {
    expect(isFieldVisible(base(), { operation: 'anything' })).toBe(true)
    expect(isFieldVisible(base({ show_if: null }), {})).toBe(true)
    expect(isFieldVisible(base({ show_if: {} }), {})).toBe(true)
    expect(isFieldVisible(undefined, {})).toBe(true)
  })

  it('honours a positive operation membership rule', () => {
    const f = base({ show_if: { operation: ['query'] } })
    expect(isFieldVisible(f, { operation: 'query' })).toBe(true)
    expect(isFieldVisible(f, { operation: 'insert' })).toBe(false)
  })

  it('honours a negated-only operation rule', () => {
    const f = base({ show_if: { operation: ['!delete'] } })
    expect(isFieldVisible(f, { operation: 'query' })).toBe(true)
    expect(isFieldVisible(f, { operation: 'delete' })).toBe(false)
  })

  it('applies positives and negatives together', () => {
    const f = base({ show_if: { operation: ['query', '!explain'] } })
    expect(isFieldVisible(f, { operation: 'query' })).toBe(true)
    expect(isFieldVisible(f, { operation: 'explain' })).toBe(false)
    expect(isFieldVisible(f, { operation: 'insert' })).toBe(false)
  })

  it('treats a missing value as empty string', () => {
    const f = base({ show_if: { operation: ['!delete'] } })
    expect(isFieldVisible(f, {})).toBe(true)
  })

  it('supports arbitrary field conditions, not just operation', () => {
    const f = base({ show_if: { auth_mode: ['advanced'] } })
    expect(isFieldVisible(f, { auth_mode: 'advanced' })).toBe(true)
    expect(isFieldVisible(f, { auth_mode: 'basic' })).toBe(false)
  })

  it('supports the object form {equals / not_equals}', () => {
    expect(isFieldVisible(base({ show_if: { mode: { equals: 'x' } } }), { mode: 'x' })).toBe(true)
    expect(isFieldVisible(base({ show_if: { mode: { equals: 'x' } } }), { mode: 'y' })).toBe(false)
    expect(isFieldVisible(base({ show_if: { mode: { not_equals: 'x' } } }), { mode: 'y' })).toBe(true)
  })

  it('requires every rule to pass', () => {
    const f = base({ show_if: { operation: ['query'], mode: ['advanced'] } })
    expect(isFieldVisible(f, { operation: 'query', mode: 'advanced' })).toBe(true)
    expect(isFieldVisible(f, { operation: 'query', mode: 'simple' })).toBe(false)
  })

  it('ignores an unrecognised rule shape rather than hiding the field', () => {
    expect(isFieldVisible(base({ show_if: { mode: 'scalar' } }), { mode: 'scalar' })).toBe(true)
    expect(isFieldVisible(base({ show_if: { mode: 'scalar' } }), { mode: 'other' })).toBe(false)
  })
})

describe('groupFields', () => {
  const fields = [
    base({ name: 'query', title: 'Query' }),
    base({ name: 'timeout_seconds', title: 'Timeout', advanced: true, group: 'advanced' }),
    base({ name: 'record_id', title: 'Record', show_if: { operation: ['update'] } }),
    base({ name: 'legacy', title: 'Legacy', group: 'advanced' }),
  ]

  it('splits main vs advanced among visible fields', () => {
    const { main, advanced, visible } = groupFields(fields, { operation: 'update' })
    expect(visible).toHaveLength(4)
    expect(main.map((f) => f.name)).toEqual(['query', 'record_id'])
    expect(advanced.map((f) => f.name)).toEqual(['timeout_seconds', 'legacy'])
  })

  it('drops operation-hidden fields from both groups', () => {
    const { main, visible } = groupFields(fields, { operation: 'query' })
    expect(visible.map((f) => f.name)).not.toContain('record_id')
    expect(main.map((f) => f.name)).not.toContain('record_id')
  })

  it('handles a missing field list', () => {
    expect(groupFields(null, {})).toEqual({ visible: [], main: [], advanced: [] })
    expect(groupFields(undefined, {})).toEqual({ visible: [], main: [], advanced: [] })
  })
})
