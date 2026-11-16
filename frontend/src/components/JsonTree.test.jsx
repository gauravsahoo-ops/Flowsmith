import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import JsonTree from './JsonTree'

function openNodeCount(html) {
  return (html.match(/<details[^>]*\bopen\b/g) || []).length
}

describe('JsonTree large payload guard', () => {
  it('collapses a large record array instead of rendering every field expanded', () => {
    const records = Array.from({ length: 50 }, (_, index) => ({
      id: index,
      name: `record-${index}`,
      status: 'active',
      description: 'x'.repeat(200),
      ...Object.fromEntries(
        Array.from({ length: 20 }, (_, field) => [`field_${field}`, `value-${field}`]),
      ),
    }))

    const html = renderToStaticMarkup(React.createElement(JsonTree, { value: records }))

    expect(html).toContain('auto-collapsed')
    // Only the root array should be open; each of the 50 records stays closed
    // and its field rows are not mounted at all.
    expect(openNodeCount(html)).toBe(1)
    expect(html).not.toContain('jt-row')
  })

  it('keeps small payloads expanded by default', () => {
    const html = renderToStaticMarkup(
      React.createElement(JsonTree, { value: { account: { id: '001', name: 'Acme' } } }),
    )

    expect(html).not.toContain('auto-collapsed')
    expect(openNodeCount(html)).toBeGreaterThan(1)
  })
})
