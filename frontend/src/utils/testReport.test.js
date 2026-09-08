// Phase 14 workflow-test report helpers.

import { describe, expect, it } from 'vitest'

import {
  badgeClass,
  formatCheckLabel,
  formatDiffEntry,
  summarizeReport,
} from './testReport'

describe('badgeClass', () => {
  it('maps each verdict to its badge', () => {
    expect(badgeClass('PASS')).toBe('badge-pass')
    expect(badgeClass('DIFF')).toBe('badge-diff')
    expect(badgeClass('FAIL')).toBe('badge-fail')
    expect(badgeClass(undefined)).toBe('badge-fail')
  })
})

describe('formatCheckLabel', () => {
  it('includes the target node when present', () => {
    const check = { name: 'output equals at 0.body.name', target: 'fetch', type: 'output_equals' }
    expect(formatCheckLabel(check)).toBe("output equals at 0.body.name [fetch]")
  })

  it('omits the target for workflow-level checks', () => {
    const check = { name: 'workflow succeeded', target: 'workflow', type: 'workflow_succeeded' }
    expect(formatCheckLabel(check)).toBe('workflow succeeded [workflow]')
  })

  it('falls back to the type when unnamed and hides placeholder targets', () => {
    expect(formatCheckLabel({ name: '', target: '-', type: 'error_code' })).toBe('error_code')
  })
})

describe('formatDiffEntry', () => {
  it('renders changes with both sides', () => {
    expect(formatDiffEntry({ op: 'change', path: '1.name', expected: 'Ada', actual: 'Grace' }))
      .toBe("~ 1.name: 'Ada' -> 'Grace'")
  })

  it('renders missing/extra/length entries', () => {
    expect(formatDiffEntry({ op: 'missing', path: 'id', expected: 7 }))
      .toBe('- id: expected 7, got nothing')
    expect(formatDiffEntry({ op: 'extra', path: 'ghost', actual: true }))
      .toBe('+ ghost: unexpected true')
    expect(formatDiffEntry({ op: 'length', path: 'main', expected: 2, actual: 3 }))
      .toBe('~ main: 2 items expected, found 3')
  })

  it('renders type flips', () => {
    expect(formatDiffEntry({ op: 'type', path: 'count', expected: 1, actual: null }))
      .toBe('~ count: type changed (number -> null)')
  })
})

describe('summarizeReport', () => {
  it('counts each result kind', () => {
    const report = {
      verdict: 'FAIL',
      checks: [
        { result: 'PASS' },
        { result: 'PASS' },
        { result: 'DIFF' },
        { result: 'FAIL' },
      ],
    }
    expect(summarizeReport(report)).toEqual({
      verdict: 'FAIL', passed: 2, failed: 1, diffs: 1, total: 4,
    })
  })

  it('derives PASS when all checks passed even without a verdict field', () => {
    expect(summarizeReport({ checks: [{ result: 'PASS' }] }).verdict).toBe('PASS')
  })

  it('tolerates a missing report', () => {
    expect(summarizeReport(null)).toEqual({
      verdict: null, passed: 0, failed: 0, diffs: 0, total: 0,
    })
    expect(summarizeReport({}).total).toBe(0)
  })
})
