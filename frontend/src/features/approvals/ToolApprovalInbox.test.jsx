import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ToolApprovalInbox, { ApprovalInboxView } from './ToolApprovalInbox'
import ApprovalDetailDrawer from './ApprovalDetailDrawer'
import { decideApproval, getApproval, listApprovals, resumeApprovalRun } from './approvalsApi'
import { generateDecisionNonce } from './approvalUtils'

const SAMPLE = {
  id: 'apr_1',
  run_id: 'exec_1',
  workflow_id: 'wf_1',
  node_id: 'agent_1',
  tool_name: 'http_request',
  risk_tier: 2,
  reason: 'External side effect',
  summary: 'Send a webhook to the billing provider',
  arguments: { url: 'https://example.com', token: '***REDACTED***' },
  preview: {},
  affected_resources: [],
  requested_by: 7,
  approvers: [7, 9],
  quorum: 2,
  separation_of_duties: true,
  status: 'pending',
  decision: {},
  decided_by: null,
  decided_at: null,
  expires_at: '2026-11-13T10:00:00Z',
  created_at: '2026-11-12T10:00:00Z',
  updated_at: '2026-11-12T10:00:00Z',
}

let fetchMock

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function mockJson(payload, { ok = true, status = 200 } = {}) {
  fetchMock.mockResolvedValueOnce({
    ok,
    status,
    text: () => Promise.resolve(JSON.stringify(payload)),
  })
}

describe('tool approval API contract', () => {
  it('lists pending requests from GET /api/approvals?status=pending', async () => {
    mockJson({ data: [SAMPLE] })

    const rows = await listApprovals({ status: 'pending' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/approvals?status=pending&limit=50')
    expect(init.method).toBe('GET')
    expect(rows).toEqual([SAMPLE])
  })

  it('returns an empty inbox without an error', async () => {
    mockJson({ data: [] })

    await expect(listApprovals({ status: 'pending' })).resolves.toEqual([])

    const html = renderToStaticMarkup(
      <ApprovalInboxView rows={[]} loading={false} error={null} statusFilter="pending" />,
    )
    expect(html).toContain('No pending tool approvals')
  })

  it('loads a single approval for the detail drawer', async () => {
    mockJson({ data: SAMPLE })

    const detail = await getApproval(SAMPLE.id)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/approvals/apr_1')
    expect(init.method).toBe('GET')
    expect(detail.summary).toBe(SAMPLE.summary)
  })

  it('posts an approval decision with a nonce and comment', async () => {
    mockJson({ data: { ...SAMPLE, status: 'approved' } })

    const updated = await decideApproval(SAMPLE.id, {
      approved: true,
      nonce: 'nonce-12345678',
      comment: 'verified',
    })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/approvals/apr_1/decide')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      approved: true,
      nonce: 'nonce-12345678',
      comment: 'verified',
    })
    expect(updated.status).toBe('approved')
  })

  it('posts a rejection decision', async () => {
    mockJson({ data: { ...SAMPLE, status: 'rejected' } })

    const updated = await decideApproval(SAMPLE.id, {
      approved: false,
      nonce: 'nonce-87654321',
      comment: 'not safe',
    })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/approvals/apr_1/decide')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      approved: false,
      nonce: 'nonce-87654321',
      comment: 'not safe',
    })
    expect(updated.status).toBe('rejected')
  })

  it('resumes the approved run explicitly with the run id and approved flag', async () => {
    mockJson({ data: { id: SAMPLE.run_id, status: 'queued' } })

    await resumeApprovalRun(SAMPLE.run_id, true)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/executions/exec_1/resume')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ approved: true })
  })

  it('resumes a rejected run with approved set to false', async () => {
    mockJson({ data: { id: SAMPLE.run_id, status: 'queued' } })

    await resumeApprovalRun(SAMPLE.run_id, false)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/executions/exec_1/resume')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ approved: false })
  })
})

describe('tool approval inbox states', () => {
  it('renders the risk tier, action, run, timestamps, expiry and status', () => {
    const html = renderToStaticMarkup(
      <ApprovalInboxView
        rows={[SAMPLE]}
        loading={false}
        error={null}
        statusFilter="pending"
        selectedId={null}
      />,
    )

    expect(html).toContain('Tier 2')
    expect(html).toContain('http_request')
    expect(html).toContain('exec_1')
    expect(html).toContain('2026-11-12T10:00:00Z')
    expect(html).toContain('2026-11-13T10:00:00Z')
    expect(html).toContain('Pending')
    expect(html).toContain('Review →')
  })

  it('renders the loading state', () => {
    const html = renderToStaticMarkup(
      <ApprovalInboxView rows={[]} loading error={null} statusFilter="pending" />,
    )
    expect(html).toContain('Loading tool approvals')
    expect(html).toContain('aria-busy="true"')
  })

  it('renders an unauthorized state for 403 responses', () => {
    const error = Object.assign(new Error('Forbidden'), { status: 403 })
    const html = renderToStaticMarkup(
      <ApprovalInboxView rows={[]} loading={false} error={error} statusFilter="pending" />,
    )
    expect(html).toContain('Not authorized')
    expect(html).toContain('do not have permission')
  })

  it('renders a generic error state', () => {
    const error = Object.assign(new Error('upstream unavailable'), { status: 502 })
    const html = renderToStaticMarkup(
      <ApprovalInboxView rows={[]} loading={false} error={error} statusFilter="pending" />,
    )
    expect(html).toContain('Could not load approvals')
    expect(html).toContain('upstream unavailable')
  })

  it('renders the inbox shell by default', () => {
    const html = renderToStaticMarkup(<ToolApprovalInbox />)
    expect(html).toContain('Loading tool approvals')
  })
})

describe('approval detail drawer', () => {
  it('shows redacted arguments, summary, approvers and separation of duties', () => {
    const detail = {
      ...SAMPLE,
      arguments: {
        url: 'https://example.com',
        token: '***REDACTED***',
        password: 'super-secret-password',
        nested: { api_key: 'key-that-must-not-render', keep: 'visible-value' },
      },
      preview: { note: 'preview text' },
      affected_resources: ['account:42'],
      decision: {
        decisions: [
          { user_id: 9, approved: true, comment: 'checked', at: '2026-11-12T11:00:00Z' },
        ],
      },
    }

    const html = renderToStaticMarkup(
      <ApprovalDetailDrawer
        request={detail}
        onClose={() => {}}
        onDecide={() => {}}
      />,
    )

    expect(html).toContain('Send a webhook to the billing provider')
    expect(html).toContain('http_request')
    expect(html).toContain('User #7')
    expect(html).toContain('User #9')
    expect(html).toContain('Separation of duties')
    expect(html).toContain('https://example.com')
    expect(html).toContain('visible-value')
    expect(html).toContain('***REDACTED***')
    expect(html).toContain('account:42')
    expect(html).toContain('Approve')
    expect(html).toContain('Reject')
    expect(html).not.toContain('super-secret-password')
    expect(html).not.toContain('key-that-must-not-render')
  })

  it('disables the decision buttons while submitting', () => {
    const html = renderToStaticMarkup(
      <ApprovalDetailDrawer
        request={SAMPLE}
        submitting
        onClose={() => {}}
        onDecide={() => {}}
      />,
    )
    expect(html).toContain('Submitting…')
    expect(html).toContain('disabled')
  })

  it('renders decision errors from the approval broker', () => {
    const html = renderToStaticMarkup(
      <ApprovalDetailDrawer
        request={SAMPLE}
        decisionError={new Error('The requester cannot approve their own request.')}
        onClose={() => {}}
        onDecide={() => {}}
      />,
    )
    expect(html).toContain('The requester cannot approve their own request.')
  })

  it('offers an explicit resume action for a decided request with a run id', () => {
    const html = renderToStaticMarkup(
      <ApprovalDetailDrawer
        request={{ ...SAMPLE, status: 'approved' }}
        onClose={() => {}}
        onDecide={() => {}}
        onResume={() => {}}
      />,
    )

    expect(html).toContain('Resume run')
    expect(html).toContain('can no longer be decided')
    expect(html).toContain('never started automatically')
  })

  it('does not offer resume without a run id or before a decision', () => {
    const decidedWithoutRun = renderToStaticMarkup(
      <ApprovalDetailDrawer
        request={{ ...SAMPLE, status: 'approved', run_id: null }}
        onClose={() => {}}
        onDecide={() => {}}
      />,
    )
    expect(decidedWithoutRun).not.toContain('Resume run')

    const pending = renderToStaticMarkup(
      <ApprovalDetailDrawer request={SAMPLE} onClose={() => {}} onDecide={() => {}} />,
    )
    expect(pending).not.toContain('Resume run')
  })

  it('disables resume while queuing and renders a readable conflict', () => {
    const busy = renderToStaticMarkup(
      <ApprovalDetailDrawer
        request={{ ...SAMPLE, status: 'approved' }}
        resuming
        onClose={() => {}}
        onDecide={() => {}}
      />,
    )
    expect(busy).toContain('Resuming…')
    expect(busy).toContain('disabled')

    const conflict = renderToStaticMarkup(
      <ApprovalDetailDrawer
        request={{ ...SAMPLE, status: 'approved' }}
        resumeError={Object.assign(new Error('Quorum not met.'), { status: 409 })}
        onClose={() => {}}
        onDecide={() => {}}
      />,
    )
    expect(conflict).toContain('Quorum not met.')
  })
})

describe('decision nonce', () => {
  it('uses crypto.randomUUID when available', () => {
    expect(generateDecisionNonce({ randomUUID: () => 'uuid-1234-5678' })).toBe('uuid-1234-5678')
  })

  it('falls back to a timestamp and random string', () => {
    const nonce = generateDecisionNonce({})
    expect(nonce).toMatch(/^approval-\d+-[a-z0-9]*$/)
    expect(nonce.length).toBeGreaterThanOrEqual(8)
    expect(nonce.length).toBeLessThanOrEqual(128)
  })
})
