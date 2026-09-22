import { useState, useEffect, useMemo } from 'react'
import MappingField from './MappingField'
import SearchableSelect from './SearchableSelect'

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
const AUTHENTICATION_OPTIONS = [
  { value: 'none', label: 'None' },
  { value: 'predefined', label: 'Predefined Credential Type' },
  { value: 'generic', label: 'Generic Credential Type' },
]
const GENERIC_AUTH_OPTIONS = [
  { value: 'basic', label: 'Basic Auth' },
  { value: 'bearer', label: 'Bearer Auth' },
  { value: 'custom', label: 'Custom Auth' },
  { value: 'digest', label: 'Digest Auth' },
  { value: 'header', label: 'Header Auth' },
  { value: 'oauth1', label: 'OAuth1 API' },
  { value: 'oauth2', label: 'OAuth2 API' },
  { value: 'query', label: 'Query Auth' },
]
const BODY_CONTENT_TYPES = [
  { value: 'json', label: 'JSON' },
  { value: 'form-urlencoded', label: 'Form URL-encoded' },
  { value: 'multipart-form-data', label: 'Multipart Form Data' },
  { value: 'raw', label: 'Raw / Text' },
]
const RESPONSE_FORMATS = [
  { value: 'auto', label: 'Auto' },
  { value: 'json', label: 'JSON' },
  { value: 'text', label: 'Text' },
]
const AUTH_CRED_MAP = {
  bearer: ['bearer_auth','oauth2','http'],
  basic: ['basic_auth','http'],
  header: ['header_auth','http'],
  query: ['query_auth','http'],
  digest: ['digest_auth'],
  custom: ['custom_auth'],
  oauth2: ['oauth2','bearer_auth','salesforce'],
  oauth1: ['oauth1'],
  api_key: ['header_auth','query_auth','http'],
}

function toList(dict) {
  if (!dict || typeof dict !== 'object') return []
  return Object.entries(dict).map(([name, value]) => ({ name, value: String(value ?? '') }))
}
function fromList(list) {
  const out = {}
  for (const { name, value } of list || []) {
    if (name) out[name] = value ?? ''
  }
  return out
}

function CurlModal({ open, onClose, onImport }) {
  const [text, setText] = useState('')
  if (!open) return null
  return (
    <div className="node-editor-overlay" style={{ zIndex: 500 }} onClick={onClose}>
      <div className="credentials-panel" style={{ width: 560 }} onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Import cURL</h2>
          <button className="ghost" onClick={onClose}>✕</button>
        </header>
        <p className="hint" style={{ margin: '8px 0' }}>Paste a cURL command. Method, URL, headers, query and body will be extracted.</p>
        <textarea
          rows={8}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={'curl -X POST https://api.example.com/users -H "Content-Type: application/json" -d \'{"name":"John"}\''}
          style={{ width: '100%', fontFamily: 'ui-monospace, monospace', fontSize: 12 }}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button className="primary" onClick={() => { onImport(text); onClose(); setText('') }} disabled={!text.trim()}>Import</button>
          <button className="ghost" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

// Inline cURL parser for frontend (mirrors backend parse_curl)
function parseCurlFrontend(curlStr) {
  if (!curlStr || !curlStr.trim()) return {}
  let str = curlStr.trim().replace(/\\\n/g, ' ').replace(/\\\r\n/g, ' ')
  // Simple tokenization handling quotes
  const tokens = []
  let cur = ''
  let inSingle = false
  let inDouble = false
  for (let i = 0; i < str.length; i++) {
    const c = str[i]
    if (c === "'" && !inDouble) { inSingle = !inSingle; cur += c; continue }
    if (c === '"' && !inSingle) { inDouble = !inDouble; cur += c; continue }
    if (c === ' ' && !inSingle && !inDouble) {
      if (cur) { tokens.push(cur); cur = '' }
      continue
    }
    cur += c
  }
  if (cur) tokens.push(cur)
  // Strip surrounding quotes from tokens
  const strip = (s) => s.replace(/^['"]|['"]$/g, '')
  const cleaned = tokens.map(t => {
    if ((t.startsWith("'") && t.endsWith("'")) || (t.startsWith('"') && t.endsWith('"'))) return t.slice(1, -1)
    return strip(t)
  })
  let idx = 0
  if (cleaned[0] && cleaned[0].toLowerCase() === 'curl') idx = 1
  const headers = {}
  const query = {}
  let method = null
  let url = null
  let body = null
  let bodyContentType = null
  let auth_type = 'none'
  let auth_token = ''
  let auth_username = ''
  let auth_password = ''
  while (idx < cleaned.length) {
    const tok = cleaned[idx]
    if (tok === '-X' || tok === '--request') {
      method = (cleaned[idx + 1] || '').toUpperCase()
      idx += 2; continue
    }
    if (tok === '-H' || tok === '--header') {
      const hv = cleaned[idx + 1] || ''
      const colon = hv.indexOf(':')
      if (colon > -1) {
        const k = hv.slice(0, colon).trim()
        const v = hv.slice(colon + 1).trim()
        if (k.toLowerCase() === 'authorization' && v.toLowerCase().startsWith('bearer ')) {
          auth_type = 'bearer'; auth_token = v.slice(7).trim()
        } else if (k.toLowerCase() === 'authorization' && v.toLowerCase().startsWith('basic ')) {
          try { const dec = atob(v.slice(6).trim()); const c2 = dec.indexOf(':'); if (c2 > -1) { auth_username = dec.slice(0, c2); auth_password = dec.slice(c2+1); auth_type='basic' } else { headers[k]=v } } catch { headers[k]=v }
        } else { headers[k] = v }
      }
      idx += 2; continue
    }
    if (tok === '-d' || tok === '--data' || tok === '--data-raw' || tok === '--data-binary') {
      const dv = cleaned[idx + 1] || ''
      if (!body) {
        try { body = JSON.parse(dv); bodyContentType='json' } catch { body = dv; bodyContentType='raw' }
      } else body = dv
      if (!method) method='POST'
      idx += 2; continue
    }
    if (tok === '--data-urlencode') {
      const dv = cleaned[idx + 1] || ''
      if (!body || typeof body !== 'object') body = {}
      if (dv.includes('=')) { const [dk,dv2]=dv.split('=',2); body[dk]=dv2 } else body[dv]=''
      bodyContentType='form-urlencoded'
      if (!method) method='POST'
      idx+=2; continue
    }
    if (tok === '-F' || tok === '--form') {
      const fv = cleaned[idx+1] || ''
      if (!body || typeof body!=='object') body = {}
      if (fv.includes('=')) { const [fk,fv2]=fv.split('=',2); body[fk]=fv2.replace(/^@/,'') }
      bodyContentType='multipart-form-data'
      if (!method) method='POST'
      idx+=2; continue
    }
    if (tok === '-u' || tok === '--user') {
      const uv = cleaned[idx+1] || ''
      if (uv.includes(':')) { const [u,p]=uv.split(':',2); auth_username=u; auth_password=p } else auth_username=uv
      auth_type='basic'
      idx+=2; continue
    }
    if (tok === '--url') { url = cleaned[idx+1]; idx+=2; continue }
    if (tok.startsWith('-')) { idx+=1; continue }
    if (!url && (tok.startsWith('http://') || tok.startsWith('https://'))) { url = tok; idx+=1; continue }
    idx+=1
  }
  const result = {}
  if (url) {
    try {
      const u = new URL(url)
      if (u.search) {
        for (const [k,v] of u.searchParams.entries()) query[k]=v
        url = `${u.protocol}//${u.host}${u.pathname}${u.hash||''}`
      }
    } catch {}
    result.url = url
  }
  if (method) result.method = method
  if (Object.keys(headers).length) { result.headers=headers; result.sendHeaders=true }
  if (Object.keys(query).length) { result.query=query; result.sendQuery=true }
  if (body !== null) {
    result.body = body
    result.sendBody = true
    if (bodyContentType==='json') { result.bodyContentType='json'; result.body_format='json'; result.jsonBodyMode = typeof body === 'object' ? 'fields' : 'raw'; if (typeof body==='string') result.rawBody=body }
    else if (bodyContentType==='form-urlencoded') { result.bodyContentType='form-urlencoded'; result.body_format='form' }
    else if (bodyContentType==='multipart-form-data') { result.bodyContentType='multipart-form-data'; result.body_format='multipart' }
    else if (bodyContentType==='raw') { result.bodyContentType='raw'; result.body_format='raw'; if (typeof body==='string') result.rawBody=body }
  }
  if (auth_type!=='none') {
    result.auth_type=auth_type
    if (auth_token) result.auth_token=auth_token
    if (auth_username) result.auth_username=auth_username
    if (auth_password) result.auth_password=auth_password
  }
  return result
}

function KeyValueList({ items, onChange, namePlaceholder = 'Name', valuePlaceholder = 'Value', addLabel = '+ Add Parameter', mapping, onPreview }) {
  const update = (idx, field, val) => {
    const next = [...items]
    next[idx] = { ...next[idx], [field]: val }
    onChange(next)
  }
  const add = () => onChange([...items, { name: '', value: '' }])
  const remove = (idx) => onChange(items.filter((_, i) => i !== idx))
  return (
    <div className="kv-list">
      {items.length === 0 && <p className="hint" style={{ margin: '4px 0' }}>No parameters yet.</p>}
      {items.map((it, idx) => (
        <div key={idx} className="kv-row" style={{ display: 'flex', gap: 6, marginBottom: 6, alignItems: 'flex-start' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <input
              value={it.name}
              onChange={(e) => update(idx, 'name', e.target.value)}
              placeholder={namePlaceholder}
              style={{ width: '100%' }}
            />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            {mapping ? (
              <MappingField schema={{ title: `Value ${idx+1}`, description: valuePlaceholder }} value={it.value} onChange={(v) => update(idx, 'value', v)} path={`value_${idx}`} mapping={mapping} onPreview={onPreview} />
            ) : (
              <input value={it.value} onChange={(e) => update(idx, 'value', e.target.value)} placeholder={valuePlaceholder} style={{ width: '100%' }} />
            )}
          </div>
          <button type="button" className="ghost" onClick={() => remove(idx)} title="Remove" style={{ padding: '6px 8px' }}>✕</button>
        </div>
      ))}
      <button type="button" className="ghost" onClick={add} style={{ marginTop: 4 }}>{addLabel}</button>
    </div>
  )
}

function QueryParamRow({ index, name, value, onNameChange, onValueChange, onRemove, mapping, onPreview }) {
  const [collapsed, setCollapsed] = useState(false)
  const displayName = name ? name : `Parameter ${index + 1}`
  return (
    <div className="fs-param-card">
      <div className="fs-param-card-header" onClick={() => setCollapsed(v => !v)}>
        <span className="fs-param-card-title">
          <span style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8', display: 'inline-block', width: 14, lineHeight: 1 }}>
            {collapsed ? '›' : '⌄'}
          </span>
          <span style={{ fontWeight: 600, color: '#f8fafc' }}>{displayName}</span>
        </span>
        <button
          type="button"
          className="fs-param-card-delete"
          onClick={(e) => {
            e.stopPropagation()
            onRemove()
          }}
          title="Remove parameter"
        >
          ✕
        </button>
      </div>
      {!collapsed && (
        <div className="fs-param-card-body">
          <div>
            {mapping ? (
              <MappingField
                schema={{ title: 'Name', description: 'Query parameter key' }}
                value={name}
                onChange={onNameChange}
                path={`query_${index}_name`}
                mapping={mapping}
                onPreview={onPreview}
              />
            ) : (
              <div>
                <div className="fs-param-field-label">Name</div>
                <input
                  className="fs-param-input"
                  value={name}
                  onChange={(e) => onNameChange(e.target.value)}
                  onBlur={(e) => onNameChange(e.target.value.trim())}
                  placeholder="name"
                />
              </div>
            )}
          </div>
          <div>
            {mapping ? (
              <MappingField
                schema={{ title: 'Value', description: 'Query parameter value or {{ expression }}' }}
                value={value}
                onChange={onValueChange}
                path={`query_${index}_value`}
                mapping={mapping}
                onPreview={onPreview}
              />
            ) : (
              <div>
                <div className="fs-param-field-label">Value</div>
                <input
                  className="fs-param-input"
                  value={value}
                  onChange={(e) => onValueChange(e.target.value)}
                  placeholder="value"
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function HeaderRow({ index, name, value, onNameChange, onValueChange, onRemove, mapping, onPreview }) {
  const [collapsed, setCollapsed] = useState(false)
  const displayName = name ? name : `Header ${index + 1}`
  return (
    <div className="fs-param-card">
      <div className="fs-param-card-header" onClick={() => setCollapsed(v => !v)}>
        <span className="fs-param-card-title">
          <span style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8', display: 'inline-block', width: 14, lineHeight: 1 }}>
            {collapsed ? '›' : '⌄'}
          </span>
          <span style={{ fontWeight: 600, color: '#f8fafc' }}>{displayName}</span>
          {value && <span style={{ fontWeight: 400, color: 'var(--muted)', marginLeft: 4, fontSize: 11 }}>→ {String(value).slice(0, 20)}</span>}
        </span>
        <button
          type="button"
          className="fs-param-card-delete"
          onClick={(e) => {
            e.stopPropagation()
            onRemove()
          }}
          title="Remove header"
        >
          ✕
        </button>
      </div>
      {!collapsed && (
        <div className="fs-param-card-body">
          <div>
            {mapping ? (
              <MappingField schema={{ title: 'Name', description: 'Header name, e.g., Accept or Authorization' }} value={name} onChange={onNameChange} path={`header_${index}_name`} mapping={mapping} onPreview={onPreview} />
            ) : (
              <div>
                <div className="fs-param-field-label">Name</div>
                <input className="fs-param-input" value={name} onChange={(e) => onNameChange(e.target.value)} onBlur={(e) => onNameChange(e.target.value.trim())} placeholder="Accept" />
              </div>
            )}
          </div>
          <div>
            {mapping ? (
              <MappingField schema={{ title: 'Value', description: 'e.g., application/json or Bearer {{$json.token}}' }} value={value} onChange={onValueChange} path={`header_${index}_value`} mapping={mapping} onPreview={onPreview} />
            ) : (
              <div>
                <div className="fs-param-field-label">Value</div>
                <input className="fs-param-input" value={value} onChange={(e) => onValueChange(e.target.value)} placeholder="application/json" />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function ToggleSection({ label, checked, onChange, children, hint }) {
  return (
    <div className="cfg-section open" style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px', marginBottom: 12, background: checked ? 'var(--panel-2)' : 'transparent' }}>
      <div
        className="fs-toggle-header"
        onClick={() => onChange(!checked)}
        style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, userSelect: 'none' }}
      >
        <div className={`fs-switch ${checked ? 'active' : ''}`}>
          <div className="fs-switch-handle" />
        </div>
        <span className="fs-toggle-label">{label}</span>
      </div>
      {hint && <p className="hint" style={{ margin: '4px 0 8px 44px' }}>{hint}</p>}
      {checked && <div style={{ marginTop: 10 }}>{children}</div>}
    </div>
  )
}

export default function HttpRequestNodeEditor({ node, onParamsChange, mapping, onPreview, credentials, credentialTypes, onCredentialChange }) {
  const params = node.parameters || {}
  const [curlOpen, setCurlOpen] = useState(false)
  const [optionsList, setOptionsList] = useState(() => {
    const o = []
    if (params.timeout_seconds !== undefined && params.timeout_seconds !== 30) o.push('timeout')
    if (params.ignore_ssl_issues) o.push('ignore_ssl')
    if (params.follow_redirects === false) o.push('follow_redirects')
    if (params.max_redirects !== undefined && params.max_redirects !== 5) o.push('max_redirects')
    if (params.response_format && params.response_format !== 'auto') o.push('response_format')
    if (params.max_response_bytes && params.max_response_bytes !== 10*1024*1024) o.push('max_response_bytes')
    return o
  })

  const method = params.method || 'GET'
  const url = params.url || ''
  const authentication = params.authentication || (params.predefinedType ? 'predefined' : (params.auth_type && params.auth_type !== 'none' ? 'generic' : 'none'))
  const authType = params.auth_type || 'none'
  const predefinedType = params.predefinedType || ''
  const sendQuery = Boolean(params.sendQuery)
  const sendHeaders = Boolean(params.sendHeaders)
  const sendBody = Boolean(params.sendBody)
  const bodyContentType = params.bodyContentType || (params.body_format === 'form' ? 'form-urlencoded' : params.body_format === 'multipart' ? 'multipart-form-data' : params.body_format === 'raw' ? 'raw' : 'json')
  const jsonBodyMode = params.jsonBodyMode || 'fields'

  const [predefinedList, setPredefinedList] = useState([])
  const [urlError, setUrlError] = useState(null)
  useEffect(() => {
    fetch('/api/credentials/predefined', { headers: { Authorization: `Bearer ${localStorage.getItem('mat_token')}` }}).then(r => r.ok ? r.json().then(j => setPredefinedList(j.data || [])) : null).catch(()=>{})
  }, [])
  useEffect(() => {
    if (!url || url.includes('{{')) { setUrlError(null); return }
    try { const u = new URL(url); if (!['http:','https:'].includes(u.protocol)) setUrlError('URL must start with http:// or https://'); else if (!u.host) setUrlError('URL missing host'); else setUrlError(null) } catch { setUrlError('Invalid URL') }
  }, [url])

  const queryList = useMemo(() => {
    if (params.queryParameters && Array.isArray(params.queryParameters)) return params.queryParameters.map(b => ({ name: b.name || '', value: b.value || '' }))
    return toList(params.query)
  }, [params.query, params.queryParameters])
  const headerList = useMemo(() => {
    if (params.headerParameters && Array.isArray(params.headerParameters)) return params.headerParameters.map(b => ({ name: b.name || '', value: b.value || '' }))
    return toList(params.headers)
  }, [params.headers, params.headerParameters])
  const bodyList = useMemo(() => {
    if (params.bodyParameters && Array.isArray(params.bodyParameters)) return params.bodyParameters.map(b => ({ name: b.name || '', value: b.value || '' }))
    return toList(params.body && typeof params.body === 'object' && !Array.isArray(params.body) ? params.body : {})
  }, [params.body, params.bodyParameters])

  const rawBodyValue = params.rawBody ?? (typeof params.body === 'string' ? params.body : '')

  function patch(obj) {
    onParamsChange({ ...params, ...obj })
  }

  function handleMethodChange(v) {
    patch({ method: v })
  }
  function handleUrlChange(v) {
    patch({ url: v })
  }
  function handleImportCurl(text) {
    if (!text.trim()) return
    const parsed = parseCurlFrontend(text)
    // Merge parsed into current params (parsed wins for fields it provides)
    const next = { ...params, ...parsed }
    // For body list sync: if parsed body is object, ensure bodyParameters derived
    if (parsed.body && typeof parsed.body === 'object' && !Array.isArray(parsed.body)) {
      next.bodyParameters = Object.entries(parsed.body).map(([k,v]) => ({ name: k, value: String(v) }))
    }
    if (parsed.body && typeof parsed.body === 'string') {
      next.rawBody = parsed.body
      next.body = parsed.body
    }
    // Convert query/headers dict to list helpers for persistence (store both)
    if (parsed.query) next.queryParameters = Object.entries(parsed.query).map(([name,value])=>({name,value}))
    if (parsed.headers) next.headerParameters = Object.entries(parsed.headers).map(([name,value])=>({name,value}))
    onParamsChange(next)
  }

  function handleQueryChange(nextList) {
    const dict = fromList(nextList)
    patch({ query: dict, queryParameters: nextList, sendQuery: nextList.length > 0 || sendQuery })
  }
  function handleHeaderChange(nextList) {
    const dict = fromList(nextList)
    patch({ headers: dict, headerParameters: nextList, sendHeaders: nextList.length > 0 || sendHeaders })
  }
  function handleBodyFieldsChange(nextList) {
    const dict = fromList(nextList)
    patch({ body: dict, bodyParameters: nextList })
  }

  const availableOptions = [
    { value: 'timeout', label: 'Timeout' },
    { value: 'ignore_ssl', label: 'Ignore SSL Issues' },
    { value: 'follow_redirects', label: 'Follow Redirects' },
    { value: 'max_redirects', label: 'Max Redirects' },
    { value: 'response_format', label: 'Response Format' },
    { value: 'max_response_bytes', label: 'Max Response Size' },
  ]
  const remainingOptions = availableOptions.filter(o => !optionsList.includes(o.value))

  return (
    <div className="http-editor" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <button type="button" className="ghost" onClick={() => setCurlOpen(true)} style={{ alignSelf: 'flex-start', fontSize: 12, padding: '6px 10px' }}>Import cURL</button>
      <CurlModal open={curlOpen} onClose={() => setCurlOpen(false)} onImport={handleImportCurl} />

      {/* Method */}
      <label>
        <span>Method <span className="required-badge">*</span></span>
        <select value={method} onChange={(e) => handleMethodChange(e.target.value)}>
          {METHODS.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      </label>

      <label>
        <span>URL <span className="required-badge">*</span></span>
        {mapping ? (
          <MappingField schema={{ title: 'URL', description: 'https://api.example.com/users or {{ $json.url }}' }} value={url} onChange={handleUrlChange} path="url" mapping={mapping} onPreview={onPreview} />
        ) : (
          <input value={url} onChange={(e) => handleUrlChange(e.target.value)} placeholder="https://api.example.com/users" style={urlError ? { borderColor: 'var(--red)' } : undefined} />
        )}
        {urlError ? <span className="field-error" style={{ color: 'var(--red)', fontSize: 11 }}>{urlError}</span> : <span className="hint">Supports Fixed value or Expression {'{{ $json.url }}'} — validated before queue.</span>}
      </label>

      {/* Authentication — exactly 3 options per spec */}
      <label>
        <span>Authentication</span>
        <select value={authentication} onChange={(e) => {
          const v = e.target.value
          if (v === 'none') patch({ authentication: 'none', predefinedType: '', auth_type: 'none' })
          else if (v === 'predefined') patch({ authentication: 'predefined', auth_type: 'none' })
          else if (v === 'generic') patch({ authentication: 'generic', auth_type: 'bearer' })
        }}>
          {AUTHENTICATION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </label>

      {authentication === 'predefined' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
          <label>
            <span>Credential Type <span className="required-badge">*</span></span>
            <SearchableSelect
              value={predefinedType}
              onChange={(v) => patch({ predefinedType: v })}
              options={predefinedList.map(p => ({
                value: p.id,
                label: `${p.displayName} (${p.id})`,
                hint: `${p.provider} · ${p.implemented ? 'Implemented' : 'Not implemented'}`,
                disabled: !p.implemented,
                disabledReason: !p.implemented ? 'Not implemented' : undefined
              }))}
              placeholder="Select credential type"
            />
          </label>
          {predefinedType && (() => {
            const pre = predefinedList.find(p => p.id === predefinedType)
            if (!pre) return null
            if (!pre.implemented) {
              return <div className="banner-inline err">Authentication provider not implemented yet — execution will be blocked before queue.</div>
            }
            // Show credential selector for this predefined's credentialType
            const credType = pre.credentialType
            // Also accept related types (e.g. "salesforce" when filtering for "oauth2")
            const relatedTypes = { oauth2: ['oauth2', 'salesforce'], salesforce: ['salesforce', 'oauth2'] }
            const matchTypes = relatedTypes[credType] || [credType]
            const available = credentials ? credentials.filter(c => matchTypes.includes(c.type)) : []
            const currentId = node.credentials?.[credType] || matchTypes.reduce((id, t) => id || node.credentials?.[t], '') || ''
            const currentCred = available.find(c => c.id === currentId)
            const typeMeta = (credentialTypes || []).find(t => t.type === credType)
            const notImpl = typeMeta && typeMeta.implemented === false
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <label>
                  <span>Credential <span className="required-badge">*</span> <span className="hint">({credType})</span></span>
                  <SearchableSelect
                    value={currentId}
                    onChange={(v) => {
                      // Clear previous predefined credential if any
                      if (currentId) {
                        onCredentialChange(credType, '')
                        if (credType !== matchTypes[0]) onCredentialChange(matchTypes[0], '')
                      }
                      if (!v) return
                      // Store under the credential's actual type
                      const selCred = available.find(c => c.id === v)
                      const storeType = selCred ? selCred.type : credType
                      onCredentialChange(storeType, v)
                    }}
                    options={[
                      { value: '', label: 'None' },
                      ...available.map(c => ({
                        value: c.id,
                        label: `${c.name} (${c.type})`,
                        disabled: (credentialTypes || []).find(t => t.type === c.type)?.implemented === false,
                        disabledReason: (credentialTypes || []).find(t => t.type === c.type)?.implemented === false ? 'Not implemented' : undefined
                      }))
                    ]}
                    placeholder={`Select ${credType} credential`}
                  />
                </label>
                {notImpl && <div className="banner-inline err">Credential type not implemented.</div>}
                {currentCred && <span className="hint">Selected: {currentCred.name} — encrypted, not in workflow JSON.</span>}
                {!currentId && <span className="hint">Create a credential of type <code>{credType}</code> or <code>{matchTypes.join('</code> / <code>')}</code> in Credentials.</span>}
              </div>
            )
          })()}
        </div>
      )}

      {authentication === 'generic' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
          <label>
            <span>Generic Auth Type <span className="required-badge">*</span></span>
            <select value={authType} onChange={(e) => patch({ auth_type: e.target.value })}>
              {GENERIC_AUTH_OPTIONS.map(o => {
                const provMap = { basic: 'basic_auth', bearer: 'bearer_auth', header: 'header_auth', query: 'query_auth', digest: 'digest_auth', custom: 'custom_auth', oauth2: 'oauth2', oauth1: 'oauth1' }
                const pt = provMap[o.value] || o.value
                const tm = (credentialTypes || []).find(t => t.type === pt)
                const notImpl = tm && tm.implemented === false
                return <option key={o.value} value={o.value} disabled={!!notImpl}>{o.label}{notImpl ? ' — Not implemented' : ''}</option>
              })}
            </select>
          </label>
          {/* Inline fields for generic auth types */}
          {authType === 'bearer' && (
            <label>
              <span>Token <span className="hint">(or use credential)</span></span>
              <input type="password" value={params.auth_token || ''} onChange={(e) => patch({ auth_token: e.target.value })} placeholder="eyJ..." />
            </label>
          )}
          {authType === 'basic' && (
            <>
              <label><span>Username <span className="required-badge">*</span></span><input value={params.auth_username || ''} onChange={(e) => patch({ auth_username: e.target.value })} placeholder="username" /></label>
              <label><span>Password</span><input type="password" value={params.auth_password || ''} onChange={(e) => patch({ auth_password: e.target.value })} placeholder="password" /></label>
            </>
          )}
          {authType === 'header' && (
            <>
              <label><span>Header Name <span className="required-badge">*</span></span><input value={params.api_key_name || 'X-API-Key'} onChange={(e) => patch({ api_key_name: e.target.value })} placeholder="X-API-Key" /></label>
              <label><span>Header Value</span><input type="password" value={params.auth_token || ''} onChange={(e) => patch({ auth_token: e.target.value })} placeholder="value" /></label>
            </>
          )}
          {authType === 'query' && (
            <>
              <label><span>Parameter Name <span className="required-badge">*</span></span><input value={params.api_key_name || 'api_key'} onChange={(e) => patch({ api_key_name: e.target.value })} placeholder="api_key" /></label>
              <label><span>Parameter Value</span><input type="password" value={params.auth_token || ''} onChange={(e) => patch({ auth_token: e.target.value })} placeholder="value" /></label>
            </>
          )}
          {authType === 'digest' && (
            <>
              <label><span>Username <span className="required-badge">*</span></span><input value={params.auth_username || ''} onChange={(e) => patch({ auth_username: e.target.value })} placeholder="username" /></label>
              <label><span>Password</span><input type="password" value={params.auth_password || ''} onChange={(e) => patch({ auth_password: e.target.value })} placeholder="password" /></label>
              <span className="hint">Digest uses provider; realm/nonce from credential if needed.</span>
            </>
          )}
          {authType === 'custom' && (
            <span className="hint">Custom Auth — define via Custom Auth credential (headers/query). Use credential selector below.</span>
          )}
          {authType === 'oauth2' && (
            <label>
              <span>Access Token <span className="hint">(or credential)</span></span>
              <input type="password" value={params.auth_token || ''} onChange={(e) => patch({ auth_token: e.target.value })} placeholder="oauth token" />
            </label>
          )}
          {authType === 'oauth1' && (
            <>
              <label><span>Consumer Key</span><input value={params.auth_username || ''} onChange={(e) => patch({ auth_username: e.target.value })} placeholder="consumer key" /></label>
              <label><span>Consumer Secret</span><input type="password" value={params.auth_password || ''} onChange={(e) => patch({ auth_password: e.target.value })} placeholder="consumer secret" /></label>
              <label><span>Token</span><input type="password" value={params.auth_token || ''} onChange={(e) => patch({ auth_token: e.target.value })} placeholder="token" /></label>
            </>
          )}
          {/* Credential selector for generic auth */}
          {(() => {
            const relevant = AUTH_CRED_MAP[authType] || []
            const available = credentials ? credentials.filter(c => relevant.includes(c.type)) : []
            const currentEntry = Object.entries(node.credentials || {}).find(([k, v]) => relevant.includes(k) && v)
            const currentId = currentEntry ? currentEntry[1] : ''
            const currentCred = available.find(c => c.id === currentId)
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <label>
                  <span>Credential <span className="hint">({relevant.join('/') || 'none'})</span></span>
                  <SearchableSelect
                    value={currentId || ''}
                    onChange={(v) => {
                      relevant.forEach(rt => { if (node.credentials?.[rt]) onCredentialChange(rt, '') })
                      if (node.credentials?.http && relevant.includes('http')) onCredentialChange('http', '')
                      if (!v) return
                      const sel = credentials.find(c => c.id === v)
                      if (sel) onCredentialChange(sel.type, v)
                      else onCredentialChange(relevant[0] || 'http', v)
                    }}
                    options={[
                      { value: '', label: 'None (use fields above)' },
                      ...available.map(c => {
                        const tm = (credentialTypes || []).find(t => t.type === c.type)
                        return { value: c.id, label: `${c.name} (${c.type})`, disabled: tm && tm.implemented === false, disabledReason: tm && tm.implemented === false ? 'Not implemented' : undefined }
                      })
                    ]}
                    placeholder="Select credential"
                  />
                </label>
                {currentCred && <span className="hint">Selected: {currentCred.name} — encrypted.</span>}
                {available.length === 0 && <span className="hint">No credentials of type {relevant.join(', ')} — create one in Credentials.</span>}
              </div>
            )
          })()}
        </div>
      )}

      {/* Send Query Parameters */}
      <ToggleSection
        label="Send Query Parameters"
        checked={sendQuery}
        onChange={(v) => patch({ sendQuery: v, ...(v ? {} : { query: {}, queryParameters: [], queryJson: '', queryMode: 'fields' }) })}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* Specify Query Parameters Header */}
          <div className="fs-field-header">
            <span className="fs-field-title">Specify Query Parameters</span>
            <div className="fs-field-badge-group">
              <span className="fs-field-dots" title="Options">⋮</span>
              <div className="fs-mode-pill-group">
                <button
                  type="button"
                  className={`fs-mode-pill ${(params.queryMode || 'fields') === 'fields' ? 'active' : ''}`}
                  onClick={() => patch({ queryMode: 'fields' })}
                >
                  Fixed
                </button>
                <button
                  type="button"
                  className={`fs-mode-pill ${(params.queryMode || 'fields') === 'json' ? 'active' : ''}`}
                  onClick={() => patch({ queryMode: 'json' })}
                >
                  Expression
                </button>
              </div>
            </div>
          </div>

          <div className="fs-select-wrap">
            <select
              className="fs-select"
              value={params.queryMode || 'fields'}
              onChange={(e) => patch({ queryMode: e.target.value })}
            >
              <option value="fields">Using Fields Below</option>
              <option value="json">Using JSON</option>
            </select>
            <span className="fs-select-arrow">▾</span>
          </div>

          {(params.queryMode || 'fields') === 'fields' ? (
            <div>
              <div className="fs-items-header">
                <span className="fs-items-title">Query Parameters</span>
                <button
                  type="button"
                  className="fs-items-add-btn"
                  onClick={() => handleQueryChange([...queryList, { name: '', value: '' }])}
                  title="Add query parameter"
                >
                  +
                </button>
              </div>

              {queryList.length === 0 && (
                <p className="hint" style={{ margin: '4px 0 8px' }}>No query parameters yet. Click + to add one.</p>
              )}

              {queryList.map((it, idx) => (
                <QueryParamRow
                  key={idx}
                  index={idx}
                  name={it.name}
                  value={it.value}
                  onNameChange={(v) => {
                    const next = [...queryList]
                    next[idx] = { ...next[idx], name: v }
                    handleQueryChange(next)
                  }}
                  onValueChange={(v) => {
                    const next = [...queryList]
                    next[idx] = { ...next[idx], value: v }
                    handleQueryChange(next)
                  }}
                  onRemove={() => handleQueryChange(queryList.filter((_, i) => i !== idx))}
                  mapping={mapping}
                  onPreview={onPreview}
                />
              ))}

              <button
                type="button"
                className="ghost"
                onClick={() => handleQueryChange([...queryList, { name: '', value: '' }])}
                style={{ marginTop: 4, fontSize: 12 }}
              >
                + Add Parameter
              </button>
            </div>
          ) : (
            <div>
              <label>
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>JSON / Expression</span>
                <textarea
                  rows={6}
                  value={params.queryJson || (params.query && Object.keys(params.query).length ? JSON.stringify(params.query, null, 2) : '{\n  "updated_after": "{{ $(\'Code in JavaScript\').item.json.currentDateTime }}"\n}')}
                  onChange={(e) => patch({ queryJson: e.target.value, queryMode: 'json', sendQuery: true })}
                  placeholder={'{\n  "updated_after": "{{ $(\'Code in JavaScript\').item.json.currentDateTime }}"\n}'}
                  style={{ width: '100%', fontFamily: 'ui-monospace, monospace', fontSize: 12, marginTop: 4 }}
                />
              </label>
              <span className="hint">Must be a JSON object. Expressions like {"{{ ... }}"} will be resolved before sending.</span>
            </div>
          )}
        </div>
      </ToggleSection>

      <ToggleSection
        label="Send Headers"
        checked={sendHeaders}
        onChange={(v) => {
          if (v) patch({ sendHeaders: true })
          else patch({ sendHeaders: false, headers: {}, headerParameters: [], headerJson: '', headerMode: 'fields' })
        }}
        hint="Custom HTTP headers"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="fs-field-header">
            <span className="fs-field-title">Specify Headers</span>
            <div className="fs-field-badge-group">
              <span className="fs-field-dots" title="Options">⋮</span>
              <div className="fs-mode-pill-group">
                <button
                  type="button"
                  className={`fs-mode-pill ${(params.headerMode || 'fields') === 'fields' ? 'active' : ''}`}
                  onClick={() => patch({ headerMode: 'fields' })}
                >
                  Fixed
                </button>
                <button
                  type="button"
                  className={`fs-mode-pill ${(params.headerMode || 'fields') === 'json' ? 'active' : ''}`}
                  onClick={() => patch({ headerMode: 'json' })}
                >
                  Expression
                </button>
              </div>
            </div>
          </div>

          <div className="fs-select-wrap">
            <select
              className="fs-select"
              value={params.headerMode || 'fields'}
              onChange={(e) => patch({ headerMode: e.target.value })}
            >
              <option value="fields">Using Fields Below</option>
              <option value="json">Using JSON</option>
            </select>
            <span className="fs-select-arrow">▾</span>
          </div>

          {(params.headerMode || 'fields') === 'fields' ? (
            <div>
              <div className="fs-items-header">
                <span className="fs-items-title">Headers</span>
                <button
                  type="button"
                  className="fs-items-add-btn"
                  onClick={() => handleHeaderChange([...headerList, { name: '', value: '' }])}
                  title="Add header"
                >
                  +
                </button>
              </div>
              {headerList.length === 0 && <p className="hint" style={{ margin: '4px 0' }}>No headers yet. Add one.</p>}
              {headerList.map((it, idx) => (
                <HeaderRow
                  key={idx}
                  index={idx}
                  name={it.name}
                  value={it.value}
                  onNameChange={(v) => {
                    const next = [...headerList]
                    next[idx] = { ...next[idx], name: v }
                    handleHeaderChange(next)
                  }}
                  onValueChange={(v) => {
                    const next = [...headerList]
                    next[idx] = { ...next[idx], value: v }
                    handleHeaderChange(next)
                  }}
                  onRemove={() => handleHeaderChange(headerList.filter((_, i) => i !== idx))}
                  mapping={mapping}
                  onPreview={onPreview}
                />
              ))}
              <button type="button" className="ghost" onClick={() => handleHeaderChange([...headerList, { name: '', value: '' }])} style={{ marginTop: 8, fontSize: 12 }}>+ Add Header</button>
            </div>
          ) : (
            <div>
              <label>
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>Headers JSON</span>
                <textarea
                  rows={6}
                  value={params.headerJson || (params.headers && Object.keys(params.headers).length ? JSON.stringify(params.headers, null, 2) : '{\n  "Accept": "application/json"\n}')}
                  onChange={(e) => patch({ headerJson: e.target.value, headerMode: 'json', sendHeaders: true })}
                  placeholder={'{\n  "Accept": "application/json",\n  "Authorization": "Bearer {{$json.token}}"\n}'}
                  style={{ width: '100%', fontFamily: 'ui-monospace, monospace', fontSize: 12, marginTop: 4 }}
                />
              </label>
              <span className="hint">Must be a JSON object. Expressions like {"{{$json.token}}"} will be resolved before sending. Invalid JSON will be rejected.</span>
            </div>
          )}
        </div>
      </ToggleSection>

      <ToggleSection label="Send Body" checked={sendBody} onChange={(v) => patch({ sendBody: v, ...(v ? {} : { body: null, rawBody: '', bodyParameters: [] }) })} hint="Request body (not for GET/HEAD)">
        <div style={{ borderLeft: '2px solid var(--border)', paddingLeft: 8 }}>
          <label>
            <span>Body Content Type</span>
            <select value={bodyContentType} onChange={(e) => {
              const ct = e.target.value
              const map = { 'json': 'json', 'form-urlencoded': 'form', 'multipart-form-data': 'multipart', 'raw': 'raw' }
              patch({ bodyContentType: ct, body_format: map[ct] || 'json' })
            }}>
              {BODY_CONTENT_TYPES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>

          {bodyContentType === 'json' && (
            <>
              <label>
                <span>Specify Body</span>
                <select value={jsonBodyMode} onChange={(e) => patch({ jsonBodyMode: e.target.value })}>
                  <option value="fields">Using Fields Below</option>
                  <option value="raw">Using JSON</option>
                </select>
              </label>
              {jsonBodyMode === 'fields' ? (
                <>
                  <p className="hint" style={{ margin: '6px 0' }}>Add fields to build JSON: {'{'} name: value, ... {'}'}</p>
                  <KeyValueList items={bodyList} onChange={handleBodyFieldsChange} namePlaceholder="Name" valuePlaceholder="Value" addLabel="+ Add Field" mapping={mapping} onPreview={onPreview} />
                </>
              ) : (
                <label>
                  <span>JSON / Raw</span>
                  <textarea rows={6} value={rawBodyValue} onChange={(e) => patch({ rawBody: e.target.value, body: e.target.value, jsonBodyMode: 'raw', bodyContentType: 'json', body_format: 'json' })} placeholder={'{\n  "name": "{{ $json.name }}",\n  "email": "{{ $json.email }}"\n}'} style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }} />
                  <span className="hint">Supports expressions. Invalid JSON will be rejected before execution.</span>
                </label>
              )}
            </>
          )}

          {bodyContentType === 'form-urlencoded' && (
            <>
              <p className="hint" style={{ margin: '6px 0' }}>application/x-www-form-urlencoded</p>
              <KeyValueList items={bodyList} onChange={handleBodyFieldsChange} addLabel="+ Add Field" mapping={mapping} onPreview={onPreview} />
            </>
          )}

          {bodyContentType === 'multipart-form-data' && (
            <>
              <p className="hint" style={{ margin: '6px 0' }}>multipart/form-data — text fields (files via binary upcoming)</p>
              <KeyValueList items={bodyList} onChange={handleBodyFieldsChange} addLabel="+ Add Field" mapping={mapping} onPreview={onPreview} />
              <p className="hint">Boundary is auto-generated; do not set manually.</p>
            </>
          )}

          {bodyContentType === 'raw' && (
            <label>
              <span>Raw Body</span>
              <textarea rows={6} value={rawBodyValue} onChange={(e) => patch({ rawBody: e.target.value, body: e.target.value })} placeholder="hello world or <request><name>John</name></request>" style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }} />
              <span className="hint">Sent as-is. Set Content-Type via Headers if needed.</span>
            </label>
          )}
        </div>
      </ToggleSection>

      {/* Options */}
      <div className="cfg-section open" style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '8px 10px', background: 'var(--panel-2)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 600, fontSize: 12, textTransform: 'uppercase', color: 'var(--muted)' }}>Options</span>
          {remainingOptions.length > 0 && (
            <select
              value=""
              onChange={(e) => {
                if (e.target.value) setOptionsList([...optionsList, e.target.value])
              }}
              style={{ fontSize: 12, padding: '4px 8px' }}
            >
              <option value="">+ Add option</option>
              {remainingOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          )}
        </div>
        {optionsList.length === 0 && <p className="hint" style={{ marginTop: 6 }}>No options added.</p>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          {optionsList.includes('timeout') && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <label style={{ flex: 1 }}><span>Timeout (seconds)</span><input type="number" min={1} max={300} value={params.timeout_seconds ?? 30} onChange={(e) => patch({ timeout_seconds: Number(e.target.value) })} /></label>
              <button type="button" className="ghost" onClick={() => { setOptionsList(optionsList.filter(v => v !== 'timeout')); patch({ timeout_seconds: 30 }) }} title="Remove">✕</button>
            </div>
          )}
          {optionsList.includes('ignore_ssl') && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <label className="check" style={{ flex: 1 }}><input type="checkbox" checked={Boolean(params.ignore_ssl_issues)} onChange={(e) => patch({ ignore_ssl_issues: e.target.checked })} /><span>Ignore SSL Issues</span></label>
              <button type="button" className="ghost" onClick={() => { setOptionsList(optionsList.filter(v => v !== 'ignore_ssl')); patch({ ignore_ssl_issues: false }) }} title="Remove">✕</button>
            </div>
          )}
          {optionsList.includes('ignore_ssl') && params.ignore_ssl_issues && (
            <p className="hint" style={{ color: 'var(--red)', marginTop: -4 }}>⚠ Disables TLS verification — insecure. Use only for testing.</p>
          )}
          {optionsList.includes('follow_redirects') && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <label className="check" style={{ flex: 1 }}><input type="checkbox" checked={params.follow_redirects !== false} onChange={(e) => patch({ follow_redirects: e.target.checked })} /><span>Follow Redirects</span></label>
              <button type="button" className="ghost" onClick={() => { setOptionsList(optionsList.filter(v => v !== 'follow_redirects')); patch({ follow_redirects: true }) }} title="Remove">✕</button>
            </div>
          )}
          {optionsList.includes('max_redirects') && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <label style={{ flex: 1 }}><span>Max Redirects</span><input type="number" min={0} max={20} value={params.max_redirects ?? 5} onChange={(e) => patch({ max_redirects: Number(e.target.value) })} /></label>
              <button type="button" className="ghost" onClick={() => { setOptionsList(optionsList.filter(v => v !== 'max_redirects')); patch({ max_redirects: 5 }) }} title="Remove">✕</button>
            </div>
          )}
          {optionsList.includes('response_format') && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <label style={{ flex: 1 }}><span>Response Format</span><select value={params.response_format || 'auto'} onChange={(e) => patch({ response_format: e.target.value })}>{RESPONSE_FORMATS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
              <button type="button" className="ghost" onClick={() => { setOptionsList(optionsList.filter(v => v !== 'response_format')); patch({ response_format: 'auto' }) }} title="Remove">✕</button>
            </div>
          )}
          {optionsList.includes('max_response_bytes') && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <label style={{ flex: 1 }}><span>Max Response Bytes</span><input type="number" min={1024} value={params.max_response_bytes ?? 10*1024*1024} onChange={(e) => patch({ max_response_bytes: Number(e.target.value) })} /></label>
              <button type="button" className="ghost" onClick={() => { setOptionsList(optionsList.filter(v => v !== 'max_response_bytes')); patch({ max_response_bytes: 10*1024*1024 }) }} title="Remove">✕</button>
            </div>
          )}
        </div>
      </div>

      <p className="hint">Credentials are redacted in logs. Use expressions for dynamic values: {'{{ $json.field }}'}</p>
    </div>
  )
}
