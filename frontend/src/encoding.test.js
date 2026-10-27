import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('.', import.meta.url))

// Mojibake happens when UTF-8 punctuation is decoded as Windows-1252.
// Keep the exact sequences escaped so this test itself stays clean.
const BAD_SEQUENCES = [
  [0x00e2, 0x2020, 0x2019],
  [0x00e2, 0x2020, 0x2018],
  [0x00e2, 0x20ac, 0x2014],
  [0x00e2, 0x20ac, 0x00a6],
  [0x00e2, 0x20ac, 0x00a2],
]

function walk(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    const stat = statSync(path)
    if (stat.isDirectory()) {
      out.push(...walk(path))
    } else if (['.js', '.jsx', '.css', '.html'].includes(extname(path))) {
      out.push(path)
    }
  }
  return out
}

describe('source text encoding', () => {
  it('does not contain common UTF-8 mojibake sequences', () => {
    const failures = []
    for (const path of walk(ROOT)) {
      const lines = readFileSync(path, 'utf8').split(/\r?\n/)
      lines.forEach((line, index) => {
        for (const sequence of BAD_SEQUENCES) {
          if (line.includes(String.fromCodePoint(...sequence))) {
            failures.push(`${path}:${index + 1}`)
          }
        }
      })
    }
    expect(failures).toEqual([])
  })
})
