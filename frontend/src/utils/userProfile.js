/**
 * Dynamic Authenticated User Profile
 * Extracts authenticated user credentials safely with zero dummy mocks.
 * Checks cached user profile (from /auth/me or login), then decodes JWT payload,
 * strictly rejecting raw database user IDs (e.g. "4") from being used as names.
 */

export function getDynamicUser() {
  if (typeof window === 'undefined') {
    return { name: 'Operator', email: 'operator@flowsmith.local', initials: 'OP' }
  }

  try {
    // 1. Check cached user object (from /api/auth/me or login payload)
    const cachedRaw = localStorage.getItem('flowsmith_user')
    if (cachedRaw) {
      try {
        const u = JSON.parse(cachedRaw)
        if (u && typeof u === 'object') {
          const email = (u.email || '').trim()
          let name = (u.name || u.first_name || '').trim()
          if (!name && email && email.includes('@')) {
            name = email.split('@')[0]
          }
          if (name && !/^\d+$/.test(name)) {
            name = name.charAt(0).toUpperCase() + name.slice(1)
            const initials = (name.slice(0, 2) || 'OP').toUpperCase()
            return {
              name,
              email: email || `${name.toLowerCase()}@flowsmith.local`,
              initials,
            }
          }
        }
      } catch (err) { console.error('[flowsmith] utils/userProfile.js', err) }
    }

    // 2. Decode JWT access token
    const token = localStorage.getItem('mat_token')
    if (token && token.includes('.')) {
      const parts = token.split('.')
      if (parts.length >= 2) {
        const base64Url = parts[1]
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
        const payload = JSON.parse(decodeURIComponent(escape(atob(base64))))

        let email = typeof payload.email === 'string' ? payload.email.trim() : ''
        let name = typeof payload.name === 'string' ? payload.name.trim() : ''

        // If sub is NOT purely numeric (e.g. an email or alphanumeric username)
        if (!email && typeof payload.sub === 'string' && !/^\d+$/.test(payload.sub.trim())) {
          email = payload.sub.trim()
        }

        if (!name && email && email.includes('@')) {
          name = email.split('@')[0]
        }

        if (name && !/^\d+$/.test(name)) {
          name = name.charAt(0).toUpperCase() + name.slice(1)
          const initials = (name.slice(0, 2) || 'OP').toUpperCase()
          return {
            name,
            email: email || `${name.toLowerCase()}@flowsmith.local`,
            initials,
          }
        }
      }
    }
  } catch (err) {
    console.warn('Failed to parse dynamic user:', err)
  }

  return { name: 'Operator', email: 'operator@flowsmith.local', initials: 'OP' }
}

/**
 * Fetch fresh user profile from backend /api/auth/me and cache it.
 */
export async function syncUserProfile(api) {
  if (typeof window === 'undefined' || !api?.getMe) return null
  const token = localStorage.getItem('mat_token')
  if (!token) return null

  try {
    const data = await api.getMe()
    const user = data?.data || data
    if (user && user.email) {
      localStorage.setItem('flowsmith_user', JSON.stringify(user))
      window.dispatchEvent(new Event('flowsmith_user_updated'))
      return user
    }
  } catch {
    // Ignore 401 or network errors during sync
  }
  return null
}
