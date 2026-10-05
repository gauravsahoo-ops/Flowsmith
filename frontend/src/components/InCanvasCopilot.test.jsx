import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import InCanvasCopilot from './InCanvasCopilot'

describe('InCanvasCopilot Component', () => {
  it('returns null when open is false', () => {
    const html = renderToStaticMarkup(React.createElement(InCanvasCopilot, { open: false }))
    expect(html).toBe('')
  })

  it('renders copilot prompt bar when open is true', () => {
    const html = renderToStaticMarkup(React.createElement(InCanvasCopilot, { open: true }))
    expect(html).toContain('In-Canvas AI Copilot')
    expect(html).toContain('Surgical Diff')
    expect(html).toContain('Auto-Layout')
    expect(html).toContain('Add Slack Alert')
    expect(html).toContain('Add Retry Policy')
    expect(html).toContain('Explain Workflow')
    expect(html).toContain('Optimize Reliability')
    expect(html).toContain('Apply')
  })
})
