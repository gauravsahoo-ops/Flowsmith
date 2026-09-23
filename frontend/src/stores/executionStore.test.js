// Execution history store tests (M8): fetchHistory pagination and
// loading a past execution into the inspector.

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useExecutionStore } from './executionStore'

const mockApi = vi.hoisted(() => ({
  listExecutions: vi.fn(),
  getExecution: vi.fn(),
  retry: vi.fn(),
  cancel: vi.fn(),
  run: vi.fn(),
}))

vi.mock('../api', () => ({ api: mockApi, getToken: () => 'tok' }))

const EXEC = {
  id: 'exec_1',
  workflow_id: 'wf_1',
  workflow_name: 'Demo',
  trigger: 'manual',
  status: 'success',
  started_at: '2026-08-12T10:00:00Z',
  finished_at: '2026-08-12T10:00:01Z',
  workflow_version: 1,
}

beforeEach(() => {
  vi.clearAllMocks()
  useExecutionStore.setState({
    executionId: null,
    status: null,
    nodeStatuses: {},
    trace: [],
    running: false,
    history: [],
    historyMeta: { page: 1, pageSize: 25, total: 0 },
    historyLoading: false,
    historyError: null,
  })
})

describe('fetchHistory', () => {
  it('stores items and pagination meta', async () => {
    mockApi.listExecutions.mockResolvedValue({ data: [EXEC], meta: { page: 1, pageSize: 25, total: 1 } })
    await useExecutionStore.getState().fetchHistory()
    expect(useExecutionStore.getState().history).toEqual([EXEC])
    expect(useExecutionStore.getState().historyMeta.total).toBe(1)
    expect(mockApi.listExecutions).toHaveBeenCalledWith({ page: 1, pageSize: 25 })
  })

  it('passes the workflow filter through', async () => {
    mockApi.listExecutions.mockResolvedValue({ data: [], meta: { page: 1, pageSize: 25, total: 0 } })
    await useExecutionStore.getState().fetchHistory({ workflowId: 'wf_9', page: 2 })
    expect(mockApi.listExecutions).toHaveBeenCalledWith({
      workflowId: 'wf_9',
      page: 2,
      pageSize: 25,
    })
  })

  it('records an error instead of throwing', async () => {
    mockApi.listExecutions.mockRejectedValue(new Error('boom'))
    await useExecutionStore.getState().fetchHistory()
    expect(useExecutionStore.getState().historyLoading).toBe(false)
    expect(useExecutionStore.getState().historyError).toBe('boom')
  })
})

describe('load', () => {
  it('hydrates the inspector with a finished execution', async () => {
    mockApi.getExecution.mockResolvedValue({
      ...EXEC,
      trace: [{ node_id: 'n1', status: 'success', duration_ms: 10 }],
      node_statuses: { n1: 'success' },
      error: null,
    })
    await useExecutionStore.getState().load('exec_1')
    const s = useExecutionStore.getState()
    expect(s.executionId).toBe('exec_1')
    expect(s.status).toBe('success')
    expect(s.trace).toHaveLength(1)
    expect(s.nodeStatuses).toEqual({ n1: 'success' })
    expect(s.running).toBe(false)
  })

  it('marks the run live when the execution is still running', async () => {
    mockApi.getExecution.mockResolvedValue({ ...EXEC, status: 'running' })
    await useExecutionStore.getState().load('exec_1')
    expect(useExecutionStore.getState().status).toBe('running')
    expect(useExecutionStore.getState().running).toBe(true)
  })

  it('marks the run live while it is still queued (Phase 15/16)', async () => {
    // A queued execution is not terminal: the inspector must stay live
    // so the WS/poll picks up the run once a worker claims it.
    mockApi.getExecution.mockResolvedValue({ ...EXEC, status: 'queued' })
    await useExecutionStore.getState().load('exec_1')
    expect(useExecutionStore.getState().status).toBe('queued')
    expect(useExecutionStore.getState().running).toBe(true)
  })

  it('surfaces a load failure in the inspector', async () => {
    mockApi.getExecution.mockRejectedValue(new Error('nope'))
    await useExecutionStore.getState().load('exec_2')
    const s = useExecutionStore.getState()
    expect(s.executionId).toBe('exec_2')
    expect(s.status).toBe('failed')
    expect(s.error.code).toBe('LOAD_FAILED')
  })
})

describe('clearNodeError', () => {
  it('clears failed node status and reset preview error', () => {
    useExecutionStore.setState({
      nodeStatuses: { node_1: 'failed', node_2: 'success' },
      runPreview: {
        node_1: { status: 'failed', error: 'URL required', note: 'Error occurred' },
        node_2: { status: 'success', outputCount: 1 },
      },
      error: 'Some execution error',
    })

    useExecutionStore.getState().clearNodeError('node_1')

    const s = useExecutionStore.getState()
    expect(s.nodeStatuses['node_1']).toBeUndefined()
    expect(s.nodeStatuses['node_2']).toBe('success')
    expect(s.runPreview['node_1'].error).toBeNull()
    expect(s.runPreview['node_1'].status).toBeNull()
    expect(s.runPreview['node_1'].note).toBeNull()
    expect(s.error).toBeNull()
  })
})