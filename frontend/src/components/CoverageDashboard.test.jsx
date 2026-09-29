import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import CoverageDashboard from './CoverageDashboard'

describe('CoverageDashboard Suite', () => {
  it('renders loading skeleton when initialLoading is true', () => {
    const html = renderToStaticMarkup(React.createElement(CoverageDashboard, { initialLoading: true }))
    expect(html).toContain('skeleton-table')
  })

  it('renders dashboard sub-tabs and headers when loaded', () => {
    const html = renderToStaticMarkup(React.createElement(CoverageDashboard, { initialLoading: false }))
    expect(html).toContain('Coverage &amp; Benchmarks')
    expect(html).toContain('Connector Certifications')
    expect(html).toContain('Canonical Node Contract')
  })
})
