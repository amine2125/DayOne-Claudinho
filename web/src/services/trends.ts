/**
 * A patient's measures from visit to visit, merged from every page photographed for her.
 * The API derives each page's series from its fields (dayone/suivi.py); this file only merges them:
 * the same visit seen on two photos of the "Grossesse actuelle" page keeps the newest reading.
 * No clinical logic: no threshold, no norm, nothing says a value is good or bad.
 */
import type { MeasureCode, Patient, SeriesValue, SeriesVisit } from '@/contract/types'
import type { AppState } from './api'
import { recordsOf } from './index'
import { normalizeCode } from './linking'

/** A visit, with where it was read (to open the page it comes from). */
export interface TrendVisit extends SeriesVisit {
  recordId: string
  pageIndex: number
  /** Gestational age on the x axis: written on the page, or counted from the LMP and the visit date. */
  x?: number
  xComputed?: boolean
}

export type Fact = SeriesValue & { recordId: string; pageIndex: number }

export interface PatientTrends {
  antenatal: TrendVisit[]
  facts: Partial<Record<'lmp' | 'edd' | 'termDate' | 'height', Fact>>
  mother: TrendVisit[]
  newborn: TrendVisit[]
  delivery: Partial<Record<'date' | 'birthWeight' | 'headCirc' | 'gaWeeks' | 'sex', Fact>> & {
    mode?: string
    place?: string
    recordId?: string
    pageIndex?: number
  }
}

const DAY = 864e5
const days = (a: string, b: string) => Math.round((new Date(`${b.slice(0, 10)}T12:00:00`).getTime() - new Date(`${a.slice(0, 10)}T12:00:00`).getTime()) / DAY)

export function patientTrends(state: AppState, patient: Patient): PatientTrends {
  const out: PatientTrends = { antenatal: [], facts: {}, mother: [], newborn: [], delivery: {} }
  const antenatal = new Map<string, TrendVisit>()
  const mother = new Map<string, TrendVisit>()
  const newborn = new Map<string, TrendVisit>()
  // Records of her file, then photos with her code still being checked on WhatsApp (their values show
  // as "to check"). Oldest first: a newer photo of the same page overrides what an older one said.
  const pending = Object.values(state.records).filter(
    (r) => !r.patientId && r.patientCode && normalizeCode(r.patientCode) === normalizeCode(patient.code),
  )
  const records = [...recordsOf(state, patient), ...pending.sort((a, b) => a.createdAt.localeCompare(b.createdAt))]
  for (const r of records)
    r.pages.forEach((p, pageIndex) => {
      const s = p.series
      if (!s) return
      const where = { recordId: r.id, pageIndex }
      if (s.kind === 'delivery') {
        for (const [k, f] of Object.entries(s.facts)) {
          if ('key' in f) (out.delivery as Record<string, unknown>)[k] = { ...f, ...where }
          else if (k === 'mode' || k === 'place') out.delivery[k] = f.value
        }
        Object.assign(out.delivery, where)
        return
      }
      if (s.kind === 'antenatal')
        for (const [k, f] of Object.entries(s.facts)) if ('key' in f) (out.facts as Record<string, unknown>)[k] = { ...f, ...where }
      const target = s.kind === 'antenatal' ? antenatal : s.kind === 'postpartum_mother' ? mother : newborn
      for (const v of s.visits) {
        // Same visit on two photos: same date, or same column of the table when the date is not read.
        const id = v.date ?? (v.column != null ? `col${v.column}` : `${r.id}.${pageIndex}`)
        target.set(id, { ...v, ...where })
      }
    })

  const lmp = typeof out.facts.lmp?.value === 'string' ? out.facts.lmp.value : undefined
  out.antenatal = [...antenatal.values()]
    .map((v) => {
      if (v.gaWeeks != null) return { ...v, x: v.gaWeeks }
      if (lmp && v.date) return { ...v, x: Math.round((days(lmp, v.date) / 7) * 10) / 10, xComputed: true }
      return v
    })
    .sort((a, b) => (a.date && b.date ? a.date.localeCompare(b.date) : (a.column ?? 0) - (b.column ?? 0)))
  out.mother = [...mother.values()].sort((a, b) => (a.date ?? '').localeCompare(b.date ?? ''))

  // Newborn: x = age in days. Birth (delivery page) is day 0; a visit without written age is placed from dates.
  const born = typeof out.delivery.date?.value === 'string' ? out.delivery.date.value : undefined
  out.newborn = [...newborn.values()]
    .map((v) => ({ ...v, x: v.ageDays ?? (born && v.date ? days(born, v.date) : undefined), xComputed: v.ageDays == null }))
    .sort((a, b) => (a.x ?? 0) - (b.x ?? 0))
  return out
}

/** Points of one measure, in visit order, with the value as a number (systolic for bp). */
export function pointsOf(visits: TrendVisit[], measure: MeasureCode) {
  return visits.flatMap((v) => {
    const e = v.values[measure]
    if (!e || v.x == null) return []
    const y = Array.isArray(e.value) ? e.value[0] : typeof e.value === 'number' ? e.value : null
    return y == null ? [] : [{ visit: v, entry: e, x: v.x, y, y2: Array.isArray(e.value) ? e.value[1] : undefined }]
  })
}

/** Appointments written on the registry, with when she actually came back (scheduling facts only). */
export interface AppointmentRow {
  givenOn: string
  due: string
  /** Date of the next visit seen in the registry, if any. */
  cameOn?: string
  /** Positive: days after the appointment. */
  delay?: number
  source: 'antenatal' | 'mother' | 'newborn'
  recordId: string
  pageIndex: number
}

export function appointmentsOf(t: PatientTrends): AppointmentRow[] {
  const rows: AppointmentRow[] = []
  const visitDates = [...t.antenatal, ...t.mother, ...t.newborn].map((v) => v.date).filter((d): d is string => !!d).sort()
  if (t.delivery.date && typeof t.delivery.date.value === 'string') visitDates.push(t.delivery.date.value)
  visitDates.sort()
  for (const [source, visits] of [['antenatal', t.antenatal], ['mother', t.mother], ['newborn', t.newborn]] as const)
    for (const v of visits) {
      // An appointment on or before the visit it was given at is a misreading (flagged by the API's checks).
      if (!v.appointment || !v.date || v.appointment <= v.date) continue
      const next = visitDates.find((d) => d > v.date!)
      rows.push({
        givenOn: v.date,
        due: v.appointment,
        cameOn: next,
        delay: next ? days(v.appointment, next) : undefined,
        source,
        recordId: v.recordId,
        pageIndex: v.pageIndex,
      })
    }
  return rows.sort((a, b) => a.givenOn.localeCompare(b.givenOn))
}

/** Latest appointment written on the registry that is still ahead of the last visit seen. */
export function nextWrittenAppointment(t: PatientTrends): AppointmentRow | undefined {
  const rows = appointmentsOf(t)
  const last = rows.at(-1)
  return last && !last.cameOn ? last : undefined
}
