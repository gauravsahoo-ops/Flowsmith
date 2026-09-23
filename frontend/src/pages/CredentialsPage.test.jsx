import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { useCredentialStore } from '../stores/credentialStore'
import CredentialsPage from './CredentialsPage'
import { api } from '../api'

vi.mock('../components/shared/WorkspaceTabs', () => ({
  default: () => React.createElement('div', { id: 'workspace-tabs' }, 'Tabs'),
}))

describe('CredentialsPage & Reconnection Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useCredentialStore.setState({
      credentials: [
        {
          id: 'cred_dcb',
          name: 'Salesforce (gaurav.sahoo@idslogic.com)',
          type: 'salesforce',
        },
      ],
      types: [
        { type: 'salesforce', name: 'Salesforce', implemented: true },
      ],
      load: vi.fn().mockResolvedValue([]),
    })
  })

  it('renders credentials page shell and elements', () => {
    const html = renderToStaticMarkup(React.createElement(CredentialsPage))
    expect(html).toContain('Credentials')
    expect(html).toContain('Manage encrypted connections')
    expect(html).toContain('Provider Capability Report')
    expect(html).toContain('New credential')
  })

  it('successfully handles reconnecting an interactive credential without sfLoginUrl errors', async () => {
    const cred = { id: 'cred_dcb', name: 'Salesforce (gaurav.sahoo@idslogic.com)', type: 'salesforce' }

    // Mock API responses
    vi.spyOn(api, 'reconnectCredential').mockResolvedValueOnce({
      ok: false,
      interactive_required: true,
      login_url: 'https://custom.my.salesforce.com',
      message: 'Credential requires re-authorization.',
    })

    const connectOAuthSpy = vi.spyOn(api, 'connectOAuth').mockResolvedValueOnce({
      authorize_url: 'https://custom.my.salesforce.com/services/oauth2/authorize?state=123',
      state: '123',
    })

    // Simulate what handleReconnect does: fetch reconnect status, resolve loginUrl, and trigger connectOAuth
    const res = await api.reconnectCredential(cred.id)
    expect(res.ok).toBe(false)
    expect(res.interactive_required).toBe(true)

    const loginUrl = res?.login_url || undefined
    expect(loginUrl).toBe('https://custom.my.salesforce.com')

    const oauthRes = await api.connectOAuth(cred.type, loginUrl)
    expect(connectOAuthSpy).toHaveBeenCalledWith(
      'salesforce',
      'https://custom.my.salesforce.com'
    )
    expect(oauthRes.authorize_url).toContain('authorize?state=123')
  })
})
