import React, { useMemo, useState } from 'react'

import { getBrandLogo } from '../utils/brandLogoResolver'

function fallbackInitials(label) {
  const words = String(label || '')
    .replace(/\b(trigger|connector|node|api|integration|app|cloud)\b/gi, ' ')
    .replace(/[^a-zA-Z0-9]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
  if (!words.length) return 'FS'
  if (words.length > 1) return (words[0][0] + words[1][0]).toUpperCase()
  return words[0].slice(0, 2).toUpperCase()
}

function hashAccent(label) {
  const palette = ['#6b8afd', '#4aa8d8', '#48b7a2', '#d0a44c', '#d2768b', '#9b7ad6', '#7da36b']
  let hash = 0
  const value = String(label || '')
  for (let i = 0; i < value.length; i += 1) hash = (hash * 31 + value.charCodeAt(i)) | 0
  return palette[Math.abs(hash) % palette.length]
}

export function BrandMonogram({ label, size = 32, className = '', style }) {
  const initials = useMemo(() => fallbackInitials(label), [label])
  const accent = useMemo(() => hashAccent(label), [label])
  return (
    <span
      className={`fs-brand-mark fs-brand-mark--monogram ${className}`.trim()}
      style={{ width: size, height: size, '--fs-brand-accent': accent, ...style }}
      title={label}
      aria-hidden="true"
    >
      <span className="fs-brand-monogram-glyph" style={{ fontSize: Math.max(8, Math.round(size * (initials.length > 1 ? 0.34 : 0.42))) }}>
        {initials}
      </span>
    </span>
  )
}

export function BrandLogo({ type, name, icon, size = 32, className = '', style }) {
  const resolved = getBrandLogo({ type, name, icon })
  const [failed, setFailed] = useState(false)
  if (!resolved || failed) {
    return <BrandMonogram label={name || type || resolved?.entry?.label || 'Flowsmith'} size={size} className={className} style={style} />
  }
  const { entry, key } = resolved
  const tone = entry.tone === 'dark' ? 'dark' : 'light'
  return (
    <span
      className={`fs-brand-mark fs-brand-mark--${tone} ${className}`.trim()}
      data-brand-key={key}
      data-brand-kind={entry.kind || 'iconify'}
      style={{ width: size, height: size, '--fs-brand-accent': entry.color || '#6b8afd', ...style }}
      title={entry.label || name || type}
      aria-hidden="true"
    >
      <img
        src={entry.src}
        alt=""
        draggable="false"
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
      />
    </span>
  )
}

export default BrandLogo
