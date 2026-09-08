export function insertMapping(current, snippet) {
  const cur = current ?? ''
  // Whole-value single expression → replace; otherwise append at end.
  const trimmed = cur.trim()
  if (trimmed === '') return snippet
  if (trimmed.startsWith('{{') && trimmed.endsWith('}}') && trimmed.match(/\{\{/g).length === 1) {
    return snippet
  }
  return `${cur.trimEnd()} ${snippet}`
}
