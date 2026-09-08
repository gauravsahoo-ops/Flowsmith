// Phase 14 workflow-testing helpers (pure, unit-tested).
//
// Everything works off the test report the API returns inside an
// execution's results: results.tests = { pass, verdict, summary,
// execution_status, checks: [{name, target, type, result, message,
// expected, actual, diff}] }.

export const VERDICT = {
  PASS: 'PASS',
  FAIL: 'FAIL',
  DIFF: 'DIFF',
}

/** Badge class for a check/verdict result. */
export function badgeClass(result) {
  switch (result) {
    case 'PASS':
      return 'badge-pass'
    case 'DIFF':
      return 'badge-diff'
    default:
      return 'badge-fail'
  }
}

/**
 * Compact one-line label for a check row: "[fetch] output equals at
 * '0.body.name'".
 */
export function formatCheckLabel(check) {
  const target = check.target && check.target !== '-' ? ` [${check.target}]` : ''
  return `${check.name || check.type || 'assertion'}${target}`
}

/** Human-readable single diff entry ("~ 1.name: 'Ada' -> 'Grace'"). */
export function formatDiffEntry(entry) {
  const path = entry.path || '$'
  switch (entry.op) {
    case 'change':
      return `~ ${path}: ${fmt(entry.expected)} -> ${fmt(entry.actual)}`
    case 'missing':
      return `- ${path}: expected ${fmt(entry.expected)}, got nothing`
    case 'extra':
      return `+ ${path}: unexpected ${fmt(entry.actual)}`
    case 'length':
      return `~ ${path}: ${entry.expected} items expected, found ${entry.actual}`
    case 'type':
      return `~ ${path}: type changed (${describe(entry.expected)} -> ${describe(entry.actual)})`
    default:
      return `? ${path}`
  }
}

function describe(value) {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'list'
  return typeof value
}

function fmt(value) {
  if (value === undefined) return '(undefined)'
  if (typeof value === 'string') return `'${value}'`
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/**
 * Roll a report up into {verdict, passed, failed, diffs, total} for the
 * header badges. Tolerates missing reports.
 */
export function summarizeReport(report) {
  if (!report || !Array.isArray(report.checks)) {
    return { verdict: null, passed: 0, failed: 0, diffs: 0, total: 0 }
  }
  let passed = 0
  let failed = 0
  let diffs = 0
  for (const c of report.checks) {
    if (c.result === 'PASS') passed += 1
    else if (c.result === 'DIFF') diffs += 1
    else failed += 1
  }
  return {
    verdict: report.verdict || (failed + diffs === 0 && passed > 0 ? 'PASS' : 'FAIL'),
    passed,
    failed,
    diffs,
    total: report.checks.length,
  }
}
