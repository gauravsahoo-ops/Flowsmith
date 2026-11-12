/**
 * Pure helpers shared by the execution log stream and its tests.
 *
 * The log stream must be searchable at the record level as well as the
 * node level. Keeping the matching/serialization logic here makes the
 * behaviour testable without mounting the whole docked panel.
 */

export function safeJson(value) {
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/** Expand the common execution payload shapes into individual items/records. */
export function unrollItems(data) {
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

/**
 * Records carried by one trace step's output.
 *
 * A per-item trace row already represents one record, so it returns [] to
 * avoid duplicating that item beneath itself. A connector search/list row
 * carries an array (`records` or `main`) and is expanded into child rows.
 */
export function extractTraceRecords(step) {
  if (!step || step.item_index != null) return []
  const payload = step.full_outputs ?? step.outputs
  let items = unrollItems(payload)
  // Connector search/list outputs are often {main: [{records: [...]}]}.
  // Expand that inner array so the log shows each record individually.
  if (items.length === 1 && items[0] && typeof items[0] === 'object' && Array.isArray(items[0].records)) {
    items = items[0].records
  } else if (items.length > 1 && items.every((item) => item && typeof item === 'object' && Array.isArray(item.records))) {
    items = items.flatMap((item) => item.records)
  }
  if (items.length <= 1) return []
  return items
}

export function traceStepHaystack(step, nodeName = '') {
  const error = step?.error
  const errorText = error == null
    ? ''
    : typeof error === 'string'
      ? error
      : safeJson(error)
  return [
    nodeName,
    step?.node_id,
    step?.node_type,
    step?.status,
    step?.note,
    errorText,
    safeJson(step?.inputs),
    safeJson(step?.outputs),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

export function matchesQuery(value, query) {
  const q = String(query || '').trim().toLowerCase()
  if (!q) return true
  return String(value || '').toLowerCase().includes(q)
}

export function recordMatchesQuery(record, query) {
  const q = String(query || '').trim().toLowerCase()
  if (!q) return true
  return safeJson(record).toLowerCase().includes(q)
}

/** Compact one-line preview for a record row (id/email/name first). */
export function formatRecordPreview(record, maxLength = 180) {
  if (record == null) return ''
  if (typeof record !== 'object') return String(record).slice(0, maxLength)
  const props = record.properties && typeof record.properties === 'object'
    ? record.properties
    : record
  const preferred = ['email', 'name', 'dealname', 'subject', 'title', 'firstname', 'lastname']
  const parts = []
  if (record.id != null) parts.push(`id=${record.id}`)
  for (const key of preferred) {
    const value = props[key]
    if (value != null && value !== '') parts.push(`${key}=${String(value)}`)
    if (parts.length >= 3) break
  }
  if (parts.length <= 1) {
    const text = safeJson(record)
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text
  }
  const text = parts.join(' · ')
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text
}
