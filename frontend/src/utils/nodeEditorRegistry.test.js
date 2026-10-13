import { describe, it, expect } from 'vitest'
import { resolveNodeEditor, hasDedicatedEditor, listDedicatedEditorTypes } from './nodeEditorRegistry'

describe('nodeEditorRegistry', () => {
  it('gives dedicated editors to every node type that has one', () => {
    for (const type of [
      'salesforce',
      'dynamics_crm',
      'code',
      'if_condition',
      'filter',
      'schedule',
      'webhook',
      'http_request',
      'set_variable',
      'split',
      'compare_datasets',
      'stop_and_error',
      'switch',
      'wait',
      'sub_workflow',
      'execute_workflow_trigger',
      'token_manager',
      'token_fetch',
      'token_store',
      'ai',
      'csv',
    ]) {
      const resolved = resolveNodeEditor(type)
      expect(resolved, type).toBeTruthy()
      expect(resolved.kind, type).toBe('dedicated')
      expect(hasDedicatedEditor(type), type).toBe(true)
    }
  })

  it('resolves aliases to the same editor', () => {
    const canonical = resolveNodeEditor('split')
    expect(resolveNodeEditor('item_lists').kind).toBe(canonical.kind)
    expect(resolveNodeEditor('item_lists').load).toBe(canonical.load)

    expect(resolveNodeEditor('execute_sub_workflow').load).toBe(
      resolveNodeEditor('sub_workflow').load,
    )
    expect(resolveNodeEditor('auth_fetch').load).toBe(resolveNodeEditor('token_fetch').load)
    expect(resolveNodeEditor('auth_store').load).toBe(resolveNodeEditor('token_store').load)
    expect(resolveNodeEditor('csv_parser').load).toBe(resolveNodeEditor('csv').load)
  })

  it('falls back to the schema-driven panel for unknown node types', () => {
    // The guarantee: every node type has a configuration panel.
    for (const type of ['aggregate', 'merge', 'noop', 'html_extract', 'totally_unknown']) {
      const resolved = resolveNodeEditor(type)
      expect(resolved, type).toBeTruthy()
      expect(resolved.kind, type).toBe('dynamic')
      expect(hasDedicatedEditor(type), type).toBe(false)
    }
  })

  it('returns null for falsy input rather than throwing', () => {
    expect(resolveNodeEditor('')).toBeNull()
    expect(resolveNodeEditor(null)).toBeNull()
    expect(resolveNodeEditor(undefined)).toBeNull()
    expect(hasDedicatedEditor(null)).toBe(false)
    expect(hasDedicatedEditor('')).toBe(false)
  })

  it('caches resolutions so component identity is stable across renders', () => {
    const first = resolveNodeEditor('salesforce')
    const second = resolveNodeEditor('salesforce')
    expect(second).toBe(first)
  })

  it('registers the pre-panel for data_table without displacing its form', () => {
    // data_table must NOT have a dedicated editor (it uses the dynamic panel),
    // but it does have an additional discovery panel above it.
    expect(hasDedicatedEditor('data_table')).toBe(false)
    expect(resolveNodeEditor('data_table').kind).toBe('dynamic')
  })

  it('exposes the dedicated list for tooling', () => {
    const list = listDedicatedEditorTypes()
    expect(list).toContain('salesforce')
    expect(list).toContain('item_lists')
    expect(new Set(list).size).toBe(list.length)
  })
})
