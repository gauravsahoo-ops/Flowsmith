import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import Tooltip from './Tooltip'

describe('Tooltip Component', () => {
  it('renders child element and suppresses duplicate native browser title', () => {
    const html = renderToStaticMarkup(
      React.createElement(
        Tooltip,
        { label: 'Zoom to fit (Ctrl+0)' },
        React.createElement('button', { type: 'button', title: 'Old native title' }, 'Fit')
      )
    )

    expect(html).toContain('tooltip')
    expect(html).toContain('Fit')
    // Suppresses native title attribute on the button element to avoid duplicate browser tooltip
    expect(html).not.toContain('title=')
    // Retains aria-label for accessibility
    expect(html).toContain('aria-label="Old native title"')
  })

  it('sets aria-label to label if no child title or aria-label exists', () => {
    const html = renderToStaticMarkup(
      React.createElement(
        Tooltip,
        { label: 'Auto-layout (tidy everything)' },
        React.createElement('button', { type: 'button' }, 'Layout')
      )
    )

    expect(html).toContain('aria-label="Auto-layout (tidy everything)"')
    expect(html).not.toContain('title=')
  })

  it('renders children directly if label is falsy', () => {
    const html = renderToStaticMarkup(
      React.createElement(
        Tooltip,
        { label: null },
        React.createElement('button', { type: 'button' }, 'Simple')
      )
    )

    expect(html).toBe('<button type="button">Simple</button>')
  })
})
