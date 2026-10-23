import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import Login from './Login'

describe('Login Component Suite', () => {
  it('renders modern v2.5 platform hero with badges, metrics, and live pipeline', () => {
    const html = renderToStaticMarkup(React.createElement(Login, { onAuthed: () => {} }))

    // Badges & Platform Branding
    expect(html).toContain('FLOWSMITH PLATFORM')
    expect(html).toContain('v2.5 Enterprise Live')
    expect(html).toContain('SOC-2 Ready')

    // Headline & Subheading
    expect(html).toContain('Automate at the')
    expect(html).toContain('speed of thought.')
    expect(html).toContain('autonomous AI agents')

    // Live Pipeline Card & Nodes
    expect(html).toContain('Live Pipeline • sync-crm-contacts')
    expect(html).toContain('Active • 99.99% SLA')
    expect(html).toContain('Webhook')
    expect(html).toContain('Salesforce')
    expect(html).toContain('AI Agent')

    // Enterprise Performance Metrics
    expect(html).toContain('12ms (P99)')
    expect(html).toContain('AES-256-GCM')
    expect(html).toContain('Dual Redis + WS')
    expect(html).toContain('45k ops/s')

    // Capability Badges
    expect(html).toContain('100+ Visual Connectors')
    expect(html).toContain('Autonomous AI Agents')
    expect(html).toContain('Self-Healing Execution')
    expect(html).toContain('Zero-Trust Encryption')

    // Auth Form & Controls
    expect(html).toContain('Log in')
    expect(html).toContain('Sign up')
    expect(html).toContain('Email address')
    expect(html).toContain('Password')
    expect(html).toContain('Sign In to Workspace')

    // System Status & Engineer Credit
    expect(html).toContain('All systems operational')
    expect(html).toContain('Gaurav')
  })
})
