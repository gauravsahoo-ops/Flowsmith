import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import StepDetail from './StepDetail'

vi.mock('../stores/workflowStore', () => ({
  useWorkflowStore: (selector) => selector({ catalogIndex: new Map() }),
}))

const marker = {
  _truncated: true,
  _total_count: 282,
  _omitted: 232,
  _note: '... and 232 more items (282 total).',
}

const records = Array.from({ length: 50 }, (_, index) => ({ id: index + 1 }))

const execution = {
  id: 'exec_preview',
  results: {
    outputs: {
      node_csv: {
        main: [{
          summary: { total_parsed: 282 },
          records: [...records, marker],
          rows: [...records, marker],
          invalid_records: [],
          duplicate_records: [],
        }],
      },
    },
  },
  workflow_data: { nodes: [{ id: 'node_csv', type: 'csv_parser' }] },
}

const step = {
  node_id: 'node_csv',
  node_type: 'csv_parser',
  status: 'success',
  outputs: execution.results.outputs.node_csv,
}

describe('StepDetail preview output', () => {
  it('does not present the preview marker as a 51st record', () => {
    const html = renderToStaticMarkup(
      React.createElement(StepDetail, {
        execution,
        step,
        onLoadFullOutput: async () => null,
      }),
    )

    expect(html).toContain('Preview: showing 50 of 282 records.')
    expect(html).toContain('Load all 282')
    expect(html).toContain('<span class="jt-brace">[50]</span>')
    expect(html).not.toContain('<span class="jt-brace">[51]</span>')
  })
})
