import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

// Public chat page (Batch D): talks to a chat_trigger workflow.
// No auth, no token — same-origin fetch only. History lives in local
// state (the server is stateless); a session id tags the conversation.
export default function ChatPage() {
  const { slug } = useParams()
  const [info, setInfo] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [status, setStatus] = useState('loading') // loading | ready | error
  const [error, setError] = useState('')
  const sessionRef = useRef(`ses_${Math.random().toString(36).slice(2, 14)}`)
  const bottomRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/webhooks/chat/${encodeURIComponent(slug)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? 'Chat not found.' : 'Could not load chat.')
        return r.json()
      })
      .then((body) => {
        if (cancelled) return
        const data = body.data || body
        setInfo(data)
        if (data.greeting) setMessages([{ role: 'assistant', content: data.greeting }])
        setStatus('ready')
      })
      .catch((e) => {
        if (cancelled) return
        setError(e.message)
        setStatus('error')
      })
    return () => { cancelled = true }
  }, [slug])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  async function send(ev) {
    ev.preventDefault()
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    setError('')
    const history = [...messages, { role: 'user', content: text }]
    setMessages(history)
    setSending(true)
    try {
      const r = await fetch(`/api/webhooks/chat/${encodeURIComponent(slug)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sessionRef.current,
          history: history.slice(-20).map((m) => ({ role: m.role, content: m.content })),
        }),
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(body?.detail || 'Send failed.')
      const data = body.data || body
      if (data.error) throw new Error(data.error.message || 'Workflow failed.')
      setMessages((m) => [...m, {
        role: 'assistant',
        content: data.reply || '(no reply)',
      }])
    } catch (e) {
      setError(e.message)
    } finally {
      setSending(false)
    }
  }

  if (status === 'loading') {
    return (
      <div className="page"><p className="hint">Loading chat…</p></div>
    )
  }

  if (status === 'error') {
    return (
      <div className="page">
        <h1>Chat unavailable</h1>
        <p className="hint">{error}</p>
      </div>
    )
  }

  return (
    <div className="page" style={{ maxWidth: 640 }}>
      <h1>{info?.title || 'Chat'}</h1>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: '16px 0' }}>
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
              background: m.role === 'user' ? 'rgba(56,189,248,0.15)' : 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 10,
              padding: '8px 12px',
              maxWidth: '85%',
              whiteSpace: 'pre-wrap',
            }}
          >
            {m.content}
          </div>
        ))}
        {sending && <p className="hint">Thinking…</p>}
        <div ref={bottomRef} />
      </div>
      {error && <p className="form-error">{error}</p>}
      <form onSubmit={send} style={{ display: 'flex', gap: 8 }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message…"
          aria-label="Chat message"
          style={{ flex: 1 }}
          disabled={sending}
        />
        <button className="ghost" type="submit" disabled={sending || !input.trim()}>Send</button>
      </form>
    </div>
  )
}
