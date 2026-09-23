// MappingField: wraps a string input with data-mapping superpowers
// (Phase 5). An "fx" button opens a browser of upstream output fields;
// picking one inserts {{ $node["id"].json.path }}. When the value holds
// an expression, a debounced preview shows the resolved value or a
// missing-field warning.

import { useEffect, useRef, useState } from 'react'
import { insertMapping } from '../utils/mappingUtils'

export default function MappingInput({ schema, value, onChange, path, mapping = [], onPreview }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [preview, setPreview] = useState(null)
  const [isDragOver, setIsDragOver] = useState(false)

  const timer = useRef(null)
  useEffect(() => {
    if (!onPreview || !(value ?? '').includes('{{')) {
      setPreview(null)
      return undefined
    }
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try {
        setPreview(await onPreview(value))
      } catch {
        setPreview({ missing: true, rendered: 'preview unavailable' })
      }
    }, 300)
    return () => clearTimeout(timer.current)
  }, [value, onPreview, mapping])

  const fields = mapping.filter(
    (f) =>
      !filter ||
      f.path.toLowerCase().includes(filter.toLowerCase()) ||
      (f.node_id || '').toLowerCase().includes(filter.toLowerCase())
  )

  function pick(f) {
    const nid = f.node_id
    const snippet =
      f.path.includes('.') || f.path.includes('[')
        ? `{{ $node["${nid}"].${f.path} }}`
        : `{{ $node["${nid}"].json.${f.path} }}`
    onChange(insertMapping(value, snippet))
    setOpen(false)
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
    if (!isDragOver) setIsDragOver(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setIsDragOver(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragOver(false)
    const varData = e.dataTransfer.getData('application/flowsmith-variable')
    const textData = e.dataTransfer.getData('text/plain')
    let exprToInsert = ''
    if (varData) {
      try {
        const parsed = JSON.parse(varData)
        exprToInsert = parsed.expr || ''
      } catch {}
    }
    if (!exprToInsert && textData) {
      exprToInsert = textData
    }
    if (exprToInsert) {
      const currentVal = value ?? ''
      const inputEl = e.target
      let nextVal = ''
      if (inputEl && typeof inputEl.selectionStart === 'number') {
        const start = inputEl.selectionStart
        const end = inputEl.selectionEnd
        nextVal = currentVal.substring(0, start) + exprToInsert + currentVal.substring(end)
      } else {
        nextVal = insertMapping(currentVal, exprToInsert)
      }
      onChange(nextVal)
    }
  }

  const Input = schema?.format === 'textarea' ? 'textarea' : 'input'

  return (
    <div className="mapping-field" style={{ minWidth: 0, width: '100%' }}>
      <label className="text-field" style={{ display: 'flex', flexDirection: 'column', width: '100%', minWidth: 0 }}>
        {schema?.title !== '' && (
          <span style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2 }}>{schema?.title || path}</span>
        )}
        <span className="mapping-row" style={{ display: 'flex', alignItems: 'center', gap: 4, width: '100%', minWidth: 0 }}>
          <Input
            type={schema?.format === 'password' ? 'password' : 'text'}
            inputMode={schema?.format === 'textarea' ? undefined : Input}
            {...(Input === 'textarea' ? { rows: 2 } : {})}
            as={Input}
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value || undefined)}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={isDragOver ? 'is-drag-target' : ''}
            placeholder={schema?.description}
            style={{ flex: 1, minWidth: 0, width: '100%' }}
          />
          {mapping.length > 0 && (
            <button
              type="button"
              className="fx-btn"
              title="Map from upstream fields"
              onClick={() => setOpen(!open)}
            >
              fx
            </button>
          )}
        </span>
      </label>

      {open && (
        <div className="mapping-pop">
          <input
            className="mapping-filter"
            placeholder="filter upstream fields…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className="mapping-list">
            {fields.length === 0 && <p className="hint">Run the workflow once to see upstream fields.</p>}
            {fields.map((f, i) => (
              <button key={`${f.node_id}:${f.path}:${i}`} type="button" className="mapping-item" onClick={() => pick(f)}>
                <code>{f.path}</code>
                <span className="badge">{f.type}</span>
                {f.sample != null && f.sample !== '' && (
                  <span className="muted sample">{String(f.sample).slice(0, 40)}</span>
                )}
                <span className="muted node-tag">{f.node_id}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {preview && !preview.missing && (
        <div className="preview ok" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%', marginTop: 3 }}>
          = {preview.rendered !== undefined ? preview.rendered.slice(0, 120) : String(preview.value).slice(0, 120)}
          <span className="badge" style={{ marginLeft: 6 }}>{preview.type}</span>
        </div>
      )}
      {preview && preview.missing && (
        <div className="preview err" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%', marginTop: 3 }}>
          ⚠ field not found in upstream outputs
        </div>
      )}
    </div>
  )
}
