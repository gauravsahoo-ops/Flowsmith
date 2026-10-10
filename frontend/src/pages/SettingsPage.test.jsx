import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import SettingsPage from './SettingsPage'

vi.mock('../api', () => ({
  api: {
    getHealth: vi.fn().mockResolvedValue({ version: '0.3.1', uptime_s: 3600 }),
    getMe: vi.fn().mockResolvedValue({ id: 'u_123', email: 'user@example.com', role: 'admin' }),
    listWorkspaces: vi.fn().mockResolvedValue([]),
    listOrganizations: vi.fn().mockResolvedValue([]),
    listApiKeys: vi.fn().mockResolvedValue([]),
    getNotificationPreferences: vi.fn().mockResolvedValue({
      email_enabled: true,
      notify_on_failure: true,
      notify_on_auth_expired: true,
      notify_on_rate_limit: true,
      notify_on_warning: false,
      cooldown_minutes: 15,
      custom_email: '',
    }),
    updateNotificationPreferences: vi.fn(),
    sendTestNotificationEmail: vi.fn(),
  },
  getToken: vi.fn().mockReturnValue(null),
}))

describe('SettingsPage Component', () => {
  it('renders notification settings including Alert Deduplication Cooldown and options', () => {
    const html = renderToStaticMarkup(
      React.createElement(MemoryRouter, null, React.createElement(SettingsPage))
    )
    expect(html).toContain('Alert Deduplication Cooldown')
    expect(html).toContain('15 minutes (recommended)')
    expect(html).toContain('Automatic Email Alerts')
    expect(html).toContain('Alert Recipient Email Override')
    expect(html).toContain('Alert Throttling &amp; Delivery Routing')
  })
})
