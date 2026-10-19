import { describe, it, expect, beforeEach, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const mockExecState = {
  executionId: null,
  status: null,
  nodeStatuses: {},
  trace: [],
  startedAt: null,
  finishedAt: null,
  version: null,
  error: null,
  pauseState: null,
  approval: null,
  running: false,
  retry: vi.fn(),
  clear: vi.fn(),
  run: vi.fn(),
  load: vi.fn(),
}

vi.mock('../stores/executionStore', () => {
  const useExecutionStore = (selector) => selector(mockExecState)
  useExecutionStore.getState = () => mockExecState
  useExecutionStore.setState = (updates) => Object.assign(mockExecState, updates)
  return { useExecutionStore }
})

vi.mock('../stores/workflowStore', () => {
  const wfState = {
    workflow: { id: 'wf_123', name: 'Test Workflow' },
    catalogIndex: new Map(),
    nodes: [
      { id: 'node_1', data: { node: { id: 'trigger_webhook' } } },
      { id: 'node_2', data: { node: { id: 'salesforce_upsert' } } },
    ],
  }
  const useWorkflowStore = (selector) => selector(wfState)
  useWorkflowStore.getState = () => wfState
  useWorkflowStore.setState = (updates) => Object.assign(wfState, updates)
  return { useWorkflowStore }
})

vi.mock('../api', () => ({
  api: {
    listExecutions: vi.fn().mockResolvedValue({ data: [] }),
    getExecution: vi.fn().mockResolvedValue({}),
    explain: vi.fn().mockResolvedValue({ explanation: 'test explanation' }),
    retry: vi.fn().mockResolvedValue({ execution_id: 'new_exec' }),
  },
}))

import ExecutionInspector from './ExecutionInspector'

describe('ExecutionInspector Component', () => {
  beforeEach(() => {
    Object.assign(mockExecState, {
      executionId: null,
      status: null,
      nodeStatuses: {},
      trace: [],
      startedAt: null,
      finishedAt: null,
      version: null,
      error: null,
      pauseState: null,
      approval: null,
      running: false,
    })
  })

  it('exports a valid ExecutionInspector React component', () => {
    expect(typeof ExecutionInspector).toBe('function')
  })

  it('renders empty state when no executionId is present', () => {
    const html = renderToStaticMarkup(React.createElement(ExecutionInspector, { onClose: vi.fn() }))
    expect(html).toContain('No Active Execution')
    expect(html).toContain('Run Workflow')
  })

  it('renders execution inspector with steps and icons without throwing ReferenceError for STEP_ICON', () => {
    Object.assign(mockExecState, {
      executionId: 'exec_abc123xyz456',
      status: 'success',
      nodeStatuses: {
        node_1: 'success',
        node_2: 'failed',
      },
      trace: [
        { node_id: 'node_1', node_type: 'webhook', status: 'success', duration_ms: 45 },
        { node_id: 'node_2', node_type: 'salesforce', status: 'failed', duration_ms: 120, retries: 2 },
      ],
      startedAt: '2026-10-19T10:00:00Z',
      finishedAt: '2026-10-19T10:00:01Z',
      version: 3,
    })

    const html = renderToStaticMarkup(React.createElement(ExecutionInspector, { onClose: vi.fn() }))
    expect(html).toContain('Console')
    expect(html).toContain('exec_abc123xyz456')
    expect(html).toContain('v3')
    expect(html).toContain('timeline')
    expect(html).toContain('steps')
    expect(html).toContain('compare')
  })

  it('renders execution error card cleanly when run fails', () => {
    Object.assign(mockExecState, {
      executionId: 'exec_err_999',
      status: 'failed',
      nodeStatuses: { node_1: 'error' },
      trace: [{ node_id: 'node_1', node_type: 'python_code', status: 'error' }],
      startedAt: '2026-10-19T10:00:00Z',
      finishedAt: '2026-10-19T10:00:01Z',
      error: { code: 'NODE_RUNTIME_ERROR', message: 'division by zero', details: 'Traceback (most recent call last): line 4' },
    })

    const html = renderToStaticMarkup(React.createElement(ExecutionInspector, { onClose: vi.fn() }))
    expect(html).toContain('NODE_RUNTIME_ERROR')
    expect(html).toContain('division by zero')
    expect(html).toContain('Technical details')
  })
})
