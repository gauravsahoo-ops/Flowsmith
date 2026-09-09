import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

// Public form-fill page (Batch D): renders a form_trigger definition and
// submits it. No auth, no token — same-origin fetch only.
export default function FormFillPage() {
  const { slug } = useParams()
  const [definition, setDefinition] = useState(null)
  const [values, setValues] = useState({})
  const [status, setStatus] = useState('loading') // loading | ready | sent | error
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetch(`/api/webhooks/form/${encodeURIComponent(slug)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? 'Form not found.' : 'Could not load form.')
        return r.json()
      })
      .then((body) => {
        if (cancelled) return
        setDefinition(body.data || body)
        setStatus('ready')
      })
      .catch((e) => {
        if (cancelled) return
        setError(e.message)
        setStatus('error')
      })
    return () => { cancelled = true }
  }, [slug])

  function set(name, value) {
    setValues((v) => ({ ...v, [name]: value }))
  }

  async function submit(ev) {
    ev.preventDefault()
    setError('')
    const payload = {}
    for (const f of definition.fields || []) {
      const v = values[f.name]
      if ((v === undefined || v === '') && f.required) {
        setError(`Field '${f.label || f.name}' is required.`)
        return
      }
      if (v !== undefined && v !== '') payload[f.name] = v
    }
    try {
      const r = await fetch(`/api/webhooks/form/${encodeURIComponent(slug)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(body?.detail || 'Submission failed.')
      }
      setStatus('sent')
    } catch (e) {
      setError(e.message)
    }
  }

  if (status === 'loading') {
    return (
      <div className="page"><p className="hint">Loading form…</p></div>
    )
  }

  if (status === 'error') {
    return (
      <div className="page">
        <h1>Form unavailable</h1>
        <p className="hint">{error}</p>
      </div>
    )
  }

  if (status === 'sent') {
    return (
      <div className="page">
        <h1>Submitted</h1>
        <p className="hint">Thanks — your response was recorded.</p>
      </div>
    )
  }

  return (
    <div className="page">
      <h1>{definition.title || 'Form'}</h1>
      <form onSubmit={submit}>
        {(definition.fields || []).map((f) => (
          <div className="field-row" key={f.name}>
            <label>
              <span>{f.label || f.name}{f.required ? ' *' : ''}</span>
              {f.type === 'boolean' ? (
                <input
                  type="checkbox"
                  checked={Boolean(values[f.name])}
                  onChange={(e) => set(f.name, e.target.checked)}
                />
              ) : (
                <input
                  type={f.type === 'number' ? 'number' : f.type === 'email' ? 'email' : 'text'}
                  value={values[f.name] ?? ''}
                  onChange={(e) => set(f.name, e.target.value)}
                  required={false}
                />
              )}
            </label>
          </div>
        ))}
        {error && <p className="form-error">{error}</p>}
        <button className="ghost" type="submit">Submit</button>
      </form>
    </div>
  )
}
