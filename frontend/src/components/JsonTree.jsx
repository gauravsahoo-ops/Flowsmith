// JsonTree: collapsible viewer for node inputs/outputs with search highlighting.

import { memo, useState, useCallback } from 'react'

function Highlight({ text, search }) {
  if (!search || !text) return <>{text}</>
  const str = String(text)
  const lower = str.toLowerCase()
  const searchLower = search.toLowerCase()
  const parts = []
  let idx = 0
  let found = false
  while (idx < str.length) {
    const pos = lower.indexOf(searchLower, idx)
    if (pos === -1) {
      parts.push(<span key={idx}>{str.slice(idx)}</span>)
      break
    }
    if (pos > idx) parts.push(<span key={`p${idx}`}>{str.slice(idx, pos)}</span>)
    parts.push(<mark key={`m${pos}`} className="jt-highlight">{str.slice(pos, pos + search.length)}</mark>)
    idx = pos + search.length
    found = true
  }
  return <>{parts}</>
}

function Scalar({ value, search }) {
  if (value === null) return <span className="jt-null">null</span>
  if (value === undefined) return <span className="jt-null">undefined</span>
  if (typeof value === 'string') {
    const display = search ? value : `"${value}"`
    return <span className="jt-str">{search ? <Highlight text={value} search={search} /> : `"${value}"`}</span>
  }
  if (typeof value === 'number') return <span className="jt-num">{String(value)}</span>
  if (typeof value === 'boolean') return <span className="jt-bool">{String(value)}</span>
  return <span className="jt-null">{String(value)}</span>
}

function Node({ label, value, depth, search }) {
  const isObj = value && typeof value === 'object'
  const entries = isObj
    ? Array.isArray(value)
      ? value.map((v, i) => [String(i), v])
      : Object.entries(value)
    : []

  if (!isObj) {
    return (
      <div className="jt-row" style={{ paddingLeft: depth * 14 }}>
        {label != null && <span className="jt-key"><Highlight text={label} search={search} />: </span>}
        <Scalar value={value} search={search} />
      </div>
    )
  }

  const matchesSearch = search && JSON.stringify(value).toLowerCase().includes(search.toLowerCase())

  return (
    <details className={`jt-node ${matchesSearch ? 'jt-match' : ''}`} open={depth < 2 || Boolean(search)}>
      <summary style={{ paddingLeft: depth * 14 }}>
        {label != null && <span className="jt-key"><Highlight text={label} search={search} />: </span>}
        <span className="jt-brace">
          {Array.isArray(value) ? `[${entries.length}]` : `{${entries.length}}`}
        </span>
      </summary>
      {entries.map(([k, v]) => (
        <Node key={k} label={k} value={v} depth={depth + 1} search={search} />
      ))}
    </details>
  )
}

function JsonTree({ value, search }) {
  if (value == null || (typeof value === 'object' && !Object.keys(value).length)) {
    return <p className="hint jt-empty">empty</p>
  }

  return (
    <div className="json-tree">
      <Node label={null} value={value} depth={0} search={search} />
    </div>
  )
}

export default memo(JsonTree)
