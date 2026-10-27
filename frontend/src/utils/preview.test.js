import { describe, it, expect } from 'vitest'
import {
  findPreviewTruncation,
  isTruncationMarker,
  stripPreviewMarkers,
} from './preview'

const marker = {
  _truncated: true,
  _total_count: 282,
  _omitted: 232,
  _note: '... and 232 more items (282 total).',
}

describe('execution preview helpers', () => {
  it('finds nested preview truncation without counting the marker as a record', () => {
    const value = {
      main: [{
        records: Array.from({ length: 50 }, (_, index) => ({ id: index })).concat(marker),
      }],
    }
    expect(findPreviewTruncation(value)).toEqual({ returned: 50, total: 282 })
  })

  it('strips every marker while preserving real records and nested arrays', () => {
    const value = {
      records: [{ id: 1 }, marker],
      rows: [{ id: 1 }, marker],
    }
    expect(stripPreviewMarkers(value)).toEqual({
      records: [{ id: 1 }],
      rows: [{ id: 1 }],
    })
    expect(stripPreviewMarkers([marker])).toEqual([])
  })

  it('recognizes only complete truncation metadata objects', () => {
    expect(isTruncationMarker(marker)).toBe(true)
    expect(isTruncationMarker({ _truncated: true })).toBe(false)
    expect(isTruncationMarker({ _total_count: 282 })).toBe(false)
    expect(isTruncationMarker({ id: 1 })).toBe(false)
  })
})
