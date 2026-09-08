// ExpressionHelper: autocomplete panel for the safe expression engine
// (Phase 40). Lists variables, this workflow's nodes, workspace env
// KEYS (values stay server-side) and pipes. Click a chip to copy its
// {{ ... }} snippet; paste into any field.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'

const BASE_VARS = [
  { name: '$json', snippet: '{{ $json }}', hint: 'first input item' },
  { name: '$execution.id', snippet: '{{ $execution.id }}', hint: 'execution id' },
  { name: '$workflow.id', snippet: '{{ $workflow.id }}', hint: 'workflow id' },
  { name: '$now', snippet: '{{ $now }}', hint: 'ISO timestamp' },
]

export default function ExpressionHelper({ workflowId }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [ctx, setCtx] = useState(null)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState('')

  useEffect(() => {
    if (!open || !workflowId || ctx) return
    let alive = true
    api
      .expressionContext(workflowId)
      .then((data) => alive && setCtx(data))
      .catch((err) => alive && setError(err.message))
    return () => {
      alive = false
    }
  }, [open, workflowId, ctx])

  const chips = useMemo(() => {
    if (!ctx) return []
    const out = [...BASE_VARS.map((v) => ({ ...v }))]
    for (const v of ctx.variables || []) {
      if (v.name === '$json') continue
      out.push({ name: v.name.split('.')[0] + '…', snippet: `{{ ${v.name} }}`, hint: v.description })
    }
    for (const n of ctx.nodes || []) {
      out.push({
        name: n.id,
        snippet: `{{ $node["${n.id}"].json }}`,
        hint: `node (${n.type})`,
      })
    }
    for (const k of ctx.env_keys || []) {
      out.push({ name: `$env.${k}`, snippet: `{{ $env.${k} }}`, hint: 'workspace env var' })
    }
    return out.filter(
      (c) =>
        !filter ||
        c.name.toLowerCase().includes(filter.toLowerCase()) ||
        (c.hint || '').toLowerCase().includes(filter.toLowerCase())
    )
  }, [ctx, filter])

  function copy(snippet) {
    navigator.clipboard?.writeText(snippet).then(
      () => {
        setCopied(snippet)
        setTimeout(() => setCopied(''), 1200)
      },
      () => {}
    )
  }

  return (
    <div className="expr-helper">
      <button className="ghost linklike" onClick={() => setOpen(!open)}>
        {open ? '▾ Expression helpers' : '▸ Expression helpers'}
      </button>
      {open && (
        <>
          <input
            className="expr-filter"
            placeholder="filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {error && <div className="banner-inline err">{error}</div>}
          {!ctx && !error && <p className="hint">loading…</p>}
          <div className="expr-chips">
            {chips.map((c, i) => (
              <button key={i} className="expr-chip" onClick={() => copy(c.snippet)} title={c.snippet}>
                <code>{c.snippet}</code>
                {c.hint && <span className="muted">{c.hint}</span>}
                {copied === c.snippet && <span className="ok"> copied</span>}
              </button>
            ))}
          </div>
          <p className="hint">
            Pipes:{' '}
            {(ctx?.pipes || []).map((p) => (
              <code key={p} className="pipe-chip">
                | {p}
              </code>
            ))}
          </p>
        </>
      )}
    </div>
  )
}
