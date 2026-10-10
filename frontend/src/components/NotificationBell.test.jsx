import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import NotificationBell from './NotificationBell'

vi.mock('../api', () => ({
  api: {
    getNotificationStats: vi.fn().mockResolvedValue({ unresolved_count: 3, critical_count: 1 }),
    listNotifications: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    acknowledgeNotification: vi.fn(),
  },
}))

describe('NotificationBell Component', () => {
  it('renders notification bell button structure', () => {
    const html = renderToStaticMarkup(
      React.createElement(MemoryRouter, null, React.createElement(NotificationBell))
    )
    expect(html).toContain('topbar-bell-btn')
    expect(html).toContain('<svg')
  })
})
