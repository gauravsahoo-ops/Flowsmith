// Tiny fetch wrapper: attaches the JWT, unwraps the {data, meta}
// envelope, and redirects to login on 401.

const TOKEN_KEY = 'mat_token'
const DEFAULT_TIMEOUT_MS = 30000

export function getToken() {
  if (typeof localStorage === 'undefined') return null
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (typeof localStorage === 'undefined') return
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(status, detail) {
    let msg = 'Request failed'
    if (typeof detail === 'string') {
      msg = detail
    } else if (Array.isArray(detail)) {
      msg = detail.map((d) => d.message || d.msg || JSON.stringify(d)).join('; ')
    } else if (detail && typeof detail === 'object') {
      msg = detail.message || detail.detail || detail.msg || JSON.stringify(detail)
    }
    super(msg)
    this.status = status
    this.detail = detail
  }
}

async function request(method, path, body, opts) {
  const { data } = await requestEnvelope(method, path, body, opts)
  return data
}

// Fetch a stored binary file with header auth. Tokens never go in URLs
// (URLs leak via history/logs/Referer); the Authorization header does not.
async function fetchFileBlob(fileId, kind = 'view') {
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`/api/files/${encodeURIComponent(fileId)}/${kind}`, { headers })
  if (resp.status === 401) {
    setToken(null)
    window.dispatchEvent(new Event('auth:expired'))
    throw new ApiError(401, 'Session expired')
  }
  if (!resp.ok) throw new ApiError(resp.status, `File fetch failed (${resp.status})`)
  return resp.blob()
}

export async function fetchFileObjectUrl(fileId, kind = 'view') {
  const blob = await fetchFileBlob(fileId, kind)
  return URL.createObjectURL(blob)
}

export async function downloadStoredFile(fileId, fileName) {
  const blob = await fetchFileBlob(fileId, 'download')
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = fileName || 'download.bin'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }
}

async function requestEnvelope(method, path, body, opts = {}) {
  const { timeout = DEFAULT_TIMEOUT_MS, signal: userSignal } = opts
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  if (userSignal) {
    if (userSignal.aborted) {
      controller.abort()
    } else {
      userSignal.addEventListener('abort', () => controller.abort(), { once: true })
    }
  }

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
      if (userSignal?.aborted) {
        throw new ApiError(0, 'Request cancelled by user')
      }
      throw new ApiError(0, `Request timed out after ${timeout / 1000}s`)
    }
    throw new ApiError(0, 'Cannot reach the server. Is the backend running?')
  } finally {
    clearTimeout(timer)
  }

  if (resp.status === 401) {
    // Suppress auto-logout ONLY when the 401 comes from a *third-party*
    // credential failing (Salesforce discovery, credential/LLM connection
    // tests) while the Flowsmith session is still valid. Every other 401
    // means our session token is bad and the user must be logged out.
    const isThirdPartyAuth =
      path.startsWith('/connectors/salesforce/') ||
      path.includes('/llm/test-connection') ||
      /^\/credentials\/[^/]+\/test/.test(path)
    if (!isThirdPartyAuth) {
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
  run: (id) => request('POST', `/workflows/${id}/run`, {}),
  runNode: (workflowId, nodeId, sourceExecutionId = null) =>
    request('POST', `/workflows/${workflowId}/run-node`, {
      node_id: nodeId,
      ...(sourceExecutionId ? { source_execution_id: sourceExecutionId } : {}),
    }),
  runToNode: (workflowId, nodeId) =>
    request('POST', `/workflows/${workflowId}/run-to-node`, { node_id: nodeId }),
  cancel: (id) => request('POST', `/executions/${id}/cancel`),
  // Phase 13: nodeId re-runs safely from one failed node (upstream seeded).
  retry: (id, nodeId) => request('POST', `/executions/${id}/retry`, nodeId ? { node_id: nodeId } : {}),
  resume: (id, approved = true) => request('POST', `/executions/${id}/resume`, { approved }),
  getExecution: (id) => request('GET', `/executions/${id}`),
  exportExecution: async (id, format = 'json') => {
    const token = getToken()
    const res = await fetch(`/api/executions/${id}/export?format=${format}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (res.status === 401) {
      setToken(null)
      window.dispatchEvent(new Event('auth:expired'))
      throw new ApiError(401, 'Session expired')
    }
    if (!res.ok) throw new Error(`Export failed: ${res.statusText}`)
    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `execution-${id.slice(0, 8)}-${format === 'csv' ? 'trace.csv' : 'audit.json'}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  },
  listExecutions: (params = {}, opts) => {
    const q = new URLSearchParams()
    if (params.workflowId) q.set('workflow_id', params.workflowId)
    if (params.status) q.set('status', params.status)
    if (params.page) q.set('page', String(params.page))
    if (params.pageSize) q.set('pageSize', String(params.pageSize))
    const suffix = q.size ? `?${q.toString()}` : ''
    return requestEnvelope('GET', `/executions${suffix}`, undefined, opts)
  },
  listNodes: () => request('GET', '/nodes'),
  listCredentials: () => request('GET', '/credentials'),
  listCredentialTypes: () => request('GET', '/credentials/types'),
  listCredentialProviders: () => request('GET', '/credentials/providers'),
  listPredefinedCredentials: () => request('GET', '/credentials/predefined'),
  testCredential: (id) => request('POST', `/credentials/${id}/test`),
  reconnectCredential: (id) => request('POST', `/credentials/${id}/reconnect`),
  updateCredentialConfig: (id, payload) => request('PATCH', `/credentials/${id}/config`, payload),
  updateCredential: (id, payload) => request('PUT', `/credentials/${id}`, payload),
  getOAuthConfig: (provider) => request('GET', `/credentials/oauth-config/${provider}`),
  saveOAuthConfig: (provider, payload) => request('POST', `/credentials/oauth-config/${provider}`, payload),
  logoutCredential: (id) => request('POST', `/credentials/${id}/logout`),
  createCredential: (payload) => request('POST', '/credentials', payload),
  deleteCredential: (id) => request('DELETE', `/credentials/${id}`),
  getHealth: () => request('GET', '/health'),
  getMe: () => request('GET', '/auth/me'),
  // One-time short-TTL ticket for the WebSocket handshake (?ticket= keeps
  // the bearer JWT out of URLs and access logs).
  wsTicket: () => request('POST', '/auth/ws-ticket'),
  listApiKeys: () => request('GET', '/apikeys'),
  createApiKey: (name) => request('POST', '/apikeys', { name }),
  revokeApiKey: (id) => request('DELETE', `/apikeys/${id}`),
  // Templates gallery (Phase 32/36)
  listTemplates: () => request('GET', '/templates'),
  createTemplate: (payload) => request('POST', '/templates', payload),
  useTemplate: (id) => request('POST', `/templates/${id}/use`, {}),
  deleteTemplate: (id) => request('DELETE', `/templates/${id}`),
  // Workspace environment variables (Phase 31/32)
  listWorkspaces: () => request('GET', '/workspaces?pageSize=100'),
  listEnvVars: (workspaceId) => request('GET', `/environments/${workspaceId}`),
  upsertEnvVar: (payload) => request('POST', '/environments', payload),
  deleteEnvVar: (id) => request('DELETE', `/environments/${id}`),
  listOrganizations: () => request('GET', '/organizations?pageSize=100'),
  salesforceConnect: (loginUrl, prompt) =>
    request('POST', '/auth/salesforce/connect', {
      ...(loginUrl ? { login_url: loginUrl } : {}),
      ...(prompt ? { prompt } : {}),
    }),
  // Live Salesforce schema/object discovery (Phase 9): dynamic
  // object/field configuration for the generic salesforce node.
  salesforceObjects: (refresh = false) =>
    request('GET', `/connectors/salesforce/objects${refresh ? '?refresh=true' : ''}`),
  salesforceObjectSchema: (objectName, refresh = false) =>
    request(
      'GET',
      `/connectors/salesforce/schema/${encodeURIComponent(objectName)}${refresh ? '?refresh=true' : ''}`,
    ),
  connectOAuth: (provider, loginUrl, prompt, extra = {}) => {
    let actualLoginUrl = loginUrl
    let actualPrompt = prompt
    let actualExtra = extra
    if (typeof loginUrl === 'object' && loginUrl !== null) {
      actualExtra = { ...loginUrl, ...extra }
      actualLoginUrl = loginUrl.login_url || loginUrl.loginUrl || undefined
      actualPrompt = loginUrl.prompt || prompt || undefined
    }
    const resolvedLoginUrl = typeof actualLoginUrl === 'string' ? actualLoginUrl.trim() : undefined
    return request('POST', `/auth/${provider}/connect`, {
      ...(resolvedLoginUrl ? { login_url: resolvedLoginUrl } : {}),
      ...(actualPrompt ? { prompt: actualPrompt } : {}),
      ...(actualExtra.clientId || actualExtra.client_id ? { client_id: actualExtra.clientId || actualExtra.client_id } : {}),
      ...(actualExtra.clientSecret || actualExtra.client_secret ? { client_secret: actualExtra.clientSecret || actualExtra.client_secret } : {}),
      ...(actualExtra.credentialId || actualExtra.credential_id ? { credential_id: actualExtra.credentialId || actualExtra.credential_id } : {}),
      ...(actualExtra.name ? { name: actualExtra.name } : {}),
      ...(actualExtra.allowedDomains || actualExtra.allowed_domains ? { allowed_domains: actualExtra.allowedDomains || actualExtra.allowed_domains } : {}),
      ...(actualExtra.tenantId || actualExtra.tenant_id ? { tenant_id: actualExtra.tenantId || actualExtra.tenant_id } : {}),
    })
  },
  aiStatus: () => request('GET', '/ai/status'),
  explain: (executionId) => request('POST', '/ai/explain', { execution_id: executionId }),
  generateWorkflow: (prompt, opts = {}) =>
    request('POST', '/ai/generate-workflow', {
      prompt,
      existing_workflow: opts.existingWorkflow,
      history: opts.history,
      credential_id: opts.credentialId,
    }),
  clearAiMemory: (sessionId, workflowId = null) =>
    request('DELETE', `/ai/memory/${encodeURIComponent(sessionId)}${workflowId ? `?workflow_id=${encodeURIComponent(workflowId)}` : ''}`),
  chatWithAgent: (payload, opts) => request('POST', '/ai/chat', payload, opts),
  // Phase 16: AI assistant surfaces (read-only suggestions).
  suggestMapping: (payload) => request('POST', '/ai/suggest-mapping', payload),
  suggestExpression: (payload) => request('POST', '/ai/suggest-expression', payload),
  suggestNodeConfig: (payload) => request('POST', '/ai/suggest-node-config', payload),
  optimizeWorkflow: (workflowId) => request('POST', '/ai/optimize-workflow', { workflow_id: workflowId }),
  explainWorkflow: (workflowId) => request('POST', '/ai/explain-workflow', { workflow_id: workflowId }),
  documentWorkflow: (workflowId) => request('POST', '/ai/document-workflow', { workflow_id: workflowId }),
  autoFixNode: (payload) => request('POST', '/ai/auto-fix', payload),
  // AI-Native Workflow Builder API
  getAiCapabilities: (q = '', limit = 15) => request('GET', `/ai/capabilities?q=${encodeURIComponent(q)}&limit=${limit}`),
  extractIntent: (payload) => request('POST', '/ai/intent', payload),
  validatePipeline: (workflow, credentialId = null) => request('POST', '/ai/validate-pipeline', { workflow, credential_id: credentialId }),
  simulateWorkflow: (workflow, mockInput = null, credentialId = null) => request('POST', '/ai/simulate', { workflow, mock_input: mockInput, credential_id: credentialId }),
  repairWorkflow: (payload) => request('POST', '/ai/repair-workflow', payload),
  modifyWorkflow: (payload) => request('POST', '/ai/modify-workflow', payload),
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
  updateDataTableRow: (tableId, rowId, data) => request('PATCH', `/data-tables/${tableId}/rows/${rowId}`, { data }),
  deleteDataTableRow: (tableId, rowId) => request('DELETE', `/data-tables/${tableId}/rows/${rowId}`),
  bulkDeleteDataTableRows: (tableId, ids) => request('POST', `/data-tables/${tableId}/rows/bulk-delete`, { ids }),
  // Phase 18: production RAG (collections, ingestion, retrieval debugging).
  listRagCollections: () => request('GET', '/rag/collections'),
  createRagCollection: (payload) => request('POST', '/rag/collections', payload),
  deleteRagCollection: (id) => request('DELETE', `/rag/collections/${id}`),
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
  // Custom company branding & white-labeling
  getBranding: () => request('GET', '/branding'),
  updateBranding: (data) => request('PUT', '/branding', data),
  resetBranding: () => request('POST', '/branding/reset'),
  // Connectors & OpenAPI Importer
  listConnectors: () => request('GET', '/connectors'),
  getConnector: (key) => request('GET', `/connectors/${encodeURIComponent(key)}`),
  previewOpenApi: (payload) => request('POST', '/connectors/preview-openapi', payload),
  importOpenApi: (payload) => request('POST', '/connectors/import-openapi', payload),
  // Model Context Protocol (MCP)
  listMcpTools: () => request('GET', '/mcp/tools'),
  callMcpTool: (payload) => request('POST', '/mcp/call', payload),
  // Universal Integration Catalog, Coverage & Canonical Nodes (Phase 4, 6, 29)
  listIntegrationCatalog: (params) => {
    const q = new URLSearchParams()
    if (params?.q) q.set('q', params.q)
    if (params?.category) q.set('category', params.category)
    const qs = q.toString() ? `?${q.toString()}` : ''
    return request('GET', `/integrations/catalog${qs}`)
  },
  getIntegrationCoverage: () => request('GET', '/integrations/coverage'),
  getIntegrationCertification: () => request('GET', '/integrations/certification'),
  listCanonicalNodes: () => request('GET', '/integrations/canonical-nodes'),
  // Multi-Provider LLM Platform
  listLLMProviders: (params) => {
    const q = new URLSearchParams()
    if (params?.q) q.set('q', params.q)
    if (params?.category) q.set('category', params.category)
    if (params?.status) q.set('status', params.status)
    const qs = q.toString() ? `?${q.toString()}` : ''
    return request('GET', `/llm/providers${qs}`)
  },
  testLLMConnection: (payload) => request('POST', '/llm/test-connection', payload),
  discoverLLMModels: (payload) => request('POST', '/llm/discover-models', payload),
  getLLMCredentialModels: (credId, refresh = false) => request('GET', `/llm/credentials/${credId}/models?refresh=${refresh}`),
  // AI Builder Pipeline Methods
  aiModifyWorkflow: (workflow, instruction) => request('POST', '/ai/modify-workflow', { workflow, instruction }),
  aiOptimizeDraft: (workflow, dimension = 'cost') => request('POST', '/ai/optimize-draft', { workflow, dimension }),
  aiExplainDraft: (workflow, failureContext = null) => request('POST', '/ai/explain-draft', { workflow, failure_context: failureContext }),
}


