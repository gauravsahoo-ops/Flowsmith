/**
 * Flowsmith Enterprise Theme Manager
 * Exclusively enforces deep obsidian dark mode.
 */

export function getSavedTheme() {
  return 'dark'
}

export function getEffectiveTheme() {
  return 'dark'
}

export function applyTheme() {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', 'dark')
    document.documentElement.setAttribute('data-theme-setting', 'dark')
    document.documentElement.style.colorScheme = 'dark'
  }
}

export function setTheme() {
  applyTheme()
  if (typeof window !== 'undefined' && window.dispatchEvent) {
    window.dispatchEvent(
      new CustomEvent('flowsmith_theme_changed', {
        detail: { theme: 'dark', effective: 'dark' },
      })
    )
  }
}

export function initTheme() {
  applyTheme()
}
