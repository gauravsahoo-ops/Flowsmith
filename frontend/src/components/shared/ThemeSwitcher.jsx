import { useEffect, useState } from 'react'
import { getSavedTheme, setTheme } from '../../utils/theme'

export default function ThemeSwitcher({ variant = 'segmented', className = '' }) {
  const [currentTheme, setCurrentTheme] = useState(() => getSavedTheme())

  useEffect(() => {
    const onThemeChange = (e) => {
      setCurrentTheme(e.detail?.theme || getSavedTheme())
    }
    window.addEventListener('flowsmith_theme_changed', onThemeChange)
    return () => window.removeEventListener('flowsmith_theme_changed', onThemeChange)
  }, [])

  const options = [
    {
      id: 'dark',
      label: 'Dark',
      title: 'Dark Obsidian theme',
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      ),
    },
    {
      id: 'light',
      label: 'Light',
      title: 'Crisp Light theme',
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="5" />
          <line x1="12" y1="1" x2="12" y2="3" />
          <line x1="12" y1="21" x2="12" y2="23" />
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
          <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
          <line x1="1" y1="12" x2="3" y2="12" />
          <line x1="21" y1="12" x2="23" y2="12" />
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
          <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
        </svg>
      ),
    },
    {
      id: 'system',
      label: 'System',
      title: 'Sync with operating system theme',
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
      ),
    },
  ]

  if (variant === 'button') {
    // Single compact toggle button that cycles: Dark -> Light -> System -> Dark
    const cycleNext = () => {
      const idx = options.findIndex((o) => o.id === currentTheme)
      const next = options[(idx + 1) % options.length].id
      setTheme(next)
    }
    const currentOpt = options.find((o) => o.id === currentTheme) || options[0]

    return (
      <button
        type="button"
        className={`theme-toggle-btn ${className}`}
        onClick={cycleNext}
        title={`Current: ${currentOpt.label} mode. Click to cycle theme.`}
        aria-label={`Theme: ${currentOpt.label}. Click to switch theme.`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 32,
          height: 32,
          padding: 0,
          borderRadius: 8,
          background: 'var(--panel-2)',
          border: '1px solid var(--border)',
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          transition: 'all 0.16s var(--ease-spring)',
        }}
      >
        {currentOpt.icon}
      </button>
    )
  }

  // Default: Segmented control
  return (
    <div
      className={`theme-segmented-control ${className}`}
      role="radiogroup"
      aria-label="Theme selector"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '3px',
        borderRadius: '999px',
        background: 'var(--panel-2)',
        border: '1px solid var(--border)',
        gap: '2px',
      }}
    >
      {options.map((opt) => {
        const active = currentTheme === opt.id
        return (
          <button
            key={opt.id}
            type="button"
            role="radio"
            aria-checked={active}
            title={opt.title}
            onClick={() => setTheme(opt.id)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '4px 10px',
              borderRadius: '999px',
              fontSize: '12px',
              fontWeight: active ? 600 : 500,
              color: active ? 'var(--text)' : 'var(--text-dim)',
              background: active ? 'var(--panel)' : 'transparent',
              border: active ? '1px solid var(--border-strong)' : '1px solid transparent',
              boxShadow: active ? 'var(--shadow-sm)' : 'none',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            {opt.icon}
            <span>{opt.label}</span>
          </button>
        )
      })}
    </div>
  )
}
