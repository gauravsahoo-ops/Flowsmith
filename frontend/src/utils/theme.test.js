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

  it('persists and applies light theme', () => {
    setTheme('light')
    expect(getSavedTheme()).toBe('light')
    expect(getEffectiveTheme()).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(document.documentElement.getAttribute('data-theme-setting')).toBe('light')
  })

  it('resolves system theme matching prefers-color-scheme', () => {
    globalThis.window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: query.includes('light'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))

    setTheme('system')
    expect(getSavedTheme()).toBe('system')
    expect(getEffectiveTheme('system')).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(document.documentElement.getAttribute('data-theme-setting')).toBe('system')
  })

  it('initializes theme correctly on page load', () => {
    localStorage.setItem('flowsmith_theme', 'light')
    initTheme()
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('applies theme directly using applyTheme', () => {
    applyTheme('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    applyTheme('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })
})
