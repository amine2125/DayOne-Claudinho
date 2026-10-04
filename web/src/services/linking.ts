/**
 * Patient matching: proposes plausible existing patients for a new visit.
 * It only suggests; the midwife always decides. Pure functions, easy to test.
 */
import type { Field, LinkCandidate, LinkReason, Patient, RegistryRecord } from '@/contract/types'

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

/** Positions where two codes differ, used to highlight the character in the UI. */
export function diffPositions(code: string, other: string): number[] {
  const out: number[] = []
  for (let i = 0; i < code.length; i++) if (code[i]?.toUpperCase() !== other[i]?.toUpperCase()) out.push(i)
  return out
}

export function numberField(fields: Field[], key: string): number | undefined {
  const f = fields.find((x) => x.key === key && typeof x.value === 'number')
  return f ? (f.value as number) : undefined
}

export function findCandidates(
  record: RegistryRecord,
  patients: Patient[],
  fieldsOf: (patient: Patient) => Field[],
): LinkCandidate[] {
  const mine = record.pages.flatMap((p) => Object.values(p.fields))
  const age = numberField(mine, 'age')
  const gestation = numberField(mine, 'gestation')
  const out: LinkCandidate[] = []
  for (const patient of patients) {
    const distance = codeDistance(record.patientCode, patient.code)
    if (distance > 1) continue
    const reasons: LinkReason[] = [distance === 0 ? { kind: 'SAME_CODE' } : { kind: 'SIMILAR_CODE', distance }]
    const theirs = fieldsOf(patient)
    const theirAge = numberField(theirs, 'age')
    if (age !== undefined && theirAge !== undefined && Math.abs(age - theirAge) <= 1)
      reasons.push({ kind: age === theirAge ? 'SAME_AGE' : 'CLOSE_AGE', age: theirAge })
    const theirGestation = numberField(theirs, 'gestation')
    if (gestation !== undefined && theirGestation === gestation) reasons.push({ kind: 'SAME_GESTATION', gestation })
    out.push({ patient, reasons, score: (distance === 0 ? 10 : 5) + reasons.length })
  }
  return out.sort((a, b) => b.score - a.score)
}
