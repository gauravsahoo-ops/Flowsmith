import { ApiError, api, getToken, setToken } from '../../api'

// Minimal API client for durable tool approvals. The approval endpoints
// return the same {data, meta} envelope as the rest of the API, so this
// mirrors the auth/error handling in ../../api.js without changing the shared
// client (approvals were added after the main client was frozen).
async function request(method, path, body) {
  const headers = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Is the backend running?')
  }

  if (response.status === 401) {
    setToken(null)
    if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
      window.dispatchEvent(new Event('auth:expired'))
    }
  }

  const text = await response.text()
  let payload = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    if (!response.ok) {
      throw new ApiError(response.status, text || `Request failed (${response.status})`)
    }
    throw new ApiError(response.status, 'Invalid response from the server')
  }

  if (!response.ok) {
    throw new ApiError(response.status, payload?.detail ?? payload?.message ?? `Request failed (${response.status})`)
  }
  return payload?.data
}

export function listApprovals({ status = 'pending', limit = 50 } = {}) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (limit) params.set('limit', String(limit))
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return request('GET', `/approvals${suffix}`)
}

export function getApproval(requestId) {
  if (!requestId) return Promise.reject(new ApiError(400, 'Approval request id is required.'))
  return request('GET', `/approvals/${encodeURIComponent(requestId)}`)
}

export function decideApproval(requestId, { approved, nonce, comment = '' } = {}) {
  if (!requestId) return Promise.reject(new ApiError(400, 'Approval request id is required.'))
  if (typeof approved !== 'boolean') {
    return Promise.reject(new ApiError(400, 'An approval decision is required.'))
  }
  if (typeof nonce !== 'string' || nonce.length < 8 || nonce.length > 128) {
    return Promise.reject(new ApiError(400, 'A decision nonce between 8 and 128 characters is required.'))
  }
  return request('POST', `/approvals/${encodeURIComponent(requestId)}/decide`, {
    approved,
    nonce,
    comment: String(comment || '').slice(0, 2000),
  })
}

// Recording a decision does not resume the paused execution. This helper is
// the explicit second step, delegating to the shared execution-resume client
// so approvals surface the same 403/404/409 errors as the Run pauses tab.
export function resumeApprovalRun(runId, approved) {
  if (!runId) return Promise.reject(new ApiError(400, 'Execution id is required.'))
  if (typeof approved !== 'boolean') {
    return Promise.reject(new ApiError(400, 'An approval decision is required.'))
  }
  return api.resume(runId, approved)
}
