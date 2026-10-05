import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ThemeSwitcher from './ThemeSwitcher'

describe('ThemeSwitcher Component', () => {
  it('renders dark obsidian indicator in segmented variant', () => {
    const html = renderToStaticMarkup(React.createElement(ThemeSwitcher, { variant: 'segmented' }))
    expect(html).toContain('Dark Obsidian')
    expect(html).toContain('role="status"')
    expect(html).not.toContain('Light')
  })

  it('renders dark obsidian indicator in button variant', () => {
    const html = renderToStaticMarkup(React.createElement(ThemeSwitcher, { variant: 'button' }))
    expect(html).toContain('Dark Obsidian')
    expect(html).toContain('aria-label="Theme: Dark Obsidian"')
    expect(html).not.toContain('Light')
  })
})
