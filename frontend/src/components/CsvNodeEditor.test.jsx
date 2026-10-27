import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import CsvNodeEditor from './CsvNodeEditor'

describe('CsvNodeEditor Suite', () => {
  it('renders the CSV Parser parameters intro and supported formats', () => {
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
    expect(html).toContain('csv_parser')
    expect(html).toContain('CSV · TSV · ZIP · TAR · GZIP')
    expect(html).not.toContain('Production Ready')
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
    expect(html).toContain('Upload file')
    expect(html).toContain('Download URL')
    expect(html).toContain('Local path')
    expect(html).toContain('Inline text')
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
    expect(html).toContain('Download URL')
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
