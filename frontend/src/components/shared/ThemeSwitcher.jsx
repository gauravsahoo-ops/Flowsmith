export default function ThemeSwitcher({ variant = 'segmented', className = '' }) {
  return (
    <div
      className={`theme-indicator ${className}`}
      role="status"
      aria-label="Theme: Dark Obsidian"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: variant === 'button' ? '6px 10px' : '4px 10px',
        borderRadius: '6px',
        background: 'var(--panel-2, #111827)',
        border: '1px solid var(--border, rgba(255, 255, 255, 0.08))',
        fontSize: '12px',
        fontWeight: 600,
        color: 'var(--text, #f1f5f9)',
      }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
      </svg>
      <span>Dark Obsidian</span>
    </div>
  )
}
