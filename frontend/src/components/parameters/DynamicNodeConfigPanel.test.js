import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DynamicNodeConfigPanel from './DynamicNodeConfigPanel'

// The panel reads the selected operation off whichever property the node names
// as its selector. Most nodes gate on `operation`; rename_keys gates on `mode`.
// Rendering statically is enough to exercise every useMemo/useCallback above
// the return, which is where the selector is resolved.

const RENAME_META = {
  display_name: 'Rename Keys',
  credential_types: [],
  operation_selector: 'mode',
  operations: {
    rename: { display_name: 'Rename', properties: ['renames', 'use_paths', 'keep_unmatched'] },
    copy: { display_name: 'Copy', properties: ['renames', 'use_paths', 'keep_unmatched'] },
    remove: { display_name: 'Remove', properties: ['renames', 'use_paths'] },
  },
  parameters_schema: {
    type: 'object',
    properties: {
      mode: { type: 'string', enum: ['rename', 'copy', 'remove'], title: 'Mode' },
      renames: { type: 'object' },
      use_paths: { type: 'boolean' },
      keep_unmatched: { type: 'boolean' },
    },
  },
  fields: [
    { name: 'mode', title: 'Mode', type: 'select', group: 'main', enum: ['rename', 'copy', 'remove'] },
    { name: 'renames', title: 'Renames', type: 'json', group: 'parameters', show_if: null },
    { name: 'use_paths', title: 'Use Paths', type: 'boolean', group: 'parameters', show_if: null },
    {
      name: 'keep_unmatched',
      title: 'Keep Unmatched',
      type: 'boolean',
      group: 'parameters',
      show_if: { mode: ['!remove'] },
    },
  ],
}

function renderPanel(meta, node) {
  return renderToStaticMarkup(
    React.createElement(DynamicNodeConfigPanel, {
      node,
      meta,
      onParamsChange: () => {},
      onSettingsChange: () => {},
      onCredentialChange: () => {},
    }),
  )
}

describe('DynamicNodeConfigPanel selector awareness', () => {
  it('labels the selector from its own name, not a hard-coded "Operation"', () => {
    const html = renderPanel(RENAME_META, { parameters: { mode: 'rename' } })
    // rename_keys gates on `mode`, so the control is labelled from the schema
    // title of that property rather than the generic word.
    expect(html).toContain('>Mode<')
  })

  it('lists every declared mode as an option', () => {
    const html = renderPanel(RENAME_META, { parameters: { mode: 'copy' } })
    expect(html).toContain('value="rename"')
    expect(html).toContain('value="copy"')
    expect(html).toContain('value="remove"')
  })

  it("marks the node's own selector value as selected", () => {
    const html = renderPanel(RENAME_META, { parameters: { mode: 'remove' } })
    // renderToStaticMarkup puts `selected=""` on the chosen option.
    expect(html).toMatch(/<option[^>]*value="remove"[^>]*selected/)
    expect(html).not.toMatch(/<option[^>]*value="rename"[^>]*selected/)
  })

  it('renders a node that gates on the default `operation` selector unchanged', () => {
    const meta = {
      display_name: 'Postgres',
      credential_types: [],
      // No operation_selector — defaults to `operation`.
      operations: {
        query: { display_name: 'Query', properties: ['sql'] },
        execute: { display_name: 'Execute', properties: ['sql'] },
      },
      parameters_schema: {
        type: 'object',
        properties: { operation: { type: 'string', enum: ['query', 'execute'] } },
      },
      fields: [
        { name: 'operation', title: 'Operation', type: 'select', group: 'main', enum: ['query', 'execute'] },
        { name: 'sql', title: 'SQL', type: 'text', group: 'parameters', show_if: null },
      ],
    }
    const html = renderPanel(meta, { parameters: { operation: 'query' } })
    expect(html).toContain('>Operation<')
    expect(html).toContain('dncp-field-sql')
  })

  it('renders without a selector declaration or any operations', () => {
    const meta = {
      display_name: 'No Ops',
      credential_types: [],
      parameters_schema: { type: 'object', properties: { text: { type: 'string' } } },
      fields: [{ name: 'text', title: 'Text', type: 'text', group: 'main' }],
    }
    const html = renderPanel(meta, { parameters: { text: 'hi' } })
    expect(html).toContain('dncp-field-text')
    // No operation bar when nothing declares operations.
    expect(html).not.toContain('dncp-operation-section')
  })

  it('renders with missing meta rather than throwing', () => {
    const html = renderPanel(null, { parameters: {} })
    expect(typeof html).toBe('string')
  })
})
