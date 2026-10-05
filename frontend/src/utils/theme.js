/**
 * Flowsmith Enterprise Theme Manager
 * Supports 'dark' | 'light' | 'system' themes with real-time OS preference detection,
 * localStorage persistence, and custom event broadcasting.
 */

export function getSavedTheme() {
  try {
    return localStorage.getItem('flowsmith_theme') || 'dark'
  } catch {
    return 'dark'
  }
}

export function getEffectiveTheme(savedTheme = getSavedTheme()) {
  if (savedTheme === 'system') {
    if (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      return 'light'
    }
    return 'dark'
  }
  return savedTheme === 'light' ? 'light' : 'dark'
}

export function applyTheme(theme = getSavedTheme()) {
  const effective = getEffectiveTheme(theme)
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', effective)
    document.documentElement.setAttribute('data-theme-setting', theme)
    // Style color-scheme for browser native widgets (inputs, scrollbars, dialogs)
    document.documentElement.style.colorScheme = effective
  }
}

export function setTheme(theme) {
  try {
    localStorage.setItem('flowsmith_theme', theme)
  } catch {}
  applyTheme(theme)
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('flowsmith_theme_changed', {
        detail: { theme, effective: getEffectiveTheme(theme) },
      })
    )
  }
}

export function initTheme() {
  const saved = getSavedTheme()
  applyTheme(saved)

  if (typeof window !== 'undefined' && window.matchMedia) {
    const media = window.matchMedia('(prefers-color-scheme: light)')
    const listener = () => {
      if (getSavedTheme() === 'system') {
        applyTheme('system')
        window.dispatchEvent(
          new CustomEvent('flowsmith_theme_changed', {
            detail: { theme: 'system', effective: getEffectiveTheme('system') },
          })
        )
      }
    }
    if (media.addEventListener) {
      media.addEventListener('change', listener)
    } else if (media.addListener) {
      media.addListener(listener)
    }
  }
}
