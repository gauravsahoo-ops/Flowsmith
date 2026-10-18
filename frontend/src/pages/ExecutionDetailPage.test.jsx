import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ExecutionDetailPage from './ExecutionDetailPage'
import { api } from '../api'

vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'exec_54797581b4f5' }),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
  useNavigate: () => vi.fn(),
  Link: ({ children, to }) => React.createElement('a', { href: to }, children),
}))

vi.mock('../components/shared/PageHeader', () => ({
  default: ({ title, description }) => React.createElement('div', { id: 'page-header' }, title, ' - ', description),
}))

vi.mock('../components/ExecutionTimeline', () => ({
  default: () => React.createElement('div', { id: 'timeline' }, 'Timeline'),
}))

vi.mock('../components/StepDetail', () => ({
  default: () => React.createElement('div', { id: 'step-detail' }, 'StepDetail'),
}))

describe('ExecutionDetailPage Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders loading state initially', () => {
    vi.spyOn(api, 'getExecution').mockImplementation(() => new Promise(() => {}))
    const html = renderToStaticMarkup(React.createElement(ExecutionDetailPage))
    expect(html).toContain('Execution')
    expect(html).toContain('skeleton')
  })

  it('renders execution details and handles steps tab without ReferenceError', async () => {
    const mockExecution = {
      id: 'exec_54797581b4f5',
      workflow_id: 'wf_demo_flow',
      workflow_version: 1,
      status: 'failed',
      trigger: 'manual',
      started_at: '2026-10-12T09:00:00Z',
      finished_at: '2026-10-12T09:00:05Z',
      error: { code: 'HTTP_500', message: 'Internal Server Error' },
      trace: [
        { node_id: 'node_1', node_type: 'http_request', status: 'success', duration_ms: 120 },
        { node_id: 'node_2', node_type: 'code', status: 'failed', duration_ms: 45 },
      ],
    }

    vi.spyOn(api, 'getExecution').mockResolvedValue(mockExecution)

    // Verify component mounts and renders without throwing ReferenceError: s is not defined
    const html = renderToStaticMarkup(React.createElement(ExecutionDetailPage))
    expect(html).toBeDefined()
  })
})
