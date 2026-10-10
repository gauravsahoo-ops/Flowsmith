// JsonTree: collapsible, high-performance viewer for node inputs/outputs with
// progressive chunking, search highlighting, copy path/value, and expandable long strings.

import { memo, useState, useCallback, useMemo } from 'react'

function Highlight({ text, search }) {
  if (!search || !text) return <>{text}</>
  const str = String(text)
  const lower = str.toLowerCase()
  const searchLower = search.toLowerCase()
  const parts = []
  let idx = 0
  while (idx < str.length) {
    const pos = lower.indexOf(searchLower, idx)
    if (pos === -1) {
      parts.push(<span key={idx}>{str.slice(idx)}</span>)
      break
    }
    if (pos > idx) parts.push(<span key={`p${idx}`}>{str.slice(idx, pos)}</span>)
    parts.push(
      <mark key={`m${pos}`} className="jt-highlight">
        {str.slice(pos, pos + search.length)}
      </mark>
    )
    idx = pos + search.length
  }
  return <>{parts}</>
}

function StringScalar({ value, search }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)
  const isLong = typeof value === 'string' && value.length > 280

  const handleCopy = (e) => {
    e.stopPropagation()
    navigator.clipboard?.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (!isLong) {
    return (
      <span className="jt-str" title="Click to copy string" onClick={handleCopy}>
        "{search ? <Highlight text={value} search={search} /> : value}"
        {copied && <span className="jt-copied-pill">copied!</span>}
      </span>
    )
  }

  const displayText = expanded ? value : value.slice(0, 240) + '…'

  return (
    <span className="jt-str-wrap">
      <span className="jt-str">"{search ? <Highlight text={displayText} search={search} /> : displayText}"</span>
      <button
        type="button"
        className="jt-expand-text-btn"
        onClick={(e) => {
          e.stopPropagation()
          setExpanded((v) => !v)
        }}
        title={expanded ? 'Collapse long text' : `Expand full text (${value.length} characters)`}
      >
        {expanded ? '↑ Collapse' : `+ View full (${value.length} chars)`}
      </button>
      <button
        type="button"
        className="jt-copy-val-btn"
        onClick={handleCopy}
        title="Copy complete string"
      >
        {copied ? '✓' : 'Copy'}
      </button>
    </span>
  )
}

function Scalar({ value, search }) {
  const [copied, setCopied] = useState(false)

  const copyVal = (e) => {
    e.stopPropagation()
    navigator.clipboard?.writeText(String(value))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (value === null) return <span className="jt-null">null</span>
  if (value === undefined) return <span className="jt-null">undefined</span>
  if (typeof value === 'string') {
    return <StringScalar value={value} search={search} />
  }
  if (typeof value === 'number') {
    return (
      <span className="jt-num" title="Click to copy number" onClick={copyVal}>
        {String(value)}
        {copied && <span className="jt-copied-pill">copied!</span>}
      </span>
    )
  }
  if (typeof value === 'boolean') {
    return (
      <span className="jt-bool" title="Click to copy boolean" onClick={copyVal}>
        {String(value)}
        {copied && <span className="jt-copied-pill">copied!</span>}
      </span>
    )
  }
  return <span className="jt-null">{String(value)}</span>
}

const CHUNK_SIZE = 50

function Node({ label, value, depth, search, path = '', forceOpen = null }) {
  const [chunkLimit, setChunkLimit] = useState(CHUNK_SIZE)
  const [copiedPath, setCopiedPath] = useState(false)
  const isObj = value && typeof value === 'object'
  const isArr = Array.isArray(value)

  const entries = useMemo(() => {
    if (!isObj) return []
    return isArr ? value.map((v, i) => [String(i), v]) : Object.entries(value)
  }, [isObj, isArr, value])

  const currentPath = useMemo(() => {
    if (label == null) return '$json'
    if (isArr || /^\d+$/.test(label)) return `${path}[${label}]`
    return /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(label) ? `${path}.${label}` : `${path}['${label.replace(/'/g, "\\'")}']`
  }, [label, path, isArr])

  const copyPath = (e) => {
    e.stopPropagation()
    navigator.clipboard?.writeText(currentPath)
    setCopiedPath(true)
    setTimeout(() => setCopiedPath(false), 1500)
  }

  if (!isObj) {
    return (
      <div className="jt-row" style={{ paddingLeft: depth * 14 }}>
        {label != null && (
          <span className="jt-key" title={`Path: ${currentPath} (click to copy)`} onClick={copyPath}>
            <Highlight text={label} search={search} />:
            {copiedPath && <span className="jt-copied-pill">path copied</span>}
          </span>
        )}
        <Scalar value={value} search={search} />
      </div>
    )
  }

  const matchesSearch = Boolean(
    search &&
      (String(label).toLowerCase().includes(search.toLowerCase()) ||
        JSON.stringify(value).toLowerCase().includes(search.toLowerCase()))
  )

  // Smart initial openness: auto-open top levels unless forced or matched
  const defaultOpen = forceOpen !== null ? forceOpen : depth < 2 || Boolean(matchesSearch)

  const visibleEntries = entries.slice(0, chunkLimit)
  const hasMore = entries.length > chunkLimit

  return (
    <details className={`jt-node ${matchesSearch ? 'jt-match' : ''}`} open={defaultOpen}>
      <summary style={{ paddingLeft: depth * 14 }}>
        {label != null && (
          <span
            className="jt-key"
            title={`Path: ${currentPath} (click to copy)`}
            onClick={copyPath}
          >
            <Highlight text={label} search={search} />:
            {copiedPath && <span className="jt-copied-pill">path copied</span>}
          </span>
        )}
        <span className="jt-brace">
          {isArr ? `[${entries.length}]` : `{${entries.length}}`}
        </span>
      </summary>
      <div className="jt-children">
        {visibleEntries.map(([k, v]) => (
          <Node
            key={k}
            label={k}
            value={v}
            depth={depth + 1}
            search={search}
            path={currentPath}
            forceOpen={forceOpen}
          />
        ))}
        {hasMore && (
          <div className="jt-chunk-more" style={{ paddingLeft: (depth + 1) * 14 }}>
            <span>
              Showing {chunkLimit} of {entries.length} items —{' '}
            </span>
            <button
              type="button"
              className="jt-chunk-btn"
              onClick={(e) => {
                e.stopPropagation()
                setChunkLimit((prev) => Math.min(prev + CHUNK_SIZE, entries.length))
              }}
            >
              + Show {Math.min(CHUNK_SIZE, entries.length - chunkLimit)} more
            </button>
            <button
              type="button"
              className="jt-chunk-btn text-accent"
              onClick={(e) => {
                e.stopPropagation()
                setChunkLimit(entries.length)
              }}
            >
              Show all ({entries.length})
            </button>
          </div>
        )}
      </div>
    </details>
  )
}

function JsonTree({ value, search, showToolbar = true }) {
  const [expandAll, setExpandAll] = useState(null)
  const [copiedAll, setCopiedAll] = useState(false)

  const handleCopyAll = useCallback(() => {
    try {
      const text = JSON.stringify(value, null, 2)
      navigator.clipboard?.writeText(text)
      setCopiedAll(true)
      setTimeout(() => setCopiedAll(false), 1800)
    } catch {
      // ignore
    }
  }, [value])

  const totalCount = useMemo(() => {
    if (value == null) return 0
    if (Array.isArray(value)) return value.length
    if (typeof value === 'object') return Object.keys(value).length
    return 1
  }, [value])

  if (value == null || (typeof value === 'object' && !Object.keys(value).length)) {
    return <p className="hint jt-empty">empty</p>
  }

  return (
    <div className="json-tree-container">
      {showToolbar && (
        <div className="jt-toolbar">
          <span className="jt-count-badge">
            {totalCount} {Array.isArray(value) ? (totalCount === 1 ? 'item' : 'items') : (totalCount === 1 ? 'key' : 'keys')}
          </span>
          <div className="jt-toolbar-actions">
            <button
              type="button"
              className="jt-tool-btn"
              onClick={() => setExpandAll(true)}
              title="Expand all nodes"
            >
              Expand all
            </button>
            <button
              type="button"
              className="jt-tool-btn"
              onClick={() => setExpandAll(false)}
              title="Collapse all nodes"
            >
              Collapse all
            </button>
            <button
              type="button"
              className="jt-tool-btn"
              onClick={handleCopyAll}
              title="Copy complete JSON"
            >
              {copiedAll ? '✓ Copied' : 'Copy JSON'}
            </button>
          </div>
        </div>
      )}
      <div className="json-tree">
        <Node
          label={null}
          value={value}
          depth={0}
          search={search}
          path="$json"
          forceOpen={expandAll}
        />
      </div>
    </div>
  )
}

export default memo(JsonTree)
