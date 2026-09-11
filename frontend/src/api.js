// Tiny fetch wrapper: attaches the JWT, unwraps the {data, meta}
// envelope, and redirects to login on 401.

const TOKEN_KEY = 'mat_token'
const DEFAULT_TIMEOUT_MS = 30000

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(status, detail) {
    const msg = Array.isArray(detail)
      ? detail.map((d) => d.message || d.msg || JSON.stringify(d)).join('; ')
      : typeof detail === 'string' ? detail : JSON.stringify(detail)
    super(msg)
    this.status = status
    this.detail = detail
  }
}

async function request(method, path, body, opts) {
  const { data } = await requestEnvelope(method, path, body, opts)
  return data
}

async function requestEnvelope(method, path, body, opts = {}) {
  const { timeout = DEFAULT_TIMEOUT_MS } = opts
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)

  let resp
  try {
    resp = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new ApiError(0, `Request timed out after ${timeout / 1000}s`)
    }
    throw new ApiError(0, 'Cannot reach the server. Is the backend running?')
  } finally {
    clearTimeout(timer)
  }

  if (resp.status === 401) {
    // Only clear token and redirect if this 401 came from Flowsmith user auth,
    // NOT from third-party connectors or external integration errors (e.g. Salesforce, HTTP requests).
    const isExternalConnector = path.startsWith('/connectors') || path.startsWith('/executions')
    if (!isExternalConnector) {
      setToken(null)
      window.dispatchEvent(new Event('auth:expired'))
    }
  }
  const text = await resp.text()
  let parsed = null
  try {
    parsed = text ? JSON.parse(text) : null
  } catch {
    // Non-JSON response (HTML error page, proxy 502/503, etc.)
    if (!resp.ok) throw new ApiError(resp.status, text || `Server error (${resp.status})`)
    throw new ApiError(resp.status, 'Invalid response from server')
  }
  if (!resp.ok) throw new ApiError(resp.status, parsed?.detail ?? text)
  return { data: parsed?.data, meta: parsed?.meta }
}

export const api = {
  register: (email, password) => request('POST', '/auth/register', { email, password }),
  login: (email, password) => request('POST', '/auth/login', { email, password }),
  getSsoProviders: () => request('GET', '/auth/sso/providers'),
  forgotPassword: (email) => request('POST', '/auth/forgot-password', { email }),
  resetPassword: (token, newPassword) =>
    request('POST', '/auth/reset-password', { token, new_password: newPassword }),
  listWorkflows: () => request('GET', '/workflows?pageSize=100'),
  listWorkflowsPaged: (params = {}) => {
    const q = new URLSearchParams()
    if (params.page) q.set('page', String(params.page))
    if (params.pageSize) q.set('pageSize', String(params.pageSize))
    if (params.search) q.set('search', params.search)
    const suffix = q.size ? `?${q.toString()}` : ''
    return requestEnvelope('GET', `/workflows${suffix}`)
  },
  createWorkflow: (wf) => request('POST', '/workflows', wf),
  getWorkflow: (id) => request('GET', `/workflows/${id}`),
  expressionContext: (workflowId) => request('GET', `/workflows/${workflowId}/expression-context`),
  saveWorkflow: (id, wf) => request('PUT', `/workflows/${id}`, wf),
  deleteWorkflow: (id) => request('DELETE', `/workflows/${id}`),
  exportWorkflow: (id) => request('GET', `/workflows/${id}/export`),
  importWorkflow: (doc) => request('POST', '/workflows/import', doc),
  setActive: (id, active) => request('PATCH', `/workflows/${id}/active`, { active }),
  setPinned: (id, pinned) => request('PATCH', `/workflows/${id}/pinned`, { pinned }),
  rollbackVersion: (workflowId, body) => request('POST', `/workflows/${workflowId}/rollback`, body),
  listVersions: (workflowId) => request('GET', `/workflows/${workflowId}/versions`),
  getVersion: (workflowId, versionNum) => request('GET', `/workflows/${workflowId}/versions/${versionNum}`),
  getActivationHistory: (workflowId) => request('GET', `/workflows/${workflowId}/activation-history`),
  upstreamFields: (workflowId, nodeId) =>
    request('GET', `/workflows/${workflowId}/upstream-fields?node_id=${encodeURIComponent(nodeId)}`),
  previewExpression: (workflowId, body) =>
    request('POST', `/workflows/${workflowId}/preview-expression`, body),
  listShares: (workflowId) => request('GET', `/workflows/${workflowId}/shares`),
  shareWorkflow: (workflowId, body) => request('POST', `/workflows/${workflowId}/shares`, body),
  unshareWorkflow: (workflowId, userId) => request('DELETE', `/workflows/${workflowId}/shares/${userId}`),
  run: (id) => request('POST', `/workflows/${id}/run`, {}),
  runNode: (workflowId, nodeId) =>
    request('POST', `/workflows/${workflowId}/run-node`, { node_id: nodeId }),
  runToNode: (workflowId, nodeId) =>
    request('POST', `/workflows/${workflowId}/run-to-node`, { node_id: nodeId }),
  // Phase 14: first-class workflow tests (mock runs, PASS/FAIL/DIFF).
  listWorkflowTests: (workflowId) => request('GET', `/workflows/${workflowId}/tests`),
  createWorkflowTest: (workflowId, payload) =>
    request('POST', `/workflows/${workflowId}/tests`, payload),
  updateWorkflowTest: (workflowId, testId, payload) =>
    request('PATCH', `/workflows/${workflowId}/tests/${testId}`, payload),
  deleteWorkflowTest: (workflowId, testId) =>
    request('DELETE', `/workflows/${workflowId}/tests/${testId}`),
  runWorkflowTest: (workflowId, testId) =>
    request('POST', `/workflows/${workflowId}/tests/${testId}/run`, {}),
  cancel: (id) => request('POST', `/executions/${id}/cancel`),
  // Phase 13: nodeId re-runs safely from one failed node (upstream seeded).
  retry: (id, nodeId) => request('POST', `/executions/${id}/retry`, nodeId ? { node_id: nodeId } : {}),
  resume: (id, approved = true) => request('POST', `/executions/${id}/resume`, { approved }),
  getExecution: (id) => request('GET', `/executions/${id}`),
  listExecutions: (params = {}) => {
    const q = new URLSearchParams()
    if (params.workflowId) q.set('workflow_id', params.workflowId)
    if (params.status) q.set('status', params.status)
    if (params.page) q.set('page', String(params.page))
    if (params.pageSize) q.set('pageSize', String(params.pageSize))
    const suffix = q.size ? `?${q.toString()}` : ''
    return requestEnvelope('GET', `/executions${suffix}`)
  },
  listNodes: () => request('GET', '/nodes'),
  listCredentials: () => request('GET', '/credentials'),
  listCredentialTypes: () => request('GET', '/credentials/types'),
  listCredentialProviders: () => request('GET', '/credentials/providers'),
  listPredefinedCredentials: () => request('GET', '/credentials/predefined'),
  testCredential: (id) => request('POST', `/credentials/${id}/test`),
  createCredential: (payload) => request('POST', '/credentials', payload),
  deleteCredential: (id) => request('DELETE', `/credentials/${id}`),
  getHealth: () => request('GET', '/health'),
  getMe: () => request('GET', '/auth/me'),
  listApiKeys: () => request('GET', '/apikeys'),
  createApiKey: (name) => request('POST', '/apikeys', { name }),
  revokeApiKey: (id) => request('DELETE', `/apikeys/${id}`),
  listUsers: () => request('GET', '/users'),
  listAudit: (params = {}) => {
    const q = new URLSearchParams()
    if (params.page) q.set('page', String(params.page))
    if (params.pageSize) q.set('pageSize', String(params.pageSize))
    const s = q.size ? `?${q.toString()}` : ''
    return requestEnvelope('GET', `/audit${s}`)
  },
  // Templates gallery (Phase 32/36)
  listTemplates: () => request('GET', '/templates'),
  createTemplate: (payload) => request('POST', '/templates', payload),
  useTemplate: (id) => request('POST', `/templates/${id}/use`, {}),
  updateTemplate: (id, payload) => request('PATCH', `/templates/${id}`, payload),
  deleteTemplate: (id) => request('DELETE', `/templates/${id}`),
  // Workspace environment variables (Phase 31/32)
  listWorkspaces: () => request('GET', '/workspaces?pageSize=100'),
  listEnvVars: (workspaceId) => request('GET', `/environments/${workspaceId}`),
  upsertEnvVar: (payload) => request('POST', '/environments', payload),
  deleteEnvVar: (id) => request('DELETE', `/environments/${id}`),
  listOrganizations: () => request('GET', '/organizations?pageSize=100'),
  salesforceConnect: (loginUrl) =>
    request('POST', '/auth/salesforce/connect', loginUrl ? { login_url: loginUrl } : {}),
  // Live Salesforce schema/object discovery (Phase 9): dynamic
  // object/field configuration for the generic salesforce node.
  salesforceObjects: (refresh = false) =>
    request('GET', `/connectors/salesforce/objects${refresh ? '?refresh=true' : ''}`),
  salesforceObjectSchema: (objectName, refresh = false) =>
    request(
      'GET',
      `/connectors/salesforce/schema/${encodeURIComponent(objectName)}${refresh ? '?refresh=true' : ''}`,
    ),
  connectOAuth: (provider, loginUrl) =>
    request('POST', `/auth/${provider}/connect`, loginUrl ? { login_url: loginUrl } : {}),
  aiStatus: () => request('GET', '/ai/status'),
  explain: (executionId) => request('POST', '/ai/explain', { execution_id: executionId }),
  generateWorkflow: (prompt) => request('POST', '/ai/generate-workflow', { prompt }),
  // Phase 16: AI assistant surfaces (read-only suggestions).
  suggestMapping: (payload) => request('POST', '/ai/suggest-mapping', payload),
  suggestExpression: (payload) => request('POST', '/ai/suggest-expression', payload),
  suggestNodeConfig: (payload) => request('POST', '/ai/suggest-node-config', payload),
  optimizeWorkflow: (workflowId) => request('POST', '/ai/optimize-workflow', { workflow_id: workflowId }),
  explainWorkflow: (workflowId) => request('POST', '/ai/explain-workflow', { workflow_id: workflowId }),
  documentWorkflow: (workflowId) => request('POST', '/ai/document-workflow', { workflow_id: workflowId }),
  // Data Tables (DATA-TABLES-01)
  listDataTables: (params = {}) => {
    const q = new URLSearchParams()
    if (params.workspace_id) q.set('workspace_id', params.workspace_id)
    if (params.search) q.set('search', params.search)
    if (params.page) q.set('page', String(params.page))
    if (params.pageSize) q.set('pageSize', String(params.pageSize))
    const s = q.size ? `?${q.toString()}` : ''
    return requestEnvelope('GET', `/data-tables${s}`)
  },
  // Webhook deliveries
  listWebhookDeliveries: (params = {}) => {
    const q = new URLSearchParams()
    if (params.workflow_id) q.set('workflow_id', params.workflow_id)
    if (params.node_id) q.set('node_id', params.node_id)
    if (params.page) q.set('page', String(params.page))
    if (params.pageSize) q.set('pageSize', String(params.pageSize))
    const s = q.size ? `?${q.toString()}` : ''
    return requestEnvelope('GET', `/webhooks/deliveries${s}`)
  },
  // Monitoring
  getMonitoringStats: () => request('GET', '/monitoring/stats'),
  getMonitoringMetrics: () => request('GET', '/monitoring/metrics'),
  createDataTable: (payload) => request('POST', '/data-tables', payload),
  getDataTable: (id) => request('GET', `/data-tables/${id}`),
  updateDataTable: (id, payload) => request('PATCH', `/data-tables/${id}`, payload),
  deleteDataTable: (id) => request('DELETE', `/data-tables/${id}`),
  createDataTableColumn: (tableId, payload) => request('POST', `/data-tables/${tableId}/columns`, payload),
  updateDataTableColumn: (tableId, colId, payload) => request('PATCH', `/data-tables/${tableId}/columns/${colId}`, payload),
  deleteDataTableColumn: (tableId, colId) => request('DELETE', `/data-tables/${tableId}/columns/${colId}`),
  reorderDataTableColumns: (tableId, order) => request('POST', `/data-tables/${tableId}/columns/reorder`, { order }),
  listDataTableRows: (tableId, params = {}) => {
    const q = new URLSearchParams()
    if (params.page) q.set('page', String(params.page))
    if (params.pageSize) q.set('pageSize', String(params.pageSize))
    if (params.search) q.set('search', params.search)
    if (params.sort_by) q.set('sort_by', params.sort_by)
    if (params.sort_order) q.set('sort_order', params.sort_order)
    if (params.filters) q.set('filters', typeof params.filters === 'string' ? params.filters : JSON.stringify(params.filters))
    const s = q.size ? `?${q.toString()}` : ''
    return requestEnvelope('GET', `/data-tables/${tableId}/rows${s}`)
  },
  createDataTableRow: (tableId, data) => request('POST', `/data-tables/${tableId}/rows`, { data }),
  bulkCreateDataTableRows: (tableId, rows) => request('POST', `/data-tables/${tableId}/rows/bulk`, { rows }),
  updateDataTableRow: (tableId, rowId, data) => request('PATCH', `/data-tables/${tableId}/rows/${rowId}`, { data }),
  deleteDataTableRow: (tableId, rowId) => request('DELETE', `/data-tables/${tableId}/rows/${rowId}`),
  bulkUpdateDataTableRows: (tableId, rows) => request('POST', `/data-tables/${tableId}/rows/bulk-update`, { rows }),
  bulkDeleteDataTableRows: (tableId, ids) => request('POST', `/data-tables/${tableId}/rows/bulk-delete`, { ids }),
  // Phase 18: production RAG (collections, ingestion, retrieval debugging).
  listRagCollections: () => request('GET', '/rag/collections'),
  createRagCollection: (payload) => request('POST', '/rag/collections', payload),
  deleteRagCollection: (id) => request('DELETE', `/rag/collections/${id}`),
  ragCollectionStats: (id) => request('GET', `/rag/collections/${id}/stats`),
  ragIngest: (id, payload) => request('POST', `/rag/collections/${id}/documents`, payload),
  ragQuery: (id, payload) => request('POST', `/rag/collections/${id}/query`, payload),
  getWorkflowAuthState: (workflowId, provider = '') => {
    const q = provider ? `?provider=${encodeURIComponent(provider)}` : ''
    return requestEnvelope('GET', `/workflows/${workflowId}/auth-state${q}`)
  },
  refreshWorkflowAuthState: (workflowId, provider = '', force = true) => {
    const q = provider ? `?provider=${encodeURIComponent(provider)}&force=${force}` : `?force=${force}`
    return requestEnvelope('POST', `/workflows/${workflowId}/auth-state/refresh${q}`)
  },
}

