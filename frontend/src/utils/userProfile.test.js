import { describe, it, expect, beforeEach } from 'vitest'
import { getDynamicUser } from './userProfile'

// --- localStorage mock for Node test environment ---
let store = {}
const mockStorage = {
  getItem: (k) => store[k] ?? null,
  setItem: (k, v) => { store[k] = String(v) },
  removeItem: (k) => { delete store[k] },
  clear: () => { store = {} },
}
Object.defineProperty(globalThis, 'localStorage', { value: mockStorage, writable: true })
Object.defineProperty(globalThis, 'window', { value: globalThis, writable: true })

describe('userProfile', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('rejects purely numeric user IDs (like "4") as names or emails', () => {
    // Simulated token where sub is "4" and no email
    const fakeToken = `header.${btoa(JSON.stringify({ sub: '4', iat: 123456 }))}.sig`
    localStorage.setItem('mat_token', fakeToken)

    const user = getDynamicUser()
    expect(user.name).not.toBe('4')
    expect(user.email).not.toBe('4')
    expect(user.initials).not.toBe('4')
    expect(user.name).toBe('Operator')
    expect(user.email).toBe('operator@flowsmith.local')
    expect(user.initials).toBe('OP')
  })

  it('extracts real name and email from token when available', () => {
    const fakeToken = `header.${btoa(JSON.stringify({ sub: '4', email: 'gaurav@flowsmith.local' }))}.sig`
    localStorage.setItem('mat_token', fakeToken)

    const user = getDynamicUser()
    expect(user.name).toBe('Gaurav')
    expect(user.email).toBe('gaurav@flowsmith.local')
    expect(user.initials).toBe('GA')
  })

  it('prefers cached user profile from /auth/me when present', () => {
    localStorage.setItem('mat_token', `header.${btoa(JSON.stringify({ sub: '4' }))}.sig`)
    localStorage.setItem('flowsmith_user', JSON.stringify({ id: 4, email: 'admin@flowsmith.local', role: 'admin' }))

    const user = getDynamicUser()
    expect(user.name).toBe('Admin')
    expect(user.email).toBe('admin@flowsmith.local')
    expect(user.initials).toBe('AD')
  })
})
