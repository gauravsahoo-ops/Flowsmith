import { useState, useMemo, useEffect, useRef } from 'react'
import Button from './shared/Button'
import { WebhookDeliveryLog } from './WebhookDeliveryLog'
import { api } from '../api'
import './WebhookNodeEditor.css'

const HTTP_METHODS = ['POST', 'GET', 'PUT', 'PATCH', 'DELETE']

export default function WebhookNodeEditor({ node, onParamsChange, workflowId }) {
  const params = node?.parameters || {}
  const path = params.path || ''
  const method = params.method || 'POST'
  const respond = Boolean(params.respond)

  const [activeCodeTab, setActiveCodeTab] = useState('curl')
  const [copied, setCopied] = useState(false)
  const [testPayload, setTestPayload] = useState(
    JSON.stringify(
      {
        event: 'user.signup',
        user: { id: 'usr_101', name: 'Dev User', email: 'dev@example.com' },
      },
      null,
      2
    )
  )
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [viewTab, setViewTab] = useState('config') // config | deliveries
  const [listening, setListening] = useState(false)
  const [capturedEvent, setCapturedEvent] = useState(null)
  const listenStartTimeRef = useRef(null)

  useEffect(() => {
    if (!listening) return
    listenStartTimeRef.current = Date.now()
    const timer = setInterval(async () => {
      try {
        const { data } = await api.listWebhookDeliveries({
          workflow_id: workflowId,
          page: 1,
          pageSize: 3,
        })
        if (Array.isArray(data) && data.length > 0) {
          const latest = data[0]
          const deliveryTime = new Date(latest.created_at).getTime()
          if (deliveryTime >= (listenStartTimeRef.current || 0) - 2000) {
            setListening(false)
            setCapturedEvent(latest)
            if (latest.request_body) {
              setTestPayload(
                typeof latest.request_body === 'string'
                  ? latest.request_body
                  : JSON.stringify(latest.request_body, null, 2)
              )
            }
          }
        }
      } catch {}
    }, 1500)
    return () => clearInterval(timer)
  }, [listening, workflowId])

  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'
  const webhookUrl = useMemo(() => {
    if (!path) return `${origin}/api/webhooks/<your-path>`
    const base = `${origin}/api/webhooks/${encodeURIComponent(path)}`
    return respond ? `${base}?respond=true` : base
  }, [origin, path, respond])

  const snippets = useMemo(() => {
    const curl = `curl -X ${method} "${webhookUrl}" \\
  -H "Content-Type: application/json" \\
  -d '${testPayload.replace(/\n\s*/g, ' ')}'`

    const js = `const response = await fetch("${webhookUrl}", {
  method: "${method}",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(${testPayload})
});
const data = await response.json();
console.log(data);`

    const python = `import requests

url = "${webhookUrl}"
payload = ${testPayload}
response = requests.${method.toLowerCase()}(url, json=payload)
print(response.status_code, response.json())`

    return { curl, js, python }
  }, [method, webhookUrl, testPayload])

  const handleCopyUrl = () => {
    navigator.clipboard.writeText(webhookUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleSendTest = async () => {
    if (!path) return
    setTesting(true)
    setTestResult(null)
    try {
      let bodyData = undefined
      if (method !== 'GET') {
        try {
          bodyData = JSON.parse(testPayload)
        } catch {
          bodyData = testPayload
        }
      }
      const res = await fetch(webhookUrl, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: bodyData ? JSON.stringify(bodyData) : undefined,
      })
      const text = await res.text()
      let parsed = text
      try {
        parsed = JSON.parse(text)
      } catch {}
      setTestResult({
        status: res.status,
        statusText: res.statusText,
        data: parsed,
        timestamp: new Date().toLocaleTimeString(),
      })
    } catch (err) {
      setTestResult({
        status: 0,
        statusText: 'Network Error',
        error: err.message,
        timestamp: new Date().toLocaleTimeString(),
      })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="webhook-editor" role="region" aria-label="Webhook Configuration">
      <div style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
        <button
          type="button"
          className={`we-code-tab ${viewTab === 'config' ? 'active' : ''}`}
          onClick={() => setViewTab('config')}
        >
          Endpoint & Code
        </button>
        <button
          type="button"
          className={`we-code-tab ${viewTab === 'deliveries' ? 'active' : ''}`}
          onClick={() => setViewTab('deliveries')}
        >
          Recent Deliveries
        </button>
      </div>

      {viewTab === 'deliveries' ? (
        <div className="we-section">
          <WebhookDeliveryLog workflowId={workflowId} nodeId={node?.id} />
        </div>
      ) : (
        <>
          {/* Endpoint Configuration */}
          <div className="we-section">
            <div className="we-title">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
              <span>Public Webhook Endpoint</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px', gap: 12, marginBottom: 12 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
                <span>Webhook Path Suffix (a-z, 0-9, -, _)</span>
                <input
                  type="text"
                  value={path}
                  placeholder="e.g. stripe-event or customer-leads"
                  onChange={(e) => onParamsChange({ ...params, path: e.target.value })}
                  style={{
                    background: 'var(--panel-2, #090b10)',
                    border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                    borderRadius: 6,
                    padding: '8px 10px',
                    color: 'var(--text, #fff)',
                    fontFamily: 'monospace',
                  }}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
                <span>HTTP Method</span>
                <select
                  value={method}
                  onChange={(e) => onParamsChange({ ...params, method: e.target.value })}
                  style={{
                    background: 'var(--panel-2, #090b10)',
                    border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                    borderRadius: 6,
                    padding: '8px 10px',
                    color: 'var(--text, #fff)',
                  }}
                >
                  {HTTP_METHODS.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, marginBottom: 14 }}>
              <input
                type="checkbox"
                checked={respond}
                onChange={(e) => onParamsChange({ ...params, respond: e.target.checked })}
              />
              <span>Wait for execution and return synchronous response</span>
            </label>

            <div className="we-url-box">
              <span className="we-method-badge">{method}</span>
              <span className="we-url-text" title={webhookUrl}>
                {webhookUrl}
              </span>
              <button type="button" className="we-copy-btn" onClick={handleCopyUrl}>
                {copied ? (<span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>Copied</span>) : 'Copy URL'}
              </button>
            </div>
          </div>

          {/* Code Snippet Generator */}
          <div className="we-section">
            <div className="we-title">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
              <span>cURL & Code Snippet Generator</span>
            </div>

            <div className="we-code-tabs">
              <button
                type="button"
                className={`we-code-tab ${activeCodeTab === 'curl' ? 'active' : ''}`}
                onClick={() => setActiveCodeTab('curl')}
              >
                cURL
              </button>
              <button
                type="button"
                className={`we-code-tab ${activeCodeTab === 'js' ? 'active' : ''}`}
                onClick={() => setActiveCodeTab('js')}
              >
                JavaScript (Fetch)
              </button>
              <button
                type="button"
                className={`we-code-tab ${activeCodeTab === 'python' ? 'active' : ''}`}
                onClick={() => setActiveCodeTab('python')}
              >
                Python (Requests)
              </button>
            </div>

            <pre className="we-code-snippet">{snippets[activeCodeTab]}</pre>
          </div>

          {/* Interactive Test Webhook Sender */}
          <div className="we-section">
            <div className="we-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#38bdf8' }}><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              <span>Send Sample Test Webhook</span>
            </div>

            <div className="we-test-area">
              <span style={{ fontSize: 11, color: '#94a3b8' }}>Test JSON Payload:</span>
              <textarea
                className="we-test-textarea"
                value={testPayload}
                onChange={(e) => setTestPayload(e.target.value)}
                placeholder="Enter JSON payload"
              />

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <Button
                  variant="primary"
                  onClick={handleSendTest}
                  disabled={testing || !path}
                  style={{
                    background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #d946ef 100%)',
                    border: 'none',
                    fontWeight: 600,
                  }}
                >
                  {testing ? 'Sending…' : (<span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>Dispatch Test Webhook</span>)}
                </Button>
                <button
                  type="button"
                  className="ghost"
                  onClick={() => {
                    setCapturedEvent(null)
                    setListening((v) => !v)
                  }}
                  disabled={!path}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    borderColor: listening ? 'var(--accent, #6366f1)' : 'var(--border)',
                    color: listening ? 'var(--accent, #818cf8)' : 'var(--text)',
                    fontSize: 12,
                    fontWeight: 600,
                    padding: '8px 12px',
                    borderRadius: 6,
                  }}
                >
                  {listening ? (
                    <>
                      <span className="app-topbar-context-dot" style={{ background: '#34d399' }} />
                      <span>Listening for external events…</span>
                    </>
                  ) : (
                    <>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9" />
                        <path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5" />
                        <circle cx="12" cy="12" r="2" />
                        <path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5" />
                        <path d="M19.1 4.9C23 8.8 23 15.2 19.1 19.1" />
                      </svg>
                      <span>Listen for Test Event</span>
                    </>
                  )}
                </button>
                {!path && (
                  <span style={{ fontSize: 11, color: '#f87171' }}>Please enter a webhook path suffix first.</span>
                )}
              </div>

              {capturedEvent && (
                <div
                  style={{
                    marginTop: 10,
                    padding: '8px 12px',
                    borderRadius: 6,
                    background: 'rgba(16, 185, 129, 0.1)',
                    border: '1px solid rgba(16, 185, 129, 0.3)',
                    color: '#34d399',
                    fontSize: 12,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                    <strong>Live payload captured from incoming webhook!</strong> (HTTP {capturedEvent.response_status || 200})
                  </span>
                  <button type="button" className="ghost small" onClick={() => setCapturedEvent(null)} style={{ padding: '2px 6px' }}>Dismiss</button>
                </div>
              )}

              {testResult && (
                <div
                  className="we-test-result"
                  style={{
                    background: testResult.status >= 200 && testResult.status < 300 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                    borderColor: testResult.status >= 200 && testResult.status < 300 ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)',
                    color: testResult.status >= 200 && testResult.status < 300 ? '#6ee7b7' : '#fca5a5',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <strong>
                      HTTP {testResult.status} {testResult.statusText}
                    </strong>
                    <span style={{ fontSize: 11 }}>{testResult.timestamp}</span>
                  </div>
                  <pre
                    style={{
                      margin: 0,
                      fontSize: 11,
                      fontFamily: 'monospace',
                      maxHeight: 120,
                      overflow: 'auto',
                    }}
                  >
                    {JSON.stringify(testResult.data || testResult.error, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
