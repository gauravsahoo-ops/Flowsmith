import { useState, useMemo } from 'react'
import Button from './shared/Button'
import { WebhookDeliveryLog } from './WebhookDeliveryLog'
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
              <span>🔗</span>
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
                    background: '#090b10',
                    border: '1px solid rgba(255, 255, 255, 0.12)',
                    borderRadius: 6,
                    padding: '8px 10px',
                    color: '#fff',
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
                    background: '#090b10',
                    border: '1px solid rgba(255, 255, 255, 0.12)',
                    borderRadius: 6,
                    padding: '8px 10px',
                    color: '#fff',
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
                {copied ? '✓ Copied' : 'Copy URL'}
              </button>
            </div>
          </div>

          {/* Code Snippet Generator */}
          <div className="we-section">
            <div className="we-title">
              <span>⚡</span>
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

              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
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
                  {testing ? 'Sending…' : '⚡ Dispatch Test Webhook'}
                </Button>
                {!path && (
                  <span style={{ fontSize: 11, color: '#f87171' }}>Please enter a webhook path suffix first.</span>
                )}
              </div>

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
