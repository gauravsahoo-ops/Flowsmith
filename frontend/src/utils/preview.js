// Helpers for the execution API's bounded preview payloads.
//
// The API deliberately returns only the first 50 items of large lists and
// appends a metadata object:
//   { _truncated: true, _total_count: 282, _omitted: 232, _note: ... }
// That marker is transport metadata, not a node record. Rendering it makes a
// 282-record output look like it contains 51 records.

export function isTruncationMarker(value) {
  return Boolean(
    value
    && typeof value === 'object'
    && !Array.isArray(value)
    && value._truncated === true
    && (value._total_count != null || value._omitted != null)
  )
}

export function stripPreviewMarkers(value) {
  if (Array.isArray(value)) {
    return value
      .filter((item) => !isTruncationMarker(item))
      .map(stripPreviewMarkers)
  }
  if (value && typeof value === 'object') {
    const out = {}
    for (const [key, child] of Object.entries(value)) {
      out[key] = stripPreviewMarkers(child)
    }
    return out
  }
  return value
}

export function findPreviewTruncation(value) {
  if (Array.isArray(value)) {
    const marker = value.find(isTruncationMarker)
    if (marker) {
      return {
        returned: value.length - 1,
        total: Number(marker._total_count) || value.length - 1,
      }
    }
    for (const item of value) {
      const found = findPreviewTruncation(item)
      if (found) return found
    }
  } else if (value && typeof value === 'object') {
    for (const child of Object.values(value)) {
      const found = findPreviewTruncation(child)
      if (found) return found
    }
  }
  return null
}
