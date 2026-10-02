// DataViewer: reusable data display with JSON / Table / Schema tabs.
// Features: search, copy, pagination, row count, expand/collapse all.

import { useMemo, useState, useCallback } from 'react'
import JsonTree from './JsonTree'

const VIEW_MODES = [
  { key: 'json', label: 'JSON' },
  { key: 'table', label: 'Table' },
  { key: 'schema', label: 'Schema' },
]

const PAGE_SIZE = 50

function TableView({ data }) {
  const [page, setPage] = useState(0)
  const [sortCol, setSortCol] = useState(null)
  const [sortDir, setSortDir] = useState('asc')
  const [filter, setFilter] = useState('')

  const rows = useMemo(() => {
    if (!data) return []
    const arr = Array.isArray(data) ? data : [data]
    return arr.map((item) => (item && typeof item === 'object' ? item : { value: item }))
  }, [data])

  const columns = useMemo(() => {
    const set = new Set()
    for (const row of rows) {
      for (const key of Object.keys(row)) set.add(key)
    }
    return Array.from(set)
  }, [rows])

  const filteredRows = useMemo(() => {
    if (!filter) return rows
    const f = filter.toLowerCase()
    return rows.filter((row) =>
      columns.some((col) => {
        const val = row[col]
        return val != null && String(val).toLowerCase().includes(f)
      })
    )
  }, [rows, filter, columns])

  const sortedRows = useMemo(() => {
    if (!sortCol) return filteredRows
    return [...filteredRows].sort((a, b) => {
      const va = a[sortCol]
      const vb = b[sortCol]
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      const cmp = String(va).localeCompare(String(vb), undefined, { numeric: true })
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [filteredRows, sortCol, sortDir])

  const totalPages = Math.ceil(sortedRows.length / PAGE_SIZE)
  const pageRows = sortedRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  const handleSort = useCallback(
    (col) => {
      if (sortCol === col) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
      } else {
        setSortCol(col)
        setSortDir('asc')
      }
      setPage(0)
    },
    [sortCol],
  )

  if (rows.length === 0) return <p className="hint">No data.</p>

  return (
    <div className="dv-table-container">
      <div className="dv-table-toolbar">
        <input
          className="dv-table-filter"
          placeholder="Filter rows…"
          value={filter}
          onChange={(e) => { setFilter(e.target.value); setPage(0) }}
        />
        <span className="dv-table-count">
          {filteredRows.length} row{filteredRows.length !== 1 ? 's' : ''}
        </span>
      </div>
      <div className="dv-table-wrap">
        <table className="dv-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  onClick={() => handleSort(col)}
                  className={sortCol === col ? 'sorted' : ''}
                >
                  {col}
                  {sortCol === col && (
                    <span className="sort-arrow" style={{ display: 'inline-flex', verticalAlign: -1, marginLeft: 4 }}>
                      {sortDir === 'asc' ? (
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="18 15 12 9 6 15"/></svg>
                      ) : (
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                      )}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, i) => (
              <tr key={page * PAGE_SIZE + i}>
                {columns.map((col) => {
                  const val = row[col]
                  const tip = typeof val === 'object' && val !== null ? JSON.stringify(val, null, 2) : String(val ?? '')
                  return (
                    <td key={col} title={tip}>
                      {formatCell(val)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="dv-table-pagination">
          <button
            className="ghost"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            ← Prev
          </button>
          <span className="dv-page-info">
            Page {page + 1} of {totalPages}
          </span>
          <button
            className="ghost"
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  )
}

function formatCell(val) {
  if (val === null || val === undefined) return <span className="dv-null">—</span>
  if (typeof val === 'boolean') return <span style={{ color: '#a78bfa' }}>{String(val)}</span>
  if (typeof val === 'number') return <span style={{ color: '#fbbf24' }}>{String(val)}</span>
  if (Array.isArray(val)) {
    return (
      <span className="dv-json" style={{ color: '#34d399', fontWeight: 500 }}>
        [Array({val.length})]
      </span>
    )
  }
  if (typeof val === 'object') {
    const keys = Object.keys(val)
    return (
      <span className="dv-json" style={{ color: '#818cf8', fontWeight: 500 }}>
        {`{Object(${keys.length})}`}
      </span>
    )
  }
  return String(val)
}

function inferSchemaFromData(data) {
  if (data == null) return null
  const sample = Array.isArray(data) ? data[0] : data
  if (!sample || typeof sample !== 'object') return { type: typeof sample }
  const props = {}
  for (const [k, v] of Object.entries(sample)) {
    if (v == null) props[k] = { type: 'null' }
    else if (Array.isArray(v)) props[k] = { type: 'array', items: v[0] ? { type: typeof v[0] } : {} }
    else if (typeof v === 'object') {
      const sub = {}
      for (const [sk, sv] of Object.entries(v)) sub[sk] = { type: typeof sv }
      props[k] = { type: 'object', properties: sub }
    } else props[k] = { type: typeof v }
  }
  return { type: 'object', properties: props }
}

function SchemaView({ schema, data }) {
  const display = schema && Object.keys(schema).length > 0 ? schema : inferSchemaFromData(data)
  if (!display) return <p className="hint">No schema available.</p>
  return (
    <div className="dv-schema">
      <JsonTree value={display} />
    </div>
  )
}

function CopyButton({ data }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = useCallback(() => {
    const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }, [data])
  return (
    <button type="button" className="ghost dv-copy" onClick={handleCopy} title="Copy to clipboard" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      {copied ? (
        <>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          <span>Copied</span>
        </>
      ) : (
        <>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
          <span>Copy</span>
        </>
      )}
    </button>
  )
}

export default function DataViewer({ data, schema, label }) {
  const [view, setView] = useState('json')
  const [search, setSearch] = useState('')

  const hasData = data != null && (typeof data !== 'object' || Object.keys(data).length > 0)
  const hasSchema = (schema != null && Object.keys(schema).length > 0) || hasData

  const tabs = VIEW_MODES.filter((m) => {
    if (m.key === 'schema' && !hasSchema) return false
    if (m.key === 'table' && (!hasData || typeof data !== 'object')) return false
    return true
  })

  if (!tabs.find((t) => t.key === view) && tabs.length > 0) {
    // keep current
  }

  return (
    <div className="dv-container">
      {label && <div className="dv-label">{label}</div>}
      <div className="dv-toolbar">
        {tabs.length > 1 && (
          <div className="dv-tabs">
            {tabs.map((t) => (
              <button
                key={t.key}
                type="button"
                className={`dv-tab ${view === t.key ? 'active' : ''}`}
                onClick={() => setView(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
        <div className="dv-actions">
          {hasData && <CopyButton data={data} />}
          {view === 'json' && hasData && (
            <input
              className="dv-search"
              placeholder="Search…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          )}
        </div>
      </div>
      <div className="dv-body">
        {view === 'json' && <JsonTree value={data} search={search} />}
        {view === 'table' && <TableView data={data} />}
        {view === 'schema' && <SchemaView schema={schema} data={data} />}
      </div>
    </div>
  )
}

export { TableView, SchemaView }
