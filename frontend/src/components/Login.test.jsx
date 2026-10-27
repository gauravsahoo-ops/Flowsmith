import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import Login from './Login'

describe('Login Component Suite', () => {
  it('renders the Foundry login hero, workflow preview, and secure auth card', () => {
    const html = renderToStaticMarkup(
      React.createElement(
        MemoryRouter,
        null,
        React.createElement(Login, { onAuthed: () => {} }),
      ),
    )

    // Brand and product statement
    expect(html).toContain('Flowsmith')
    expect(html).toContain('Enterprise Automation Cloud')
    expect(html).toContain('Self-hosted')
    expect(html).toContain('Automation with')
    expect(html).toContain('engineering discipline.')
    expect(html).toContain('Design, run, and observe workflows')

    // Workflow preview
    expect(html).toContain('Workflow preview')
    expect(html).toContain('Example run')
    expect(html).toContain('Webhook')
    expect(html).toContain('Salesforce')
    expect(html).toContain('AI Agent')

    // Factual capability list
    expect(html).toContain('Visual DAG builder')
    expect(html).toContain('Native connectors')
    expect(html).toContain('AI agents')
    expect(html).toContain('Human approvals')

    // Auth form and security strip
    expect(html).toContain('Log in')
    expect(html).toContain('Sign up')
    expect(html).toContain('Email or username')
    expect(html).toContain('Password')
    expect(html).toContain('Sign In to Workspace')
    expect(html).toContain('256-bit encryption')
    expect(html).toContain('Passkeys')

    // Product footer
    expect(html).toContain('Secure workspace')
  })
})
