import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import ErrorAlertsList from './ErrorAlertsList'

vi.mock('../api', () => ({
  api: {
    listNotifications: vi.fn().mockResolvedValue({
      total: 1,
      items: [
        {
          id: 'ev-1',
          title: 'Action Required: Your Salesforce Session Has Expired',
          message: 'Authentication session expired, token renewal failed.',
          resolution: 'Reconnect Salesforce account in Settings > Credentials.',
          severity: 'CRITICAL',
          category: 'AUTH_SESSION_EXPIRED',
          status: 'NOTIFIED',
          workflow_name: 'Lead Sync',
          connector_type: 'salesforce',
          created_at: '2026-10-10T12:00:00Z',
        },
      ],
    }),
    acknowledgeNotification: vi.fn(),
    resolveNotification: vi.fn(),
  },
}))

describe('ErrorAlertsList Component', () => {
  it('renders filter bar and search controls', () => {
    const html = renderToStaticMarkup(
      React.createElement(MemoryRouter, null, React.createElement(ErrorAlertsList))
    )
    expect(html).toContain('error-alerts-container')
    expect(html).toContain('Search by workflow, error, node…')
    expect(html).toContain('All Severities')
    expect(html).toContain('All Categories')
    expect(html).toContain('Unresolved only')
  })
})
