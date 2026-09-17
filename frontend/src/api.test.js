import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { getToken, setToken, ApiError, api } from './api.js'

// --- localStorage mock ---
const store = {}
const mockStorage = {
  getItem: vi.fn((k) => store[k] ?? null),
  setItem: vi.fn((k, v) => { store[k] = v }),
  removeItem: vi.fn((k) => { delete store[k] }),
}
Object.defineProperty(globalThis, 'localStorage', { value: mockStorage, writable: true })

// --- window mock (for auth:expired event) ---
const mockDispatchEvent = vi.fn()
if (!globalThis.window) {
  globalThis.window = { dispatchEvent: mockDispatchEvent }
} else {
  globalThis.window.dispatchEvent = mockDispatchEvent
}

// --- fetch mock ---
let fetchMock
beforeEach(() => {
  fetchMock = vi.fn()
  globalThis.fetch = fetchMock
  Object.keys(store).forEach((k) => delete store[k])
  mockStorage.getItem.mockClear()
  mockStorage.setItem.mockClear()
  mockStorage.removeItem.mockClear()
  mockDispatchEvent.mockClear()
})
afterEach(() => { vi.restoreAllMocks() })

function mockFetchSuccess(data, meta) {
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify({ data, meta })),
  })
}

function mockFetchError(status, detail) {
  fetchMock.mockResolvedValue({
    ok: false,
    status,
    text: () => Promise.resolve(JSON.stringify({ detail })),
  })
}

function mockFetchNetworkError() {
  fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
}

// ---- getToken / setToken ----

describe('getToken', () => {
  it('returns token from localStorage', () => {
    store.mat_token = 'abc123'
    expect(getToken()).toBe('abc123')
  })
  it('returns null when no token', () => {
    expect(getToken()).toBeNull()
  })
})

describe('setToken', () => {
  it('stores token in localStorage', () => {
    setToken('xyz')
    expect(mockStorage.setItem).toHaveBeenCalledWith('mat_token', 'xyz')
  })
  it('removes token when called with falsy value', () => {
    store.mat_token = 'old'
    setToken(null)
    expect(mockStorage.removeItem).toHaveBeenCalledWith('mat_token')
  })
  it('does nothing when called with empty string', () => {
    setToken('')
    expect(mockStorage.removeItem).toHaveBeenCalledWith('mat_token')
  })
})

// ---- ApiError ----

describe('ApiError', () => {
  it('formats array detail with message field', () => {
    const err = new ApiError(422, [{ message: 'bad input' }])
    expect(err.message).toBe('bad input')
    expect(err.status).toBe(422)
    expect(err.detail).toEqual([{ message: 'bad input' }])
  })

  it('formats array detail with msg field', () => {
    const err = new ApiError(400, [{ msg: 'oops' }])
    expect(err.message).toBe('oops')
  })

  it('formats array detail with no message/msg (JSON stringify)', () => {
    const err = new ApiError(400, [{ code: 'ERR' }])
    expect(err.message).toContain('"code"')
  })

  it('formats string detail', () => {
    const err = new ApiError(500, 'server boom')
    expect(err.message).toBe('server boom')
  })

  it('formats non-string non-array detail', () => {
    const err = new ApiError(500, { error: true })
    expect(err.message).toContain('"error"')
  })

  it('is an instance of Error', () => {
    const err = new ApiError(400, 'x')
    expect(err).toBeInstanceOf(Error)
  })
})

// ---- api methods ----

describe('api.register', () => {
  it('sends POST /api/auth/register with email and password', async () => {
    mockFetchSuccess({ token: 'tok', user: { id: 1 } })
    const result = await api.register('a@b.com', 'pass')
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/register', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ email: 'a@b.com', password: 'pass' }),
    }))
    expect(result).toEqual({ token: 'tok', user: { id: 1 } })
  })
})

describe('api.login', () => {
  it('sends POST /api/auth/login', async () => {
    mockFetchSuccess({ token: 'tok' })
    await api.login('a@b.com', 'pass')
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/login', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ email: 'a@b.com', password: 'pass' }),
    }))
  })
})

describe('api.listWorkflows', () => {
  it('sends GET with pageSize=100', async () => {
    mockFetchSuccess([])
    await api.listWorkflows()
    expect(fetchMock).toHaveBeenCalledWith('/api/workflows?pageSize=100', expect.objectContaining({ method: 'GET' }))
  })
})

describe('api.createWorkflow', () => {
  it('sends POST with workflow body', async () => {
    mockFetchSuccess({ id: 'wf1' })
    const wf = { id: 'wf1', name: 'test' }
    await api.createWorkflow(wf)
    expect(fetchMock).toHaveBeenCalledWith('/api/workflows', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify(wf),
    }))
  })
})

describe('api.getWorkflow', () => {
  it('sends GET to correct path', async () => {
    mockFetchSuccess({ id: 'wf1' })
    await api.getWorkflow('wf1')
    expect(fetchMock).toHaveBeenCalledWith('/api/workflows/wf1', expect.objectContaining({ method: 'GET' }))
  })
})

describe('api.saveWorkflow', () => {
  it('sends PUT with body', async () => {
    mockFetchSuccess({ id: 'wf1' })
    await api.saveWorkflow('wf1', { name: 'x' })
    expect(fetchMock).toHaveBeenCalledWith('/api/workflows/wf1', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ name: 'x' }),
    }))
  })
})

describe('api.deleteWorkflow', () => {
  it('sends DELETE', async () => {
    mockFetchSuccess(null)
    await api.deleteWorkflow('wf1')
    expect(fetchMock).toHaveBeenCalledWith('/api/workflows/wf1', expect.objectContaining({ method: 'DELETE' }))
  })
})

describe('api.run', () => {
  it('sends POST with empty body', async () => {
    mockFetchSuccess({ execution_id: 'exec1' })
    await api.run('wf1')
    expect(fetchMock).toHaveBeenCalledWith('/api/workflows/wf1/run', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({}),
    }))
  })
})

describe('api.cancel', () => {
  it('sends POST to cancel endpoint', async () => {
    mockFetchSuccess({ status: 'cancelling' })
    await api.cancel('exec1')
    expect(fetchMock).toHaveBeenCalledWith('/api/executions/exec1/cancel', expect.objectContaining({ method: 'POST' }))
  })
})

describe('api.retry', () => {
  it('sends POST with empty body', async () => {
    mockFetchSuccess({ execution_id: 'exec2' })
    await api.retry('exec1')
    expect(fetchMock).toHaveBeenCalledWith('/api/executions/exec1/retry', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({}),
    }))
  })
})

describe('api.listExecutions', () => {
  it('builds query string from params', async () => {
    mockFetchSuccess([])
    await api.listExecutions({ workflowId: 'wf1', page: 2, pageSize: 10 })
    const url = fetchMock.mock.calls[0][0]
    expect(url).toContain('workflow_id=wf1')
    expect(url).toContain('page=2')
    expect(url).toContain('pageSize=10')
  })

  it('omits empty params', async () => {
    mockFetchSuccess([])
    await api.listExecutions({})
    expect(fetchMock).toHaveBeenCalledWith('/api/executions', expect.anything())
  })

  it('uses requestEnvelope (returns data+meta)', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify({ data: [{ id: 1 }], meta: { total: 1 } })),
    })
    const result = await api.listExecutions()
    expect(result).toEqual({ data: [{ id: 1 }], meta: { total: 1 } })
  })
})

describe('api.salesforceConnect', () => {
  it('sends login_url when provided', async () => {
    mockFetchSuccess({ authorize_url: 'http://sf' })
    await api.salesforceConnect('https://login.salesforce.com')
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/salesforce/connect', expect.objectContaining({
      body: JSON.stringify({ login_url: 'https://login.salesforce.com' }),
    }))
  })

  it('sends empty body when no loginUrl', async () => {
    mockFetchSuccess({ authorize_url: 'http://sf' })
    await api.salesforceConnect(null)
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/salesforce/connect', expect.objectContaining({
      body: JSON.stringify({}),
    }))
  })
})

describe('api.explain', () => {
  it('sends execution_id in body', async () => {
    mockFetchSuccess({ explanation: 'ok' })
    await api.explain('exec1')
    expect(fetchMock).toHaveBeenCalledWith('/api/ai/explain', expect.objectContaining({
      body: JSON.stringify({ execution_id: 'exec1' }),
    }))
  })
})

describe('api.salesforce discovery (Phase 9)', () => {
  it('salesforceObjects hits the discovery endpoint without refresh by default', async () => {
    mockFetchSuccess({ sobjects: [{ name: 'Account' }] })
    await api.salesforceObjects()
    expect(fetchMock).toHaveBeenCalledWith('/api/connectors/salesforce/objects', expect.anything())
  })

  it('salesforceObjects passes refresh=true when asked', async () => {
    mockFetchSuccess({ sobjects: [] })
    await api.salesforceObjects(true)
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/connectors/salesforce/objects?refresh=true')
  })

  it('salesforceObjectSchema URL-encodes the object name', async () => {
    mockFetchSuccess({ fields: [] })
    await api.salesforceObjectSchema('My_Object__c')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/connectors/salesforce/schema/My_Object__c',
      expect.anything(),
    )
  })

  it('salesforceObjectSchema appends refresh flag', async () => {
    mockFetchSuccess({ fields: [] })
    await api.salesforceObjectSchema('Lead', true)
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/connectors/salesforce/schema/Lead?refresh=true')
  })
})

describe('api.generateWorkflow', () => {
  it('sends prompt in body', async () => {
    mockFetchSuccess({ nodes: [] })
    await api.generateWorkflow('make a flow')
    expect(fetchMock).toHaveBeenCalledWith('/api/ai/generate-workflow', expect.objectContaining({
      body: JSON.stringify({ prompt: 'make a flow' }),
    }))
  })
})

describe('ai assistant endpoints (Phase 16)', () => {
  it('suggestMapping posts workflow + node ids', async () => {
    mockFetchSuccess({ mapping: {} })
    await api.suggestMapping({ workflow_id: 'wf_1', node_id: 'n1', intent: 'map name' })
    expect(fetchMock).toHaveBeenCalledWith('/api/ai/suggest-mapping', expect.objectContaining({
      body: JSON.stringify({ workflow_id: 'wf_1', node_id: 'n1', intent: 'map name' }),
    }))
  })

  it('suggestExpression posts description and sample', async () => {
    mockFetchSuccess({ expression: '' })
    await api.suggestExpression({ description: 'upper', sample_item: { a: 1 } })
    expect(fetchMock).toHaveBeenCalledWith('/api/ai/suggest-expression', expect.objectContaining({
      body: JSON.stringify({ description: 'upper', sample_item: { a: 1 } }),
    }))
  })

  it('suggestNodeConfig posts node type, operation and intent', async () => {
    mockFetchSuccess({ parameters: {} })
    await api.suggestNodeConfig({ node_type: 'salesforce', operation: 'query', intent: 'find lead' })
    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(init.body)
    expect(body).toEqual({ node_type: 'salesforce', operation: 'query', intent: 'find lead' })
    expect(init.url ?? fetchMock.mock.calls[0][0]).toBe('/api/ai/suggest-node-config')
  })

  it('optimize/explain/document post the workflow id only', async () => {
    mockFetchSuccess({})
    for (const [fn, path] of [
      [api.optimizeWorkflow, '/api/ai/optimize-workflow'],
      [api.explainWorkflow, '/api/ai/explain-workflow'],
      [api.documentWorkflow, '/api/ai/document-workflow'],
    ]) {
      fetchMock.mockClear()
      await fn('wf_9')
      const [url] = fetchMock.mock.calls[0]
      expect(url).toBe(path)
      const body = JSON.parse(fetchMock.mock.calls[0][1].body)
      expect(body.workflow_id).toBe('wf_9')
    }
  })
})

describe('rag endpoints (Phase 18)', () => {
  it('collection CRUD hits the right URLs', async () => {
    mockFetchSuccess({ id: 'rc_1' })
    await api.createRagCollection({ name: 'kb' })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/rag/collections')

    await api.deleteRagCollection('rc_1')
    const [delUrl, delInit] = fetchMock.mock.calls.at(-1)
    expect(delUrl).toBe('/api/rag/collections/rc_1')
    expect(delInit.method).toBe('DELETE')
  })

  it('ingest posts documents; query posts query params', async () => {
    mockFetchSuccess({ chunks_upserted: 1 })
    await api.ragIngest('rc_1', { documents: [{ text: 'hi' }] })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/rag/collections/rc_1/documents')

    mockFetchSuccess({ hits: [] })
    await api.ragQuery('rc_1', { query: 'q', top_k: 5 })
    const [url, init] = fetchMock.mock.calls.at(-1)
    expect(url).toBe('/api/rag/collections/rc_1/query')
    const body = JSON.parse(init.body)
    expect(body).toEqual({ query: 'q', top_k: 5 })
  })
})

// ---- Auth header ----

describe('authorization header', () => {
  it('includes Bearer token when set', async () => {
    store.mat_token = 'mytoken'
    mockFetchSuccess({})
    await api.listWorkflows()
    const headers = fetchMock.mock.calls[0][1].headers
    expect(headers.Authorization).toBe('Bearer mytoken')
  })

  it('omits Authorization when no token', async () => {
    mockFetchSuccess({})
    await api.listWorkflows()
    const headers = fetchMock.mock.calls[0][1].headers
    expect(headers).not.toHaveProperty('Authorization')
  })
})

// ---- Error handling ----

describe('error handling', () => {
  it('throws ApiError on non-ok response', async () => {
    mockFetchError(404, { detail: 'not found' })
    await expect(api.getWorkflow('x')).rejects.toThrow(ApiError)
    try {
      await api.getWorkflow('x')
    } catch (e) {
      expect(e.status).toBe(404)
    }
  })

  it('throws ApiError(0) on network failure', async () => {
    mockFetchNetworkError()
    await expect(api.listWorkflows()).rejects.toThrow(ApiError)
    try {
      await api.listWorkflows()
    } catch (e) {
      expect(e.status).toBe(0)
      expect(e.message).toContain('Cannot reach the server')
    }
  })

  it('clears token and dispatches auth:expired on 401', async () => {
    store.mat_token = 'expired'
    mockFetchError(401, 'unauthorized')
    await expect(api.listWorkflows()).rejects.toThrow()
    expect(mockStorage.removeItem).toHaveBeenCalledWith('mat_token')
    expect(mockDispatchEvent).toHaveBeenCalledWith(expect.any(Event))
  })
})

// ---- Approvals / templates / env endpoints (Phase 32) ----

describe('resume endpoint', () => {
  it('posts the decision as JSON body', async () => {
    store.mat_token = 't'
    mockFetchSuccess({ id: 'exec_1', status: 'queued' })
    await api.resume('exec_1', false)
    const [path, init] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/executions/exec_1/resume')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ approved: false })
  })

  it('defaults to approved=true', async () => {
    mockFetchSuccess({})
    await api.resume('exec_2')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ approved: true })
  })
})

describe('listExecutions status filter', () => {
  it('passes status as a query parameter', async () => {
    mockFetchSuccess([], { page: 1, pageSize: 25, total: 0 })
    await api.listExecutions({ status: 'waiting_approval' })
    expect(fetchMock.mock.calls[0][0]).toContain('status=waiting_approval')
  })

  it('omits the param when not requested', async () => {
    mockFetchSuccess([])
    await api.listExecutions()
    expect(fetchMock.mock.calls[0][0]).not.toContain('status=')
  })
})

describe('templates endpoints', () => {
  it('lists templates', async () => {
    mockFetchSuccess([{ id: 1, name: 'T' }])
    const data = await api.listTemplates()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/templates')
    expect(data[0].name).toBe('T')
  })

  it('useTemplate posts to /use and returns workflow data', async () => {
    mockFetchSuccess({ workflow_data: { nodes: [], connections: [] } })
    const data = await api.useTemplate(7)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/templates/7/use')
    expect(data.workflow_data).toBeDefined()
  })
})

describe('environment endpoints', () => {
  it('lists env vars per workspace', async () => {
    mockFetchSuccess([{ key: 'API_URL' }])
    await api.listEnvVars('ws_1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/environments/ws_1')
  })

  it('upserts with workspace scoping + secret flag', async () => {
    mockFetchSuccess({ id: 1 })
    await api.upsertEnvVar({ workspace_id: 'ws_1', key: 'K', value: 'v', is_secret: true })
    const [path, init] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/environments')
    expect(JSON.parse(init.body)).toEqual({ workspace_id: 'ws_1', key: 'K', value: 'v', is_secret: true })
  })

  it('deletes by id', async () => {
    mockFetchSuccess({ deleted: true })
    await api.deleteEnvVar(3)
    expect(fetchMock.mock.calls[0]).toMatchObject(['/api/environments/3', { method: 'DELETE' }])
  })

  it('lists workspaces for the selector', async () => {
    mockFetchSuccess([{ id: 'ws_1' }])
    await api.listWorkspaces()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/workspaces?pageSize=100')
  })
})

describe('ai assistant superpowers', () => {
  it('calls documentWorkflow endpoint', async () => {
    mockFetchSuccess({ markdown: '# Doc', mermaid: 'graph TD' })
    const res = await api.documentWorkflow('wf_123')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/ai/document-workflow')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ workflow_id: 'wf_123' })
    expect(res.mermaid).toBe('graph TD')
  })

  it('calls autoFixNode endpoint', async () => {
    mockFetchSuccess({
      root_cause: 'Malformed URL',
      suggested_parameters: { url: 'https://api.com' },
      changes_summary: 'Added https',
    })
    const res = await api.autoFixNode({
      workflow_id: 'wf_123',
      node_id: 'node_456',
      error_message: 'Invalid URL',
    })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/ai/auto-fix')
    expect(res.suggested_parameters.url).toBe('https://api.com')
  })
})

