import { FOLLOW_UP, bucketFor, type FollowUp } from '@/contract/followup'
import type { Patient } from '@/contract/types'
import type { AppState } from './api'
import { lastVisitDate, recordsOf } from './index'
import { nextWrittenAppointment, patientTrends } from './trends'

const DAY = 864e5
const day = (iso: string) => new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
const addDays = (iso: string, n: number) => new Date(day(iso).getTime() + n * DAY).toISOString().slice(0, 10)

/** Delivery date written on the registry, or the day the delivery page was photographed. */
export function deliveryDate(state: AppState, patient: Patient): string | undefined {
  for (const r of [...recordsOf(state, patient)].reverse())
    for (const p of r.pages)
      if (p.pageType === 'accouchement') {
        const v = p.fields.date_accouchement?.value
        return typeof v === 'string' ? v : p.capturedAt.slice(0, 10)
      }
  return undefined
}

/**
 * Next expected contact for a patient. The appointment the midwife wrote on the registry comes first
 * ("Rendez-vous" row of the visits table, "Prochain rendez-vous le" after delivery); without one,
 * the booklet calendar below.
 */
export function followUpFor(state: AppState, patient: Patient, today = new Date()): FollowUp {
  const photographed = new Set(recordsOf(state, patient).flatMap((r) => r.pages.map((p) => p.pageType)))
  const late = (due: string) => Math.floor((today.getTime() - day(due).getTime()) / DAY)
  const delivered = deliveryDate(state, patient)
  const written = nextWrittenAppointment(patientTrends(state, patient))
  const fromPaper = (step: FollowUp['step']): FollowUp | undefined =>
    written && (!delivered || written.givenOn >= delivered)
      ? { step, due: written.due, daysLate: late(written.due), bucket: bucketFor(late(written.due)), anchor: { kind: 'WRITTEN', date: written.givenOn } }
      : undefined

  if (!delivered) {
    const paper = fromPaper('ANTENATAL')
    if (paper) return paper
    const last = lastVisitDate(state, patient)
    if (!last) return { step: 'ANTENATAL', bucket: 'LATER', daysLate: 0 }
    const due = addDays(last, FOLLOW_UP.antenatalEveryDays)
    return { step: 'ANTENATAL', due, daysLate: late(due), bucket: bucketFor(late(due)), anchor: { kind: 'LAST_VISIT', date: last } }
  }
  for (const s of FOLLOW_UP.postpartum) {
    if (s.pages.some((p) => photographed.has(p))) continue
    const paper = fromPaper(s.step)
    if (paper) return paper
    const due = addDays(delivered, s.dueDaysAfterDelivery)
    return { step: s.step, due, daysLate: late(due), bucket: bucketFor(late(due)), anchor: { kind: 'DELIVERY', date: delivered } }
  }
  return { step: 'DONE', bucket: 'DONE', daysLate: 0, anchor: { kind: 'DELIVERY', date: delivered } }
}
