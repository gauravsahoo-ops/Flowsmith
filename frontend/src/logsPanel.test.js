import { describe, expect, it } from 'vitest'
import {
  extractTraceRecords,
  formatRecordPreview,
  recordMatchesQuery,
  traceStepHaystack,
} from './utils/logRecords'

function unrollItems(data) {
  if (data == null) return []
  if (Array.isArray(data)) {
    return data.map((item) => {
      if (item && typeof item === 'object' && 'json' in item) {
        return item.json
      }
      return item
    })
  }
  if (typeof data === 'object') {
    if (Array.isArray(data.main)) {
      return unrollItems(data.main)
    }
    if (Array.isArray(data.records)) {
      return data.records
    }
    if ('json' in data && typeof data.json === 'object') {
      return [data.json]
    }
    return [data]
  }
  return [{ value: data }]
}

describe('Logs feature utils and data structures', () => {
  it('formats milliseconds and seconds durations cleanly', () => {
    function fmtDuration(ms) {
      if (ms == null) return ''
      if (ms < 1000) return `${Math.round(ms)}ms`
      return `${(ms / 1000).toFixed(2)}s`
    }

    expect(fmtDuration(null)).toBe('')
    expect(fmtDuration(0)).toBe('0ms')
    expect(fmtDuration(450)).toBe('450ms')
    expect(fmtDuration(1200)).toBe('1.20s')
    expect(fmtDuration(3540)).toBe('3.54s')
  })

  it('formats item counts correctly for arrays or counts', () => {
    function fmtItems(outputs, output_count) {
      if (Array.isArray(outputs)) return `${outputs.length} items`
      if (output_count != null) return `${output_count} items`
      return ''
    }

    expect(fmtItems([1, 2, 3])).toBe('3 items')
    expect(fmtItems([], null)).toBe('0 items')
    expect(fmtItems(null, 5)).toBe('5 items')
    expect(fmtItems(null, null)).toBe('')
  })

  it('unrolls json wrapper items cleanly', () => {
    expect(unrollItems(null)).toEqual([])
    expect(unrollItems([{ json: { foo: 'bar' } }])).toEqual([{ foo: 'bar' }])
    expect(unrollItems({ main: [{ json: { id: 10 } }] })).toEqual([{ id: 10 }])
    expect(unrollItems({ records: [{ name: 'Test' }] })).toEqual([{ name: 'Test' }])
    expect(unrollItems({ json: { x: 1 } })).toEqual([{ x: 1 }])
  })

  it('handles execution log status mapping', () => {
    function getStatusLabel(status) {
      switch (status) {
        case 'success':
          return 'Success'
        case 'running':
          return 'Running'
        case 'failed':
        case 'error':
          return 'Error'
        case 'skipped':
          return 'Skipped'
        case 'waiting_approval':
          return 'Waiting'
        default:
          return status
      }
    }

    expect(getStatusLabel('success')).toBe('Success')
    expect(getStatusLabel('running')).toBe('Running')
    expect(getStatusLabel('failed')).toBe('Error')
    expect(getStatusLabel('error')).toBe('Error')
    expect(getStatusLabel('skipped')).toBe('Skipped')
    expect(getStatusLabel('waiting_approval')).toBe('Waiting')
  })

  it('finds records inside a node step and matches record values', () => {
    const step = {
      node_id: 'hs',
      node_type: 'hubspot',
      status: 'success',
      note: 'List records',
      outputs: {
        main: [{
          object_type: 'cars',
          records: [
            { id: '1', properties: { email: 'alice@example.com', model: 'Roadster' } },
            { id: '2', properties: { email: 'bob@example.com', model: 'Cybertruck' } },
          ],
        }],
      },
    }

    const records = extractTraceRecords(step)
    expect(records).toHaveLength(2)
    expect(formatRecordPreview(records[0])).toContain('alice@example.com')
    expect(recordMatchesQuery(records[1], 'cybertruck')).toBe(true)
    expect(recordMatchesQuery(records[1], 'roadster')).toBe(false)

    const haystack = traceStepHaystack(step, 'HubSpot')
    expect(haystack).toContain('hubspot')
    expect(haystack).toContain('alice@example.com')
  })

  it('does not duplicate a per-item trace row as a record child', () => {
    const step = {
      node_id: 'hs',
      item_index: 2,
      item_total: 10,
      inputs: { main: [{ email: 'item2@example.com' }] },
      outputs: { main: [{ id: '2', email: 'item2@example.com' }] },
    }

    expect(extractTraceRecords(step)).toEqual([])
    expect(traceStepHaystack(step, 'HubSpot')).toContain('item2@example.com')
  })
})
