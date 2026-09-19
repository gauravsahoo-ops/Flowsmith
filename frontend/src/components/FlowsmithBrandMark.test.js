import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import FlowsmithBrandMark from './FlowsmithBrandMark'

describe('FlowsmithBrandMark Suite', () => {
  it('renders badge variant with gradient and node coordinates', () => {
    const html = renderToStaticMarkup(React.createElement(FlowsmithBrandMark, { size: 48, variant: 'badge' }))
    expect(html).toContain('svg')
    expect(html).toContain('viewBox="0 0 48 48"')
    expect(html).toContain('fs-brand-bg')
    expect(html).toContain('cx="28.5"')
    expect(html).toContain('cx="24.5"')
  })

  it('renders glyph variant with currentColor', () => {
    const html = renderToStaticMarkup(React.createElement(FlowsmithBrandMark, { size: 20, variant: 'glyph' }))
    expect(html).toContain('fill="currentColor"')
    expect(html).not.toContain('fs-brand-bg')
    expect(html).toContain('width="20"')
  })

  it('renders glow filter when requested', () => {
    const html = renderToStaticMarkup(React.createElement(FlowsmithBrandMark, { size: 32, glow: true }))
    expect(html).toContain('fs-brand-glow')
    expect(html).toContain('feDropShadow')
  })
})
