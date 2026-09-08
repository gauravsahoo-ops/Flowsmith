// executionStore: run a workflow and track live node statuses.
// M5 streams events over a WebSocket (spec 10); if the socket is
// unavailable or dies mid-run, it falls back to 500ms polling.

import { create } from 'zustand'
import { api, getToken } from '../api'

function wsUrl(executionId) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/ws/executions/${executionId}?token=${encodeURIComponent(getToken() || '')}`
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

/** Build the per-node canvas preview map from a finished (or partial) trace. */
function deriveRunPreview(trace) {
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
    })
    try {
      const { execution_id } = await api.run(workflowId)
      set({ executionId: execution_id })
      get().connect(execution_id)
    } catch (err) {
      set({ running: false, status: 'failed', error: err.message })
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
    let socket
    try {
      socket = new WebSocket(wsUrl(id))
    } catch {
      get().schedulePoll(id)
      return
    }
    socket.onmessage = (msg) => get().onEvent(id, msg)
    socket.onerror = () => get().fallback(id)
    socket.onclose = (e) => {
      if (e.code !== 1000 && e.code !== 1005) get().fallback(id)
    }
    set({ socket })
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
      set({ status: ev.status, error: ev.error || null, running: false })
      get().close()
      // Delay loadTrace slightly to allow DB commit to finish after
      // the execution completes (the terminal bus event fires before
      // the worker writes trace/node_statuses to the DB).
      setTimeout(() => get().loadTrace(id), 300)
      return
    }
    const { node_id, status } = ev
    if (node_id && status) {
      set((s) => {
        const now = Date.now()
        const prev = s.runPreview[node_id] || {}
        // Build a live runPreview entry from the bus event so the
        // canvas shows status badges and timing during execution.
        const startedAt = status === 'running' ? now : (prev.startedAt || now)
        const durationMs = (status === 'success' || status === 'error' || status === 'failed')
          ? (prev._startMs ? now - prev._startMs : prev.durationMs || 0)
          : prev.durationMs || 0
        return {
          nodeStatuses: { ...s.nodeStatuses, [node_id]: status },
          runPreview: {
            ...s.runPreview,
            [node_id]: {
              ...prev,
              status,
              durationMs: Math.round(durationMs),
              _startMs: status === 'running' ? now : prev._startMs,
              error: ev.error || prev.error || null,
            },
          },
        }
      })
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
      })
      if (data.status === 'running' || data.status === 'cancelling' || data.status === 'queued') {
        get().schedulePoll(id)
      } else {
        set({ running: false, pollTimer: null })
      }
    } catch {
      get().schedulePoll(id)
    }
  },

  schedulePoll(id) {
    const { pollTimer } = get()
    if (pollTimer) clearTimeout(pollTimer)
    set({ pollTimer: setTimeout(() => get().poll(id), 500) })
  },

  close() {
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
    set({ pollTimer: null })
  },
}))

if (typeof window !== 'undefined') window.__executionStore = useExecutionStore