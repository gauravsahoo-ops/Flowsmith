import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export function SearchIcon({ size = 15, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

export function ClearIcon({ size = 11, color = '#ffffff' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ display: 'block', pointerEvents: 'none', flexShrink: 0 }}
      aria-hidden="true"
    >
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
  )
}

export function StepsIcon({ size = 14, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
      <path d="M10 6.5h4" />
      <path d="M17.5 10v4" />
    </svg>
  )
}

export function ErrorsIcon({ size = 14, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

export function RecordsIcon({ size = 14, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  )
}

export function ApiRequestsIcon({ size = 14, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  )
}

export function PayloadsIcon({ size = 14, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 7c0-1.1.9-2 2-2h1a2 2 0 0 1 2 2v2a2 2 0 0 0 2 2 2 2 0 0 0-2 2v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2" />
      <path d="M20 7c0-1.1-.9-2-2-2h-1a2 2 0 0 0-2 2v2a2 2 0 0 1-2 2 2 2 0 0 1 2 2v2a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2" />
    </svg>
  )
}

export function MetadataIcon({ size = 14, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z" />
      <circle cx="7" cy="7" r="1.5" fill="currentColor" />
    </svg>
  )
}

function getCategoryIcon(catId, size = 13, color = 'currentColor') {
  switch (catId) {
    case 'steps':
      return <StepsIcon size={size} color={color} />
    case 'errors':
      return <ErrorsIcon size={size} color={color} />
    case 'records':
      return <RecordsIcon size={size} color={color} />
    case 'api_requests':
      return <ApiRequestsIcon size={size} color={color} />
    case 'payloads':
      return <PayloadsIcon size={size} color={color} />
    case 'metadata':
      return <MetadataIcon size={size} color={color} />
    default:
      return <SearchIcon size={size} color={color} />
  }
}

const CATEGORY_TABS = [
  { id: 'all', label: 'All Details', IconComponent: SearchIcon },
  { id: 'steps', label: 'Steps & Nodes', IconComponent: StepsIcon },
  { id: 'errors', label: 'Errors & Logs', IconComponent: ErrorsIcon },
  { id: 'records', label: 'Records & Fields', IconComponent: RecordsIcon },
  { id: 'api_requests', label: 'API Calls', IconComponent: ApiRequestsIcon },
  { id: 'payloads', label: 'Payloads & JSON', IconComponent: PayloadsIcon },
  { id: 'metadata', label: 'Metadata', IconComponent: MetadataIcon },
]

const CATEGORY_COLORS = {
  steps: { bg: 'rgba(99, 102, 241, 0.12)', text: '#a5b4fc', border: 'rgba(99, 102, 241, 0.3)' },
  errors: { bg: 'rgba(239, 68, 68, 0.12)', text: '#fca5a5', border: 'rgba(239, 68, 68, 0.3)' },
  records: { bg: 'rgba(16, 185, 129, 0.12)', text: '#6ee7b7', border: 'rgba(16, 185, 129, 0.3)' },
  api_requests: { bg: 'rgba(56, 189, 248, 0.12)', text: '#7dd3fc', border: 'rgba(56, 189, 248, 0.3)' },
  payloads: { bg: 'rgba(245, 158, 11, 0.12)', text: '#fcd34d', border: 'rgba(245, 158, 11, 0.3)' },
  metadata: { bg: 'rgba(168, 85, 247, 0.12)', text: '#d8b4fe', border: 'rgba(168, 85, 247, 0.3)' },
}

const DEFAULT_POPULAR_QUERIES = [
  'failed',
  'salesforce',
  'POST',
  '404',
  'timeout',
  'email',
  'records_read',
]

function fmtDropdownTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return String(iso)
  }
}

export function HighlightMatch({ text, query }) {
  if (!text) return null
  if (!query || !query.trim()) return <>{text}</>
  const str = String(text)
  const q = query.trim().toLowerCase()

  // 1. Direct exact substring match
  const idx = str.toLowerCase().indexOf(q)
  if (idx !== -1) {
    return (
      <>
        {str.slice(0, idx)}
        <mark
          style={{
            background: 'rgba(99, 102, 241, 0.28)',
            color: '#e0e7ff',
            padding: '1px 4px',
            borderRadius: 3,
            fontWeight: 600,
            border: '1px solid rgba(99, 102, 241, 0.45)',
          }}
        >
          {str.slice(idx, idx + q.length)}
        </mark>
        <HighlightMatch text={str.slice(idx + q.length)} query={query} />
      </>
    )
  }

  // 2. Multi-token match (supports dates like "October 21st 2026" matching "2026-10-21" or "October 21")
  const rawTokens = q
    .split(/[\s,]+/)
    .map((t) => t.replace(/(st|nd|rd|th)$/i, ''))
    .filter((t) => t.length >= 2)

  if (!rawTokens.length) return <>{str}</>

  // Escape special regex chars in tokens
  const escaped = rawTokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
  const parts = str.split(pattern)
  if (parts.length <= 1) return <>{str}</>

  return (
    <>
      {parts.map((part, i) => {
        const isMatch = rawTokens.some((t) => t.toLowerCase() === part.toLowerCase())
        if (isMatch) {
          return (
            <mark
              key={i}
              style={{
                background: 'rgba(99, 102, 241, 0.28)',
                color: '#e0e7ff',
                padding: '1px 4px',
                borderRadius: 3,
                fontWeight: 600,
                border: '1px solid rgba(99, 102, 241, 0.45)',
              }}
            >
              {part}
            </mark>
          )
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}

export default function UniversalExecutionSearch({
  value = '',
  onChange,
  onSearch,
  category = 'all',
  onCategoryChange,
  facets = {},
  placeholder = "Search execution details, steps, errors, payloads, records... (Press / to focus)",
  autoFocus = false,
}) {
  const navigate = useNavigate()
  const [query, setQuery] = useState(value)
  const [debouncedQuery, setDebouncedQuery] = useState(value)
  const [activeCategory, setActiveCategory] = useState(category)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [facetCounts, setFacetCounts] = useState(facets)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const [recentSearches, setRecentSearches] = useState(() => {
    try {
      const saved = localStorage.getItem('flowsmith_recent_execution_searches')
      return saved ? JSON.parse(saved) : DEFAULT_POPULAR_QUERIES
    } catch {
      return DEFAULT_POPULAR_QUERIES
    }
  })

  const containerRef = useRef(null)
  const inputRef = useRef(null)
  const abortCtrlRef = useRef(null)

  // Keep internal state in sync with external value
  useEffect(() => {
    setQuery(value)
  }, [value])

  useEffect(() => {
    setActiveCategory(category)
  }, [category])

  useEffect(() => {
    if (facets && Object.keys(facets).length) {
      setFacetCounts(facets)
    }
  }, [facets])

  // Global keyboard shortcut: '/' or 'Ctrl+K'
  useEffect(() => {
    function handleKeyDown(e) {
      if ((e.key === '/' || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) && document.activeElement !== inputRef.current) {
        const tag = document.activeElement?.tagName?.toLowerCase()
        if (tag !== 'input' && tag !== 'textarea') {
          e.preventDefault()
          inputRef.current?.focus()
          inputRef.current?.select()
          setDropdownOpen(true)
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Debounce query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query)
    }, 250)
    return () => clearTimeout(timer)
  }, [query])

  // Fetch instant autocomplete / search occurrences
  const fetchLiveResults = useCallback(async (q, cat) => {
    if (!q || !q.trim()) {
      setResults([])
      setTotalCount(0)
      setLoading(false)
      return
    }

    abortCtrlRef.current?.abort()
    const ctrl = new AbortController()
    abortCtrlRef.current = ctrl
    setLoading(true)

    try {
      const res = await api.universalSearchExecutions(
        {
          q: q.trim(),
          category: cat || 'all',
          pageSize: 8,
        },
        { signal: ctrl.signal }
      )

      if (res && Array.isArray(res.items)) {
        setResults(res.items)
        setTotalCount(res.total ?? res.items.length)
        if (res.facets) {
          setFacetCounts(res.facets)
        }
      } else if (Array.isArray(res)) {
        setResults(res)
        setTotalCount(res.length)
      } else {
        setResults([])
        setTotalCount(0)
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setResults([])
        setTotalCount(0)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (dropdownOpen && debouncedQuery && debouncedQuery.trim()) {
      fetchLiveResults(debouncedQuery, activeCategory)
    }
  }, [debouncedQuery, activeCategory, dropdownOpen, fetchLiveResults])

  // Click outside listener to close dropdown
  useEffect(() => {
    function handleClickOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function saveRecentSearch(term) {
    if (!term || !term.trim()) return
    const clean = term.trim()
    try {
      const existing = recentSearches.filter((s) => s.toLowerCase() !== clean.toLowerCase())
      const updated = [clean, ...existing].slice(0, 8)
      setRecentSearches(updated)
      localStorage.setItem('flowsmith_recent_execution_searches', JSON.stringify(updated))
    } catch {
      // Ignore storage errors
    }
  }

  function handleInputChange(e) {
    const val = e.target.value
    setQuery(val)
    setSelectedIndex(-1)
    setDropdownOpen(true)
    onChange?.(val)
  }

  function handleSubmitSearch(overrideQuery) {
    const finalQuery = (overrideQuery ?? query).trim()
    saveRecentSearch(finalQuery)
    setDropdownOpen(false)
    onSearch?.(finalQuery, activeCategory)
  }

  function handleClear() {
    setQuery('')
    setResults([])
    setTotalCount(0)
    setSelectedIndex(-1)
    onChange?.('')
    onSearch?.('', activeCategory)
    inputRef.current?.focus()
  }

  function handleSelectOccurrence(item) {
    saveRecentSearch(query)
    setDropdownOpen(false)
    if (item.url) {
      navigate(item.url)
    } else {
      navigate(`/executions/${item.execution_id}`)
    }
  }

  function handleCategoryClick(catId) {
    setActiveCategory(catId)
    onCategoryChange?.(catId)
    if (query && query.trim()) {
      fetchLiveResults(query.trim(), catId)
      onSearch?.(query.trim(), catId)
    }
  }

  function handleKeyDown(e) {
    if (!dropdownOpen) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        setDropdownOpen(true)
      }
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((prev) => (prev < results.length - 1 ? prev + 1 : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : results.length - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (selectedIndex >= 0 && selectedIndex < results.length) {
        handleSelectOccurrence(results[selectedIndex])
      } else {
        handleSubmitSearch()
      }
    } else if (e.key === 'Escape') {
      setDropdownOpen(false)
      inputRef.current?.blur()
    }
  }

  return (
    <div
      ref={containerRef}
      className="universal-search-container"
      style={{
        width: '100%',
        position: 'relative',
        marginBottom: 16,
      }}
    >
      {/* Search Input Bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          background: 'rgba(15, 20, 31, 0.92)',
          border: dropdownOpen ? '1px solid rgba(129, 140, 248, 0.65)' : '1px solid rgba(255, 255, 255, 0.12)',
          boxShadow: dropdownOpen
            ? '0 0 0 3px rgba(99, 102, 241, 0.2), 0 8px 24px rgba(0, 0, 0, 0.45)'
            : '0 4px 14px rgba(0, 0, 0, 0.25)',
          borderRadius: 9999,
          padding: '3px 6px 3px 16px',
          minHeight: 42,
          transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
          backdropFilter: 'blur(20px)',
        }}
      >
        {/* Left Search Icon */}
        <div style={{ display: 'flex', alignItems: 'center', color: dropdownOpen ? '#818cf8' : '#94a3b8', marginRight: 10, flexShrink: 0 }}>
          {loading ? (
            <span className="spinner-sm" style={{ width: 15, height: 15, borderTopColor: '#818cf8' }} />
          ) : (
            <SearchIcon size={16} color={dropdownOpen ? '#818cf8' : '#94a3b8'} />
          )}
        </div>

        {/* Input */}
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleInputChange}
          onFocus={() => setDropdownOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          autoFocus={autoFocus}
          aria-label="Universal Execution Search"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck="false"
          style={{
            flex: 1,
            minWidth: 0,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            boxShadow: 'none',
            WebkitAppearance: 'none',
            appearance: 'none',
            color: '#f8fafc',
            fontSize: 13.5,
            padding: '8px 10px 8px 4px',
            fontFamily: 'inherit',
          }}
        />

        {/* Clear Button (Visible 'X' cross sign) */}
        {query && (
          <button
            type="button"
            className="universal-search-clear-btn"
            onClick={handleClear}
            title="Clear search query"
            aria-label="Clear search"
          >
            <ClearIcon size={11} color="#ffffff" />
          </button>
        )}

        {/* Search Submit Button */}
        <button
          type="button"
          onClick={() => handleSubmitSearch()}
          title="Search execution logs"
          style={{
            background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.28) 0%, rgba(79, 70, 229, 0.38) 100%)',
            border: '1px solid rgba(99, 102, 241, 0.45)',
            color: '#e0e7ff',
            padding: '6px 14px',
            borderRadius: 9999,
            cursor: 'pointer',
            fontSize: 12.5,
            fontWeight: 600,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            transition: 'all 0.15s ease',
            flexShrink: 0,
            marginLeft: 2,
            marginRight: 2,
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.1)',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'linear-gradient(135deg, rgba(99, 102, 241, 0.45) 0%, rgba(79, 70, 229, 0.55) 100%)'
            e.currentTarget.style.borderColor = 'rgba(129, 140, 248, 0.75)'
            e.currentTarget.style.color = '#ffffff'
            e.currentTarget.style.boxShadow = '0 0 12px rgba(99, 102, 241, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.2)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'linear-gradient(135deg, rgba(99, 102, 241, 0.28) 0%, rgba(79, 70, 229, 0.38) 100%)'
            e.currentTarget.style.borderColor = 'rgba(99, 102, 241, 0.45)'
            e.currentTarget.style.color = '#e0e7ff'
            e.currentTarget.style.boxShadow = '0 2px 8px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.1)'
          }}
        >
          <SearchIcon size={13} color="currentColor" />
          <span>Search</span>
        </button>
      </div>

      {/* Category Chips Bar */}
      <div
        className="universal-category-chips"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          overflowX: 'auto',
          padding: '8px 4px 2px',
          scrollbarWidth: 'none',
        }}
      >
        {CATEGORY_TABS.map((tab) => {
          const isActive = activeCategory === tab.id
          const count = facetCounts[tab.id]
          const TabIcon = tab.IconComponent
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => handleCategoryClick(tab.id)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '4px 11px',
                borderRadius: 9999,
                fontSize: 11.5,
                fontWeight: isActive ? 600 : 500,
                color: isActive ? '#ffffff' : '#94a3b8',
                background: isActive ? 'rgba(99, 102, 241, 0.22)' : 'rgba(255, 255, 255, 0.03)',
                border: isActive ? '1px solid rgba(99, 102, 241, 0.5)' : '1px solid rgba(255, 255, 255, 0.06)',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                transition: 'all 0.15s ease',
              }}
            >
              <TabIcon size={12} color={isActive ? '#818cf8' : '#94a3b8'} />
              <span>{tab.label}</span>
              {typeof count === 'number' && count > 0 && (
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    padding: '1px 5px',
                    borderRadius: 8,
                    background: isActive ? 'rgba(99, 102, 241, 0.45)' : 'rgba(255, 255, 255, 0.08)',
                    color: isActive ? '#ffffff' : '#cbd5e1',
                  }}
                >
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Autocomplete Dropdown Popover */}
      {dropdownOpen && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: 6,
            background: 'rgba(15, 20, 31, 0.96)',
            border: '1px solid rgba(255, 255, 255, 0.12)',
            borderRadius: 14,
            boxShadow: '0 20px 45px -10px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.05)',
            backdropFilter: 'blur(28px)',
            zIndex: 1000,
            overflow: 'hidden',
            maxHeight: 460,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* Recent Searches & Suggested Filters */}
          {!query.trim() && (
            <div style={{ padding: '12px 16px' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                Recent Searches & Suggested Filters
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {recentSearches.map((term, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      setQuery(term)
                      handleSubmitSearch(term)
                    }}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                      padding: '5px 10px',
                      borderRadius: 8,
                      fontSize: 12,
                      color: '#cbd5e1',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid rgba(255, 255, 255, 0.08)',
                      cursor: 'pointer',
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#818cf8" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <polyline points="12 6 12 12 16 14" />
                    </svg>
                    <span>{term}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Results List */}
          {query.trim() && (
            <div style={{ overflowY: 'auto', flex: 1, padding: '4px 0' }}>
              {loading && results.length === 0 ? (
                <div style={{ padding: '24px 16px', textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
                  <span className="spinner-sm" style={{ marginRight: 8, verticalAlign: -2 }} />
                  Searching across all execution history, steps, payloads, logs, and errors…
                </div>
              ) : results.length === 0 ? (
                <div style={{ padding: '28px 16px', textAlign: 'center' }}>
                  <div style={{ display: 'inline-flex', padding: 10, borderRadius: '50%', background: 'rgba(255, 255, 255, 0.04)', marginBottom: 10, color: '#94a3b8' }}>
                    <SearchIcon size={20} color="#94a3b8" />
                  </div>
                  <div style={{ fontSize: 13.5, fontWeight: 600, color: '#f8fafc', marginBottom: 4 }}>
                    No execution occurrences found for &ldquo;{query}&rdquo;
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8', maxWidth: 420, margin: '0 auto' }}>
                    Try searching by execution ID, step name, error code, status, email, connector object, or JSON payload field.
                  </div>
                </div>
              ) : (
                <>
                  <div style={{ padding: '8px 14px 4px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11, color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>
                    <span>Top Occurrences ({totalCount} found)</span>
                    <span>Use ↑ ↓ to navigate, Enter to open</span>
                  </div>

                  {results.map((item, idx) => {
                    const isSelected = selectedIndex === idx
                    const catStyle = CATEGORY_COLORS[item.category] || CATEGORY_COLORS.metadata
                    const isSuccess = item.status === 'success'
                    const isFailed = item.status === 'failed' || item.status === 'error'
                    const isRunning = item.status === 'running' || item.status === 'queued'

                    return (
                      <div
                        key={item.id || idx}
                        onClick={() => handleSelectOccurrence(item)}
                        onMouseEnter={() => setSelectedIndex(idx)}
                        style={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: 12,
                          padding: '10px 14px',
                          borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                          background: isSelected ? 'rgba(99, 102, 241, 0.15)' : 'transparent',
                          cursor: 'pointer',
                          transition: 'background 0.1s ease',
                        }}
                      >
                        {/* Status Dot */}
                        <div style={{ marginTop: 4, flexShrink: 0 }}>
                          <span
                            style={{
                              display: 'inline-block',
                              width: 7,
                              height: 7,
                              borderRadius: '50%',
                              background: isSuccess ? '#34d399' : isFailed ? '#f87171' : isRunning ? '#38bdf8' : '#fbbf24',
                              boxShadow: `0 0 6px ${isSuccess ? '#34d399' : isFailed ? '#f87171' : isRunning ? '#38bdf8' : '#fbbf24'}`,
                            }}
                          />
                        </div>

                        {/* Content */}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 3 }}>
                            {/* Category & Location Badge */}
                            <span
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                fontSize: 10.5,
                                fontWeight: 700,
                                padding: '1px 6px',
                                borderRadius: 4,
                                background: catStyle.bg,
                                color: catStyle.text,
                                border: `1px solid ${catStyle.border}`,
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {getCategoryIcon(item.category, 10, catStyle.text)}
                              <span>{item.location_badge}</span>
                            </span>

                            {/* Workflow Name */}
                            <span style={{ fontSize: 12.5, fontWeight: 600, color: '#f8fafc', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              <HighlightMatch text={item.workflow_name} query={query} />
                            </span>

                            {/* Execution ID */}
                            <code style={{ fontSize: 11, color: '#94a3b8', background: 'rgba(255, 255, 255, 0.04)', padding: '1px 5px', borderRadius: 4 }}>
                              <HighlightMatch text={item.execution_id?.slice(0, 14)} query={query} />
                            </code>

                            {/* Execution Timestamp */}
                            {item.started_at && (
                              <span
                                style={{
                                  fontSize: 10.5,
                                  color: '#94a3b8',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                  background: 'rgba(255, 255, 255, 0.04)',
                                  padding: '1px 6px',
                                  borderRadius: 4,
                                }}
                                title={`Executed: ${item.started_at}`}
                              >
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#818cf8" strokeWidth="2" style={{ flexShrink: 0 }}>
                                  <circle cx="12" cy="12" r="10" />
                                  <polyline points="12 6 12 12 16 14" />
                                </svg>
                                <span><HighlightMatch text={fmtDropdownTime(item.started_at)} query={query} /></span>
                              </span>
                            )}

                            {/* Duration */}
                            {item.duration_ms != null && (
                              <span style={{ fontSize: 11, color: '#64748b', marginLeft: 'auto', fontFamily: 'monospace' }}>
                                {Math.round(item.duration_ms)}ms
                              </span>
                            )}
                          </div>

                          {/* Snippet */}
                          {item.snippet && (
                            <div
                              style={{
                                fontSize: 12,
                                color: '#cbd5e1',
                                lineHeight: 1.4,
                                background: 'rgba(0, 0, 0, 0.25)',
                                padding: '4px 8px',
                                borderRadius: 5,
                                border: '1px solid rgba(255, 255, 255, 0.04)',
                                fontFamily: 'JetBrains Mono, monospace',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              <HighlightMatch text={item.snippet} query={query} />
                            </div>
                          )}
                        </div>

                        {/* Direct Jump Icon */}
                        <div style={{ flexShrink: 0, marginTop: 4 }}>
                          <span
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              color: isSelected ? '#818cf8' : '#64748b',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                            }}
                          >
                            <span>Open</span>
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                              <polyline points="9 18 15 12 9 6" />
                            </svg>
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </>
              )}
            </div>
          )}

          {/* Footer Bar: See all results */}
          {query.trim() && totalCount > 0 && (
            <div
              onClick={() => handleSubmitSearch()}
              style={{
                padding: '9px 14px',
                background: 'rgba(99, 102, 241, 0.1)',
                borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: 12,
                color: '#818cf8',
                fontWeight: 600,
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(99, 102, 241, 0.2)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'rgba(99, 102, 241, 0.1)')}
            >
              <span>View all {totalCount} occurrences in execution details</span>
              <kbd style={{ fontSize: 10, background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)', padding: '2px 5px', borderRadius: 4, color: '#e2e8f0', fontFamily: 'inherit' }}>
                ↵ Enter
              </kbd>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
