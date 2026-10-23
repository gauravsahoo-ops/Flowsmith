import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import CsvNodeEditor from './CsvNodeEditor'

describe('CsvNodeEditor Suite', () => {
  it('renders CSV Parser identity banner and supported format tags', () => {
    const node = {
      id: 'node_dataload_1',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'upload',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('CSV Parser')
    expect(html).toContain('Production Ready')
    expect(html).toContain('CSV')
    expect(html).toContain('TSV')
    expect(html).toContain('ZIP (Single &amp; Multi-File)')
    expect(html).toContain('Nested Archives')
    expect(html).toContain('GZIP (.gz)')
  })

  it('renders 4 source modes: upload, url, file_path, and inline', () => {
    const node = {
      id: 'node_dataload_2',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'upload',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Option A: Upload File')
    expect(html).toContain('Option B: Download URL')
    expect(html).toContain('Local File Path')
    expect(html).toContain('Inline Content')
  })

  it('renders SSRF protection guard when in URL mode', () => {
    const node = {
      id: 'node_dataload_3',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'url',
        download_url: 'https://cdn.example.com/contacts.csv',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('SSRF Guard Active')
    expect(html).toContain('Rejects loopback, private networks')
    expect(html).toContain('Download URL (Supports Expressions)')
  })

  it('removes Field Mapping section and Auto-Map controls as requested (handled in subsequent step)', () => {
    const node = {
      id: 'node_dataload_4',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'upload',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).not.toContain('Field Mapping')
    expect(html).not.toContain('Auto-Map All')
    expect(html).not.toContain('Salesforce Contact')
    expect(html).not.toContain('Target Field')
  })

  it('keeps node editor clean and decoupled without duplicate policy or DB persistence clutter', () => {
    const node = {
      id: 'node_dataload_5',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'upload',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).not.toContain('Duplicate Policy &amp; Database Persistence')
    expect(html).not.toContain('Skip Duplicate Rows')
    expect(html).not.toContain('Persist staged records to PostgreSQL')
  })

  it('renders focused CSV configuration controls and preserves single-responsibility principle', () => {
    const node = {
      id: 'node_dataload_custom_fields',
      type: 'csv_parser',
      parameters: {
        source_mode: 'url',
        delimiter: ',',
        has_header: true,
        batch_size: 500,
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('CSV Parser')
    expect(html).toContain('Batch Size')
    expect(html).toContain('Row Limit (0 = All)')
    expect(html).toContain('First row contains column headers')
    expect(html).not.toContain('Add Target Field')
    expect(html).not.toContain('Custom Schema / Table')
  })
})
