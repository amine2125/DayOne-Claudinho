/**
 * Patient code helpers for searching by code. Matching itself (proposing
 * existing patients for a new visit) is done by the backend (api/store.py).
 */

/** Characters handwriting readers often confuse, folded to one form. */
const LOOKALIKE: Record<string, string> = { O: '0', Q: '0', D: '0', I: '1', L: '1', S: '5', Z: '2', B: '8', G: '6' }

export function normalizeCode(code: string): string {
  return code.toUpperCase().replace(/[^A-Z0-9]/g, '')
}
function fold(code: string): string {
  return [...normalizeCode(code)].map((c) => LOOKALIKE[c] ?? c).join('')
}

export function codeDistance(a: string, b: string): number {
  const x = fold(a)
  const y = fold(b)
  const d = Array.from({ length: x.length + 1 }, (_, i) => [i, ...Array(y.length).fill(0)])
  for (let j = 1; j <= y.length; j++) d[0][j] = j
  for (let i = 1; i <= x.length; i++)
    for (let j = 1; j <= y.length; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (x[i - 1] === y[j - 1] ? 0 : 1))
  return d[x.length][y.length]
}
