import { describe, it, expect, beforeEach } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ThemeSwitcher from './ThemeSwitcher'

let store = {}
const mockStorage = {
  getItem: (k) => store[k] ?? null,
  setItem: (k, v) => { store[k] = String(v) },
  removeItem: (k) => { delete store[k] },
  clear: () => { store = {} },
}

Object.defineProperty(globalThis, 'localStorage', { value: mockStorage, writable: true })
if (!globalThis.window) {
  Object.defineProperty(globalThis, 'window', { value: globalThis, writable: true })
}
if (!globalThis.window.addEventListener) {
  globalThis.window.addEventListener = () => {}
  globalThis.window.removeEventListener = () => {}
}

describe('ThemeSwitcher Component', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders all 3 theme options in segmented mode', () => {
    const html = renderToStaticMarkup(React.createElement(ThemeSwitcher, { variant: 'segmented' }))
    expect(html).toContain('Dark')
    expect(html).toContain('Light')
    expect(html).toContain('System')
    expect(html).toContain('role="radiogroup"')
  })

  it('renders button toggle variant with proper accessibility label', () => {
    const html = renderToStaticMarkup(React.createElement(ThemeSwitcher, { variant: 'button' }))
    expect(html).toContain('theme-toggle-btn')
    expect(html).toContain('aria-label=')
    expect(html).toContain('svg')
  })
})
