import { useEffect, useRef, useState, useMemo } from 'react'

export default function SearchableSelect({
  value,
  onChange,
  options = [],
  placeholder = 'Type to search or select…',
  disabled = false,
  clearable = true,
  loading = false,
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [focusIdx, setFocusIdx] = useState(0)
  const rootRef = useRef(null)
  const inputRef = useRef(null)
  const listRef = useRef(null)

  const selected = options.find((o) => o.value === value) || null

  const filtered = useMemo(() => {
    if (!query.trim()) return options
    const q = query.trim().toLowerCase()
    return options.filter((o) =>
      `${o.label || ''} ${o.value || ''} ${o.hint || ''} ${o.description || ''} ${o.keywords || ''}`
        .toLowerCase()
        .includes(q)
    )
  }, [options, query])

  useEffect(() => {
    function onDoc(e) {
      if (!rootRef.current) return
      if (!rootRef.current.contains(e.target)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  useEffect(() => {
    if (!open || !listRef.current) return
    const el = listRef.current.querySelector(`[data-idx="${focusIdx}"]`)
    if (el) el.scrollIntoView({ block: 'nearest' })
  }, [focusIdx, open])

  function handleKey(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) setOpen(true)
      else setFocusIdx((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) setOpen(true)
      else setFocusIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      if (open && filtered.length > 0) {
        e.preventDefault()
        const opt = filtered[focusIdx]
        if (opt && !opt.disabled) {
          onChange(opt.value)
          setQuery('')
          setOpen(false)
          inputRef.current?.blur()
        }
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
      setQuery('')
    }
  }

  function handleSelect(opt) {
    if (opt.disabled) return
    onChange(opt.value)
    setQuery('')
    setOpen(false)
  }

  function handleClear(e) {
    e.stopPropagation()
    onChange('')
    setQuery('')
    setOpen(true)
    inputRef.current?.focus()
  }

  return (
    <div ref={rootRef} className="searchable-select" style={{ position: 'relative', width: '100%' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '5px 8px',
          background: 'var(--bg, #0f172a)',
          border: open ? '1px solid var(--accent, #3b82f6)' : '1px solid var(--border, #334155)',
          borderRadius: 6,
          boxShadow: open ? '0 0 0 2px rgba(59, 130, 246, 0.2)' : 'none',
          transition: 'border-color 0.15s, box-shadow 0.15s',
          cursor: disabled ? 'not-allowed' : 'text',
          opacity: disabled ? 0.6 : 1,
        }}
        onClick={() => {
          if (!disabled) {
            setOpen(true)
            inputRef.current?.focus()
          }
        }}
      >
        {selected?.icon && !open && (
          <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            {selected.icon}
          </span>
        )}
        <span aria-hidden="true" style={{ color: 'var(--muted, #64748b)', fontSize: 13, flexShrink: 0 }}>
          🔍
        </span>
        <input
          ref={inputRef}
          type="text"
          disabled={disabled}
          value={open ? query : (selected ? selected.label : '')}
          onChange={(e) => {
            setQuery(e.target.value)
            setFocusIdx(0)
            if (!open) setOpen(true)
          }}
          onFocus={() => {
            setOpen(true)
            setQuery('')
          }}
          onKeyDown={handleKey}
          placeholder={selected ? selected.label : placeholder}
          aria-label={placeholder}
          aria-expanded={open}
          aria-haspopup="listbox"
          style={{
            flex: 1,
            minWidth: 0,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: 'var(--text, #f8fafc)',
            fontSize: 13,
            padding: '2px 0',
          }}
        />

        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
          {loading && <span className="spinner-sm" aria-hidden="true" style={{ width: 12, height: 12, borderWidth: 2 }} />}
          {clearable && (value || query) && !disabled && (
            <span
              role="button"
              tabIndex={0}
              onClick={handleClear}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleClear(e) }}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 18,
                height: 18,
                borderRadius: '50%',
                color: 'var(--muted, #94a3b8)',
                cursor: 'pointer',
                transition: 'background 0.15s, color 0.15s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = '#ef4444'; e.currentTarget.style.background = 'rgba(239, 68, 68, 0.15)' }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--muted, #94a3b8)'; e.currentTarget.style.background = 'transparent' }}
              title="Clear"
              aria-label="Clear"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </span>
          )}
          <span
            onClick={(e) => {
              e.stopPropagation()
              if (!disabled) {
                setOpen((o) => !o)
                if (!open) inputRef.current?.focus()
              }
            }}
            style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center' }}
          >
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
                color: 'var(--muted, #94a3b8)',
                transform: open ? 'rotate(180deg)' : 'none',
                transition: 'transform 0.2s ease',
              }}
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </span>
        </div>
      </div>

      {open && (
        <div
          ref={listRef}
          role="listbox"
          style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            left: 0,
            right: 0,
            zIndex: 100,
            background: 'var(--panel, #1e293b)',
            border: '1px solid var(--border, #334155)',
            borderRadius: 8,
            boxShadow: '0 12px 32px rgba(0,0,0,.5)',
            overflowY: 'auto',
            maxHeight: 280,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {filtered.length === 0 ? (
            <div style={{ padding: '12px 14px', color: 'var(--muted, #94a3b8)', fontSize: 12 }}>
              No matches for “{query}”
            </div>
          ) : (
            filtered.map((opt, idx) => (
              <div
                key={opt.value}
                data-idx={idx}
                role="option"
                aria-selected={value === opt.value}
                aria-disabled={!!opt.disabled}
                onClick={() => handleSelect(opt)}
                onMouseEnter={() => setFocusIdx(idx)}
                style={{
                  padding: '8px 12px',
                  cursor: opt.disabled ? 'not-allowed' : 'pointer',
                  background: idx === focusIdx ? 'var(--panel-2, #334155)' : (value === opt.value ? 'rgba(59, 130, 246, 0.1)' : 'transparent'),
                  color: opt.disabled ? 'var(--muted, #64748b)' : 'var(--text, #f8fafc)',
                  opacity: opt.disabled ? 0.6 : 1,
                  borderLeft: value === opt.value ? '3px solid var(--accent, #3b82f6)' : '3px solid transparent',
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
                    {opt.disabled && opt.disabledReason && <span style={{ color: 'var(--red, #ef4444)', marginLeft: 6, fontSize: 10 }}>— {opt.disabledReason}</span>}
                  </span>
                  {opt.badge && <span className="badge" style={{ fontSize: 10, padding: '1px 5px', flexShrink: 0 }}>{opt.badge}</span>}
                </div>
                {opt.hint && <span style={{ color: 'var(--muted, #94a3b8)', fontSize: 10, marginLeft: opt.icon ? 24 : 0 }}>{opt.hint}</span>}
              </div>
            ))
          )}
          {filtered.length > 6 && (
            <div style={{ padding: '5px 8px', borderTop: '1px solid var(--border, #334155)', color: 'var(--muted, #64748b)', fontSize: 10, textAlign: 'center' }}>
              {filtered.length} types available — scroll or continue typing to narrow down
            </div>
          )}
        </div>
      )}
    </div>
  )
}
