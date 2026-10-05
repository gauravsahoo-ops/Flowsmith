import { describe, it, expect, beforeEach, vi } from 'vitest'
import { getSavedTheme, getEffectiveTheme, setTheme, applyTheme, initTheme } from './theme'

let store = {}
const mockStorage = {
  getItem: (k) => store[k] ?? null,
  setItem: (k, v) => { store[k] = String(v) },
  removeItem: (k) => { delete store[k] },
  clear: () => { store = {} },
}

let docAttrs = {}
const mockDocument = {
  documentElement: {
    setAttribute: (k, v) => { docAttrs[k] = String(v) },
    getAttribute: (k) => docAttrs[k] ?? null,
    removeAttribute: (k) => { delete docAttrs[k] },
    style: {},
  },
}

Object.defineProperty(globalThis, 'localStorage', { value: mockStorage, writable: true })
Object.defineProperty(globalThis, 'document', { value: mockDocument, writable: true })

if (!globalThis.window) {
  Object.defineProperty(globalThis, 'window', { value: globalThis, writable: true })
}
if (!globalThis.window.dispatchEvent) {
  globalThis.window.dispatchEvent = vi.fn()
}

describe('Theme Manager', () => {
  beforeEach(() => {
    localStorage.clear()
    docAttrs = {}
  })

  it('defaults to dark when localStorage is empty', () => {
    expect(getSavedTheme()).toBe('dark')
    expect(getEffectiveTheme()).toBe('dark')
  })

  it('exclusively enforces dark mode', () => {
    setTheme('light')
    expect(getSavedTheme()).toBe('dark')
    expect(getEffectiveTheme()).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme-setting')).toBe('dark')
  })

  it('initializes dark theme on page load', () => {
    initTheme()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('applies dark theme directly using applyTheme', () => {
    applyTheme()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })
})
