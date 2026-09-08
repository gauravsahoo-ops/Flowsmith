/**
 * Subsequence fuzzy score; higher is better, -1 = no match.
 */
export function fuzzyScore(query, text) {
  if (!query) return 0
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  let qi = 0
  let score = 0
  let prevMatch = -2
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) {
      score += 1
      if (ti === prevMatch + 1) score += 2 // consecutive boost
      if (ti === 0 || t[ti - 1] === ' ' || t[ti - 1] === '/' || t[ti - 1] === '_') score += 3 // word-boundary
      prevMatch = ti
      qi++
    }
  }
  return qi === q.length ? score : -1
}
