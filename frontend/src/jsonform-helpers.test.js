import { describe, it, expect } from 'vitest'
import { formatToInput, getDefaultForSchema, resolveRef } from './components/JsonForm.jsx'

describe('formatToInput', () => {
  it('returns "text" for undefined/null format', () => {
    expect(formatToInput(undefined)).toBe('text')
    expect(formatToInput(null)).toBe('text')
  })

  it('maps uri to url', () => {
    expect(formatToInput('uri')).toBe('url')
  })

  it('maps url to url', () => {
    expect(formatToInput('url')).toBe('url')
  })

  it('maps email to email', () => {
    expect(formatToInput('email')).toBe('email')
  })

  it('maps date-time to datetime-local', () => {
    expect(formatToInput('date-time')).toBe('datetime-local')
  })

  it('maps date to date', () => {
    expect(formatToInput('date')).toBe('date')
  })

  it('maps color to color', () => {
    expect(formatToInput('color')).toBe('color')
  })

  it('maps password to password', () => {
    expect(formatToInput('password')).toBe('password')
  })

  it('returns text for unknown formats', () => {
    expect(formatToInput('uuid')).toBe('text')
    expect(formatToInput('hostname')).toBe('text')
    expect(formatToInput('ipv4')).toBe('text')
  })
})

describe('getDefaultForSchema', () => {
  it('returns null for null/undefined schema', () => {
    expect(getDefaultForSchema(null)).toBeNull()
    expect(getDefaultForSchema(undefined)).toBeNull()
  })

  it('returns empty string for string type', () => {
    expect(getDefaultForSchema({ type: 'string' })).toBe('')
  })

  it('returns default value for string when set', () => {
    expect(getDefaultForSchema({ type: 'string', default: 'hello' })).toBe('hello')
  })

  it('returns first enum value for string with enum', () => {
    expect(getDefaultForSchema({ type: 'string', enum: ['a', 'b'] })).toBe('a')
  })

  it('returns 0 for number type', () => {
    expect(getDefaultForSchema({ type: 'number' })).toBe(0)
  })

  it('returns default for number when set', () => {
    expect(getDefaultForSchema({ type: 'number', default: 42 })).toBe(42)
  })

  it('returns 0 for integer type', () => {
    expect(getDefaultForSchema({ type: 'integer' })).toBe(0)
  })

  it('returns false for boolean type', () => {
    expect(getDefaultForSchema({ type: 'boolean' })).toBe(false)
  })

  it('returns default for boolean when set', () => {
    expect(getDefaultForSchema({ type: 'boolean', default: true })).toBe(true)
  })

  it('returns empty object for object type', () => {
    expect(getDefaultForSchema({ type: 'object' })).toEqual({})
  })

  it('returns empty array for array type', () => {
    expect(getDefaultForSchema({ type: 'array' })).toEqual([])
  })

  it('returns null for unknown type', () => {
    expect(getDefaultForSchema({ type: 'unknown' })).toBeNull()
  })
})

describe('resolveRef', () => {
  it('returns schema as-is when no $ref', () => {
    const schema = { type: 'string' }
    expect(resolveRef(schema, schema)).toBe(schema)
  })

  it('returns schema as-is when null/undefined', () => {
    expect(resolveRef(null, {})).toBeNull()
    expect(resolveRef(undefined, {})).toBeUndefined()
  })

  it('resolves $ref from rootSchema.$defs', () => {
    const schema = { $ref: '#/$defs/MyType' }
    const root = { $defs: { MyType: { type: 'string', title: 'My Type' } } }
    expect(resolveRef(schema, root)).toEqual({ type: 'string', title: 'My Type' })
  })

  it('returns original schema when ref target not found', () => {
    const schema = { $ref: '#/$defs/Missing' }
    const root = { $defs: {} }
    expect(resolveRef(schema, root)).toBe(schema)
  })

  it('handles $ref with different path formats', () => {
    const schema = { $ref: 'OtherType' }
    const root = { $defs: { OtherType: { type: 'number' } } }
    expect(resolveRef(schema, root)).toEqual({ type: 'number' })
  })

  it('returns schema when rootSchema has no $defs', () => {
    const schema = { $ref: '#/$defs/X' }
    expect(resolveRef(schema, {})).toBe(schema)
    expect(resolveRef(schema, null)).toBe(schema)
  })
})
