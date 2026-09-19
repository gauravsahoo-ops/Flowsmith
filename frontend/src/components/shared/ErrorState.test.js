import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ErrorState from './ErrorState'
import EmptyState from './EmptyState'

describe('ErrorState & EmptyState Object-Safety Suite', () => {
  it('safely renders NodeExecutionError dict without crashing React', () => {
    const errorObj = {
      code: 'EXECUTION_FAILED',
      message: 'Failed to authenticate with Salesforce instance',
      node_id: 'salesforce_1',
      retryable: false,
      details: { status: 401, error: 'invalid_grant' },
    }

    const html = renderToStaticMarkup(
      React.createElement(ErrorState, {
        icon: '⚠️',
        title: 'Execution failed',
        description: errorObj,
      })
    )

    expect(html).toContain('Failed to authenticate with Salesforce instance')
    expect(html).toContain('Technical details')
    expect(html).toContain('invalid_grant')
  })

  it('safely renders plain string descriptions and custom details', () => {
    const html = renderToStaticMarkup(
      React.createElement(ErrorState, {
        title: 'Simple Error',
        description: 'Plain error message',
        details: 'Stack trace line 1',
      })
    )

    expect(html).toContain('Simple Error')
    expect(html).toContain('Plain error message')
    expect(html).toContain('Stack trace line 1')
  })

  it('safely handles error object without message field by falling back to JSON', () => {
    const html = renderToStaticMarkup(
      React.createElement(ErrorState, {
        title: { code: 'ERR_TIMEOUT' },
        description: { custom_code: 504, reason: 'Gateway Timeout' },
      })
    )

    expect(html).toContain('ERR_TIMEOUT')
    expect(html).toContain('Gateway Timeout')
  })

  it('EmptyState safely handles error objects in title and description', () => {
    const errorObj = {
      code: 'LOAD_ERROR',
      message: 'Failed to load workflow version history',
    }

    const html = renderToStaticMarkup(
      React.createElement(EmptyState, {
        title: 'Error loading',
        description: errorObj,
      })
    )

    expect(html).toContain('Failed to load workflow version history')
  })
})
