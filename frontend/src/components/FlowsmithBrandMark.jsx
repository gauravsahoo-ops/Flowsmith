import { memo } from 'react'

/**
 * FlowsmithBrandMark — official brand mark for Flowsmith.
 * Blends the letter 'F' with connected workflow execution nodes and speed geometry.
 *
 * @param {number} size - pixel dimension (width & height)
 * @param {'badge' | 'glyph'} variant - 'badge' includes gradient rounded tile; 'glyph' is pure icon
 * @param {boolean} glow - whether to render drop-shadow glow
 * @param {string} className - extra CSS classes
 */
function FlowsmithBrandMark({
  size = 24,
  variant = 'badge',
  glow = false,
  className = '',
  style = {},
}) {
  if (variant === 'glyph') {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 48 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        style={{ display: 'block', flexShrink: 0, ...style }}
        aria-hidden="true"
      >
        <path
          d="M14 11h18c1.66 0 2.58 1.93 1.52 3.21L28.8 20H20v3h6.5c1.66 0 2.58 1.93 1.52 3.21L24.8 30H18v7c0 1.1-.9 2-2 2s-2-.9-2-2V13c0-1.1.9-2 2-2z"
          fill="currentColor"
        />
        <circle cx="28.5" cy="20" r="2.2" fill="#38bdf8" />
        <circle cx="24.5" cy="30" r="2.2" fill="#38bdf8" />
      </svg>
    )
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={{ display: 'block', flexShrink: 0, borderRadius: Math.round(size * 0.28), ...style }}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="fs-brand-bg" x1="2" y1="2" x2="46" y2="46" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="45%" stopColor="#6366f1" />
          <stop offset="100%" stopColor="#8b5cf6" />
        </linearGradient>
        {glow && (
          <filter id="fs-brand-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="3" stdDeviation="5" floodColor="#6366f1" floodOpacity="0.45" />
          </filter>
        )}
      </defs>
      <rect
        width="48"
        height="48"
        rx="13"
        fill="url(#fs-brand-bg)"
        filter={glow ? 'url(#fs-brand-glow)' : undefined}
      />
      <path
        d="M14 11h18c1.66 0 2.58 1.93 1.52 3.21L28.8 20H20v3h6.5c1.66 0 2.58 1.93 1.52 3.21L24.8 30H18v7c0 1.1-.9 2-2 2s-2-.9-2-2V13c0-1.1.9-2 2-2z"
        fill="#ffffff"
      />
      <circle cx="28.5" cy="20" r="2.2" fill="#38bdf8" />
      <circle cx="24.5" cy="30" r="2.2" fill="#38bdf8" />
    </svg>
  )
}

export default memo(FlowsmithBrandMark)
