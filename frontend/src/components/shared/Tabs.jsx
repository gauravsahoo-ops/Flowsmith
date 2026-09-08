import React, { useRef } from 'react'

export default function Tabs({ tabs, value, onChange, className = 'tabs', ariaLabel = 'Tabs' }) {
  const refs = useRef([])

  function onKey(e, idx) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const dir = e.key === 'ArrowRight' ? 1 : -1
    const next = (idx + dir + tabs.length) % tabs.length
    onChange(tabs[next].id)
    refs.current[next]?.focus()
  }

  return (
    <div className={className} role="tablist" aria-label={ariaLabel}>
      {tabs.map((t, i) => (
        <button
          key={t.id}
          ref={(el) => (refs.current[i] = el)}
          role="tab"
          aria-selected={value === t.id}
          tabIndex={value === t.id ? 0 : -1}
          className={value === t.id ? 'active' : ''}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => onKey(e, i)}
        >
          {t.icon && (
            <span aria-hidden="true" style={{ marginRight: 6 }}>
              {t.icon}
            </span>
          )}
          {t.label}
        </button>
      ))}
    </div>
  )
}
