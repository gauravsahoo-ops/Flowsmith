import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ApprovalsPage from './ApprovalsPage'

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}))

vi.mock('../features/approvals/ToolApprovalInbox', () => ({
  default: () => <div id="tool-approval-inbox" />,
}))

describe('ApprovalsPage integration', () => {
  it('keeps the execution-level approval inbox and adds the durable tool-approval tab', () => {
    const html = renderToStaticMarkup(<ApprovalsPage />)

    expect(html).toContain('Run pauses')
    expect(html).toContain('Tool approvals')
    expect(html).toContain('Workflow runs paused at a human-approval node or a gated agent tool call.')
    expect(html).toContain('Refresh run pauses')
  })
})
