import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { isTrustedOAuthOrigin } from './oauthOrigins'

describe('isTrustedOAuthOrigin', () => {
  let originalWindow

  beforeEach(() => {
    originalWindow = globalThis.window
    globalThis.window = {
      location: {
        origin: 'http://localhost:5173',
        hostname: 'localhost',
        port: '5173',
      },
    }
  })

  afterEach(() => {
    if (originalWindow === undefined) {
      delete globalThis.window
    } else {
      globalThis.window = originalWindow
    }
  })

  it('rejects null, empty, and invalid origins', () => {
    expect(isTrustedOAuthOrigin(null)).toBe(false)
    expect(isTrustedOAuthOrigin('')).toBe(false)
    expect(isTrustedOAuthOrigin('null')).toBe(false)
    expect(isTrustedOAuthOrigin(undefined)).toBe(false)
    expect(isTrustedOAuthOrigin('not-a-url')).toBe(false)
  })

  it('trusts same-origin messages', () => {
    expect(isTrustedOAuthOrigin('http://localhost:5173')).toBe(true)
  })

  it('trusts loopback cross-talk between localhost and 127.0.0.1 on dev ports', () => {
    // Current is localhost:5173
    expect(isTrustedOAuthOrigin('http://127.0.0.1:5173')).toBe(true)
    expect(isTrustedOAuthOrigin('http://localhost:8000')).toBe(true)
    expect(isTrustedOAuthOrigin('http://127.0.0.1:8000')).toBe(true)
    expect(isTrustedOAuthOrigin('http://localhost:5174')).toBe(true)
    expect(isTrustedOAuthOrigin('http://127.0.0.1:5174')).toBe(true)
    expect(isTrustedOAuthOrigin('http://localhost:3000')).toBe(true)
    expect(isTrustedOAuthOrigin('http://127.0.0.1:4173')).toBe(true)
  })

  it('rejects malicious external origins', () => {
    expect(isTrustedOAuthOrigin('https://evil.com')).toBe(false)
    expect(isTrustedOAuthOrigin('http://attacker.local')).toBe(false)
    expect(isTrustedOAuthOrigin('https://oauth-phishing.com')).toBe(false)
  })
})
