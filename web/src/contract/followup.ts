/**
 * Follow-up calendar of the registry booklet: when is the next page expected?
 * It is a schedule, not a clinical assessment: it only uses dates and which
 * pages were photographed. Delays below are placeholders to validate with the
 * national maternal-health guideline in use; change them here only.
 */
import type { PageType } from './enums'

export type FollowUpStep = 'ANTENATAL' | 'POSTPARTUM_EARLY' | 'POSTPARTUM_LATE' | 'DONE'

export const FOLLOW_UP = {
  /** Pregnant (no delivery page yet): next antenatal contact after the last visit. */
  antenatalEveryDays: 28,
  /** After delivery: booklet pages expected, in order, with their due day. */
  postpartum: [
    { step: 'POSTPARTUM_EARLY', pages: ['postpartum_precoce_mere', 'postpartum_precoce_nouveau_ne'], dueDaysAfterDelivery: 7 },
    { step: 'POSTPARTUM_LATE', pages: ['postpartum_tardif_mere', 'postpartum_tardif_nouveau_ne'], dueDaysAfterDelivery: 42 },
  ] satisfies { step: FollowUpStep; pages: PageType[]; dueDaysAfterDelivery: number }[],
  /** "This week": due within this many days. */
  soonDays: 7,
  /** Past due by more than this: probably lost to follow-up, to recontact. */
  lostAfterDays: 30,
} as const

/** Groups of the Today screen, in display order. */
export const BUCKETS = ['LATE', 'SOON', 'LOST', 'LATER', 'DONE'] as const
export type Bucket = (typeof BUCKETS)[number]

export interface FollowUp {
  step: FollowUpStep
  bucket: Bucket
  /** ISO date the next contact is expected, if any. */
  due?: string
  /** Positive = days late, negative = days left. */
  daysLate: number
  /** What the due date comes from: the appointment written on the registry, or the booklet calendar. */
  anchor?: { kind: 'DELIVERY' | 'LAST_VISIT' | 'WRITTEN'; date: string }
}

export function bucketFor(daysLate: number): Bucket {
  if (daysLate > FOLLOW_UP.lostAfterDays) return 'LOST'
  if (daysLate > 0) return 'LATE'
  if (-daysLate <= FOLLOW_UP.soonDays) return 'SOON'
  return 'LATER'
}
