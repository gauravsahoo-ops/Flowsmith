// executionStore: run a workflow and track live node statuses.
// M5 streams events over a WebSocket (spec 10); if the socket is
// unavailable or dies mid-run, it falls back to 500ms polling.

import { create } from 'zustand'
import { api, getToken } from '../api'
import { playChime } from '../utils/soundEffects'
import { useUiStore } from './uiStore'

/**
 * @typedef {Object} NodePreview
 * @property {string} [status] - Node execution status
 * @property {number} [durationMs] - Execution duration in milliseconds
 * @property {number} [inputCount] - Number of input items
 * @property {number} [outputCount] - Number of output items
 * @property {string|null} [note] - Optional note
 * @property {string|null} [error] - Error message if failed
 * @property {number} [_startMs] - Internal: timestamp when node started running
 */

/**
 * @typedef {Object} ExecutionState
 * @property {string|null} executionId - Current execution ID
 * @property {string|null} status - Execution status (running|success|failed|cancelled)
 * @property {Object.<string, string>} nodeStatuses - Map of node ID to status
 * @property {Array} trace - Step-by-step run log
 * @property {string|null} startedAt - Execution start timestamp
 * @property {string|null} finishedAt - Execution finish timestamp
 * @property {number|null} version - Workflow version
 * @property {Object|null} error - Error details
 * @property {boolean} running - Whether execution is currently running
 * @property {Object|null} pauseState - Pause state if paused
 * @property {Object|null} approval - Approval details
 * @property {Object|null} results - Execution results
 * @property {WebSocket|null} socket - Active WebSocket connection
 * @property {number|null} pollTimer - Polling timer ID
 * @property {Object.<string, NodePreview>} runPreview - Per-node preview data
 * @property {Array} history - Past executions list
 * @property {Object} historyMeta - Pagination metadata for history
 * @property {boolean} historyLoading - Whether history is loading
 * @property {string|null} historyError - History loading error
 * @property {Object.<string, NodePreview>} pendingNodeUpdates - Batched node updates awaiting flush
 * @property {number|null} rafBatchHandle - requestAnimationFrame handle for batching
 * @property {number} _pollRetryCount - Internal: consecutive poll failure count
 */

function wsUrl(executionId, ticket) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  // Preferred: single-use ticket. Fallback: legacy ?token= when the
  // ticket endpoint is unreachable (server older than this change).
  const auth = ticket
    ? `ticket=${encodeURIComponent(ticket)}`
    : `token=${encodeURIComponent(getToken() || '')}`
  return `${proto}//${window.location.host}/api/ws/executions/${executionId}?${auth}`
}

async function fetchWsTicket() {
  try {
    const res = await api.wsTicket()
    return res?.data?.ticket || null
  } catch {
    return null
  }
}

function countItems(payload) {
  if (payload == null) return 0
  if (Array.isArray(payload)) return payload.length
  if (typeof payload === 'object') {
    const values = Object.values(payload)
    if (values.some(Array.isArray)) {
      return values.reduce((sum, v) => sum + (Array.isArray(v) ? v.length : 0), 0)
    }
    return Object.keys(payload).length
  }
  return 0
}

/**
 * Build the per-node canvas preview map from a finished (or partial) trace.
 * @param {Array} trace - Array of trace steps
 * @returns {Object.<string, NodePreview>}
 */
function deriveRunPreview(trace) {
  /** @type {Object.<string, NodePreview>} */
  const out = {}
  for (const step of trace || []) {
    if (!step?.node_id) continue
    const outCount = countItems(step.outputs)
    const inCount = countItems(step.inputs)
    out[step.node_id] = {
      status: step.status,
      durationMs: step.duration_ms,
      inputCount: inCount,
      outputCount: outCount,
      note: step.note || null,
      error:
        step.error && typeof step.error !== 'string'
          ? step.error.message || JSON.stringify(step.error)
          : step.error || null,
    }
  }
  return out
}

/**
 * Schedule a batched flush of pending node updates via requestAnimationFrame.
 * @param {Function} set - Zustand set function
 * @param {Function} get - Zustand get function
 */
function scheduleNodeBatch(set, get) {
  if (typeof requestAnimationFrame === 'function') {
    if (get().rafBatchHandle) return
    const handle = requestAnimationFrame(() => {
      set({ rafBatchHandle: null })
      flushNodeBatch(set, get)
    })
    set({ rafBatchHandle: handle })
  } else {
    // Non-browser / test environment: flush synchronously
    flushNodeBatch(set, get)
  }
}

/**
 * Flush all pending node updates to the store in a single state update.
 * @param {Function} set - Zustand set function
 * @param {Function} get - Zustand get function
 */
function flushNodeBatch(set, get) {
  if (get().rafBatchHandle && typeof cancelAnimationFrame === 'function') {
    cancelAnimationFrame(get().rafBatchHandle)
    set({ rafBatchHandle: null })
  }
  const pending = get().pendingNodeUpdates
  const keys = Object.keys(pending)
  if (!keys.length) return
  set({ pendingNodeUpdates: {} })
  set((s) => {
    const nextStatuses = { ...s.nodeStatuses }
    const nextPreview = { ...s.runPreview }
    for (const nid of keys) {
      const item = pending[nid]
      nextStatuses[nid] = item.status
      nextPreview[nid] = {
        ...(nextPreview[nid] || {}),
        ...item,
      }
    }
    return {
      nodeStatuses: nextStatuses,
      runPreview: nextPreview,
    }
  })
}

export const useExecutionStore = create((set, get) => ({
  executionId: null,
  status: null, // running | success | failed | cancelled
  nodeStatuses: {},
  trace: [], // step-by-step run log (M8)
  startedAt: null,
  finishedAt: null,
  version: null,
  error: null,
  running: false,
  pauseState: null,
  approval: null,
  results: null,
  socket: null,
  pollTimer: null,

  // Phase 12 (premium editor): per-node last-run summary for the canvas
  // previews — {status, durationMs, inputCount, outputCount, error}.
  // Derived once per trace/status change; nodes subscribe per-id.
  runPreview: {},

  // history (M8): past executions list
  history: [],
  historyMeta: { page: 1, pageSize: 25, total: 0 },
  historyLoading: false,
  historyError: null,

  clearNodeError(nodeId) {
    if (!nodeId) return
    const statuses = { ...(get().nodeStatuses || {}) }
    delete statuses[nodeId]
    const preview = { ...(get().runPreview || {}) }
    if (preview[nodeId]) {
      preview[nodeId] = { ...preview[nodeId], status: null, error: null, note: null }
    }
    set({ nodeStatuses: statuses, runPreview: preview, error: null })
  },

  async fetchHistory({ workflowId, page = 1 } = {}) {
    set({ historyLoading: true, historyError: null })
    try {
      const { data, meta } = await api.listExecutions({ workflowId, page, pageSize: 25 })
      set({
        history: data,
        historyMeta: meta || { page: 1, pageSize: 25, total: data.length },
        historyLoading: false,
      })
    } catch (err) {
      set({ historyLoading: false, historyError: err.message })
    }
  },

  async load(id) {
    // Open any past (or still-running) execution into the inspector.
    get().close()
    set({
      executionId: id,
      running: false,
      status: null,
      nodeStatuses: {},
      runPreview: {},
      trace: [],
      startedAt: null,
      finishedAt: null,
      version: null,
      error: null,
      pauseState: null,
      approval: null,
    })
    let data
    try {
      data = await api.getExecution(id)
    } catch (err) {
      set({ status: 'failed', error: { code: 'LOAD_FAILED', message: err.message } })
      return
    }
    const live = data.status === 'running' || data.status === 'cancelling' || data.status === 'queued'
    set({
      status: data.status,
      nodeStatuses: data.node_statuses || {},
      trace: data.trace || [],
      runPreview: deriveRunPreview(data.trace || []),
      startedAt: data.started_at,
      finishedAt: data.finished_at,
      version: data.workflow_version,
      error: data.error,
      pauseState: data.pause_state || null,
      approval: data.results?.approval || null,
      results: data.results || null,
      running: live,
    })
    if (live) get().connect(id)
  },

  async run(workflowId) {
    set({
      running: true,
      status: 'running',
      nodeStatuses: {},
      runPreview: {},
      trace: [],
      startedAt: null,
      finishedAt: null,
      version: null,
      error: null,
      pauseState: null,
      approval: null,
      _pollRetryCount: 0,
    })
    try {
      const { execution_id } = await api.run(workflowId)
      set({ executionId: execution_id })
      get().connect(execution_id)
    } catch (err) {
      set({ running: false, status: 'failed', error: err.message })
      if (useUiStore.getState().soundEffects) {
        playChime('error')
      }
    }
  },

  async retry() {
    const { executionId } = get()
    if (!executionId) return
    set({
      running: true,
      status: 'running',
      nodeStatuses: {},
      runPreview: {},
      trace: [],
      startedAt: null,
      finishedAt: null,
      version: null,
      error: null,
      pauseState: null,
      approval: null,
    })
    try {
      const { execution_id } = await api.retry(executionId)
      set({ executionId: execution_id })
      get().connect(execution_id)
    } catch (err) {
      set({ running: false, status: 'failed', error: err.message })
    }
  },

  clear() {
    get().close()
    set({
      executionId: null,
      status: null,
      nodeStatuses: {},
      runPreview: {},
      trace: [],
      startedAt: null,
      finishedAt: null,
      version: null,
      error: null,
      running: false,
    })
  },

  connect(id) {
    get().close()
    const seq = (get()._connectSeq || 0) + 1
    set({ _connectSeq: seq })
    ;(async () => {
      const ticket = await fetchWsTicket()
      if (get()._connectSeq !== seq) return // superseded by close()/newer connect
      let socket
      try {
        socket = new WebSocket(wsUrl(id, ticket))
      } catch {
        get().schedulePoll(id)
        return
      }
      socket.onmessage = (msg) => get().onEvent(id, msg)
      socket.onerror = () => get().fallback(id)
      socket.onclose = (e) => {
        if (e.code !== 1000 && e.code !== 1005) get().fallback(id)
      }
      if (get()._connectSeq !== seq) {
        try {
          socket.close()
        } catch {
          /* noop */
        }
        return
      }
      set({ socket })
    })()
  },

  fallback(id) {
    set({ socket: null })
    if (get().status === 'running' || get().status === 'queued' || get().status === null) {
      get().schedulePoll(id)
    }
  },

  onEvent(id, msg) {
    let ev
    try {
      ev = JSON.parse(msg.data)
    } catch {
      return // malformed message, ignore
    }
    if (ev.type === 'execution.terminal') {
      const batchHandle = get().rafBatchHandle
      if (batchHandle && typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(batchHandle)
        set({ rafBatchHandle: null })
      }
      flushNodeBatch(set, get)
      set({ status: ev.status, error: ev.error || null, running: false })
      get().close()
      if (useUiStore.getState().soundEffects) {
        playChime(ev.status === 'success' ? 'success' : 'error')
      }
      // Delay loadTrace slightly to allow DB commit to finish after
      // the execution completes (the terminal bus event fires before
      // the worker writes trace/node_statuses to the DB).
      setTimeout(() => get().loadTrace(id), 300)
      return
    }
    const { node_id, status } = ev
    if (node_id && status) {
      const now = Date.now()
      const currentPreview = get().runPreview[node_id] || {}
      const durationMs = (status === 'success' || status === 'error' || status === 'failed')
        ? (currentPreview._startMs ? now - currentPreview._startMs : currentPreview.durationMs || 0)
        : currentPreview.durationMs || 0

      set({
        pendingNodeUpdates: {
          ...get().pendingNodeUpdates,
          [node_id]: {
            status,
            durationMs: Math.round(durationMs),
            _startMs: status === 'running' ? now : currentPreview._startMs,
            error:
              ev.error && typeof ev.error !== 'string'
                ? ev.error.message || JSON.stringify(ev.error)
                : (ev.error || currentPreview.error || null),
          },
        },
      })
      scheduleNodeBatch(set, get)
    }
  },

  async loadTrace(id, retries = 3) {
    try {
      const data = await api.getExecution(id)
      // If the trace is empty but we expect data (execution is terminal),
      // retry — the DB commit may not have propagated yet.
      const hasTrace = Array.isArray(data.trace) && data.trace.length > 0
      const isTerminal = data.status === 'success' || data.status === 'failed' || data.status === 'cancelled' || data.status === 'timeout'
      if (!hasTrace && isTerminal && retries > 0) {
        await new Promise((r) => setTimeout(r, 500))
        return get().loadTrace(id, retries - 1)
      }
      set({
        trace: data.trace || [],
        runPreview: deriveRunPreview(data.trace || []),
        startedAt: data.started_at,
        finishedAt: data.finished_at,
        version: data.workflow_version,
        nodeStatuses: data.node_statuses || {},
        results: data.results || null,
        approval: data.results?.approval || null,
      })
    } catch {
      // the poll fallback keeps retrying
    }
  },

  async cancel() {
    const { executionId } = get()
    if (!executionId) return
    try {
      await api.cancel(executionId)
    } catch {
      // already finished; the stream/poll picks up the real status
    }
  },

  async poll(id) {
    try {
      const data = await api.getExecution(id)
      set({
        status: data.status,
        nodeStatuses: data.node_statuses || {},
        trace: data.trace || [],
        runPreview: deriveRunPreview(data.trace || []),
        startedAt: data.started_at,
        finishedAt: data.finished_at,
        version: data.workflow_version,
        error: data.error,
        pauseState: data.pause_state || null,
        approval: data.results?.approval || null,
        results: data.results || null,
        _pollRetryCount: 0,
      })
      if (data.status === 'running' || data.status === 'cancelling' || data.status === 'queued') {
        get().schedulePoll(id)
      } else {
        const prevRunning = get().running
        set({ running: false, pollTimer: null })
        if (prevRunning && useUiStore.getState().soundEffects) {
          playChime(data.status === 'success' ? 'success' : 'error')
        }
      }
    } catch (err) {
      const retryCount = (get()._pollRetryCount || 0) + 1
      set({ _pollRetryCount: retryCount })
      if (retryCount > 10) {
        set({ running: false, error: { code: 'POLL_FAILED', message: err.message } })
        return
      }
      get().schedulePoll(id)
    }
  },

  schedulePoll(id) {
    const { pollTimer } = get()
    if (pollTimer) clearTimeout(pollTimer)
    set({ pollTimer: setTimeout(() => get().poll(id), 500) })
  },

  close() {
    // Invalidate any in-flight async connect() (it awaits a WS ticket).
    set({ _connectSeq: (get()._connectSeq || 0) + 1 })
    const { socket, pollTimer } = get()
    if (socket) {
      socket.onmessage = null
      socket.onerror = null
      socket.onclose = null
      try {
        socket.close()
      } catch {
        /* noop */
      }
      set({ socket: null })
    }
    if (pollTimer) clearTimeout(pollTimer)
    const batchHandle = get().rafBatchHandle
    if (batchHandle && typeof cancelAnimationFrame === 'function') {
      cancelAnimationFrame(batchHandle)
    }
    set({ pollTimer: null, rafBatchHandle: null, pendingNodeUpdates: {} })
  },
}))

if (typeof window !== 'undefined' && import.meta.env?.DEV) window.__executionStore = useExecutionStore