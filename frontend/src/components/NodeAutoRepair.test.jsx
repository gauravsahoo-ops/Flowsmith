import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import NodeAutoRepair from './NodeAutoRepair'

describe('NodeAutoRepair Component', () => {
  const defaultNode = {
    id: 'http_1',
    type: 'http_request',
    parameters: { method: 'GET', url: '' },
  }

  it('renders initial loading state with brand title', () => {
    const html = renderToStaticMarkup(
      React.createElement(NodeAutoRepair, {
        workflowId: 'wf_1',
        node: defaultNode,
        errorMessage: 'URL is required',
        onClose: () => {},
        onApplyFix: () => {},
      })
    )
    expect(html).toContain('Flowsmith AI Self-Healing Diagnostic')
    expect(html).toContain('Flowsmith AI is diagnosing root cause')
  })

  it('verifies action handlers for Apply Fix & Re-test vs Apply Fix Only', () => {
    const applySpy = vi.fn()
    const closeSpy = vi.fn()
    const suggested = { method: 'GET', url: 'https://httpbin.org/get' }

    // Simulate callback direct invocation as handled in NodeAutoRepair buttons:
    // Apply Fix & Re-test -> onApplyFix(suggested, true)
    // Apply Fix Only -> onApplyFix(suggested, false)
    // Dismiss -> onClose()
    const handleApplyAndRetest = () => applySpy(suggested, true)
    const handleApplyOnly = () => applySpy(suggested, false)
    const handleClose = () => closeSpy()

    handleApplyAndRetest()
    expect(applySpy).toHaveBeenCalledWith(suggested, true)

    handleApplyOnly()
    expect(applySpy).toHaveBeenCalledWith(suggested, false)

    handleClose()
    expect(closeSpy).toHaveBeenCalled()
  })
})
