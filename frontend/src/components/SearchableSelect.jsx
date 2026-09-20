import { useEffect, useRef, useState, useMemo } from 'react'

export default function SearchableSelect({ value, onChange, options, placeholder = 'Select…', disabled = false, clearable = true, loading = false }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [focusIdx, setFocusIdx] = useState(0)
  const rootRef = useRef(null)
  const inputRef = useRef(null)
  const listRef = useRef(null)

  const selected = options.find(o => o.value === value) || null

  const filtered = useMemo(() => {
    if (!query) return options
    const q = query.toLowerCase()
    return options.filter(o => `${o.label || ''} ${o.value || ''} ${o.hint || ''} ${o.description || ''} ${o.keywords || ''}`.toLowerCase().includes(q))
  }, [options, query])

  useEffect(() => {
    if (open) {
      setFocusIdx(0)
      setTimeout(() => inputRef.current?.focus(), 0)
    } else {
      setQuery('')
    }
  }, [open])

  useEffect(() => {
    function onDoc(e) {
      if (!rootRef.current) return
      if (!rootRef.current.contains(e.target)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  useEffect(() => {
    if (!open || !listRef.current) return
    const el = listRef.current.querySelector(`[data-idx="${focusIdx}"]`)
    if (el) el.scrollIntoView({ block: 'nearest' })
  }, [focusIdx, open])

  function handleKey(e) {
    if (!open) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
        e.preventDefault()
        setOpen(true)
      }
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setFocusIdx(i => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setFocusIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const opt = filtered[focusIdx]
      if (opt && !opt.disabled) {
        onChange(opt.value)
        setOpen(false)
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
    }
  }

  return (
    <div ref={rootRef} className="searchable-select" style={{ position: 'relative' }}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(o => !o)}
        onKeyDown={handleKey}
        aria-haspopup="listbox"
        aria-expanded={open}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          padding: '7px 9px',
          background: 'var(--bg)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          color: 'var(--text)',
          fontSize: 13,
          textAlign: 'left',
          cursor: disabled ? 'default' : 'pointer',
          opacity: disabled ? 0.6 : 1,
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, display: 'flex', alignItems: 'center', gap: 8 }}>
          {selected ? (
            <>
              {selected.icon && <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{selected.icon}</span>}
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selected.label}</span>
            </>
          ) : (
            <span style={{ color: 'var(--muted)' }}>{placeholder}</span>
          )}
        </span>
          <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0 }}>
            {loading && <span className="spinner-sm" aria-hidden="true" style={{ width: 12, height: 12, borderWidth: 2 }} />}
            {clearable && value && (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => { e.stopPropagation(); onChange('') }}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); onChange('') } }}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 18,
                  height: 18,
                  borderRadius: '50%',
                  color: 'var(--muted)',
                  cursor: 'pointer',
                  transition: 'background 0.15s, color 0.15s',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.color = '#ef4444'; e.currentTarget.style.background = 'rgba(239, 68, 68, 0.15)' }}
                onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--muted)'; e.currentTarget.style.background = 'transparent' }}
                title="Clear selection"
                aria-label="Clear selection"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </span>
            )}
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{
                color: 'var(--muted)',
                transform: open ? 'rotate(180deg)' : 'none',
                transition: 'transform 0.2s ease',
              }}
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </span>
        </button>

      {open && (
        <div
          role="listbox"
          style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            left: 0,
            right: 0,
            zIndex: 50,
            background: 'var(--panel)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            boxShadow: '0 12px 32px rgba(0,0,0,.4)',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            maxHeight: 280,
          }}
        >
          <div style={{ padding: 6, borderBottom: '1px solid var(--border)', flexShrink: 0, position: 'relative' }}>
            <span aria-hidden="true" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--muted)', fontSize: 12 }}>🔍</span>
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => { setQuery(e.target.value); setFocusIdx(0) }}
              onKeyDown={handleKey}
              placeholder="Search…"
              style={{ width: '100%', padding: '6px 8px 6px 26px', fontSize: 12 }}
              aria-label="Search options"
            />
          </div>
          <div
            ref={listRef}
            style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}
          >
            {filtered.length === 0 ? (
              <div style={{ padding: '10px 12px', color: 'var(--muted)', fontSize: 12 }}>No matches</div>
            ) : (
              filtered.map((opt, idx) => (
                <div
                  key={opt.value}
                  data-idx={idx}
                  role="option"
                  aria-selected={value === opt.value}
                  aria-disabled={!!opt.disabled}
                  onClick={() => {
                    if (opt.disabled) return
                    onChange(opt.value)
                    setOpen(false)
                  }}
                  style={{
                    padding: '7px 10px',
                    cursor: opt.disabled ? 'not-allowed' : 'pointer',
                    background: idx === focusIdx ? 'var(--panel-2)' : 'transparent',
                    color: opt.disabled ? 'var(--muted)' : 'var(--text)',
                    opacity: opt.disabled ? 0.6 : 1,
                    borderLeft: value === opt.value ? '2px solid var(--accent)' : '2px solid transparent',
                    fontSize: 12,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 2,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%' }}>
                    {opt.icon && <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{opt.icon}</span>}
                    <span style={{ fontWeight: value === opt.value ? 600 : 400, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {opt.label}
                      {opt.disabled && opt.disabledReason && <span style={{ color: 'var(--red)', marginLeft: 6, fontSize: 10 }}>— {opt.disabledReason}</span>}
                    </span>
                    {opt.badge && <span className="badge" style={{ fontSize: 10, padding: '1px 5px', flexShrink: 0 }}>{opt.badge}</span>}
                  </div>
                  {opt.hint && <span style={{ color: 'var(--muted)', fontSize: 10, marginLeft: opt.icon ? 24 : 0 }}>{opt.hint}</span>}
                </div>
              ))
            )}
          </div>
          {filtered.length > 7 && <div style={{ padding: '4px 8px', borderTop: '1px solid var(--border)', color: 'var(--muted)', fontSize: 10, textAlign: 'center' }}>{filtered.length} options — scroll or type to filter</div>}
        </div>
      )}
    </div>
  )
}
