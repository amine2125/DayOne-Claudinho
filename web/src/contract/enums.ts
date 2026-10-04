/**
 * Every enumeration of the data contract, defined once.
 * Codes are the same strings the Python pipeline emits (dayone/schema.py),
 * so the backend and this UI can exchange JSON without any mapping.
 * Human labels live in src/i18n, never here.
 */

/** The 6 field statuses required by the challenge. */
export const FIELD_STATUSES = [
  'KNOWN', // read and plausible
  'NEEDS_REVIEW', // the AI doubts: the midwife must look
  'ILLEGIBLE', // something is written but cannot be read
  'UNKNOWN', // the paper says "unknown" / "?"
  'NOT_PROVIDED', // the zone is blank on the paper
  'NOT_APPLICABLE', // does not apply (e.g. C-section indication for a vaginal birth)
] as const
export type FieldStatus = (typeof FIELD_STATUSES)[number]

/** Statuses that need a human decision before a page can be validated. */
export const STATUSES_TO_REVIEW: readonly FieldStatus[] = ['NEEDS_REVIEW', 'ILLEGIBLE']

/** Who produced the current value of a field (traceability). */
export const FIELD_ORIGINS = [
  'AI', // produced by the extraction pipeline, untouched
  'CONFIRMED', // AI value confirmed by the midwife
  'CORRECTED', // AI value replaced by the midwife
  'MANUAL', // typed by the midwife without AI (AI unavailable or page unsupported)
] as const
export type FieldOrigin = (typeof FIELD_ORIGINS)[number]

/** Record lifecycle, including failure states. Transitions live in lifecycle.ts. */
export const LIFECYCLE_STATES = [
  'CAPTURED',
  'PENDING_AI',
  'AI_PROCESSED',
  'NEEDS_REVIEW',
  'VALIDATED',
  'PATIENT_LINKED',
  'SAVED',
  'SYNCED',
  // failures
  'PROCESSING_FAILED',
  'SYNC_FAILED',
  'SUSPECTED_DUPLICATE',
  'MANUAL_REVIEW_REQUIRED',
] as const
export type LifecycleState = (typeof LIFECYCLE_STATES)[number]

export const FAILURE_STATES: readonly LifecycleState[] = [
  'PROCESSING_FAILED',
  'SYNC_FAILED',
  'SUSPECTED_DUPLICATE',
  'MANUAL_REVIEW_REQUIRED',
]

/** The 8 pages of the paper registry booklet, in booklet order. */
export const PAGE_TYPES = [
  'fiche_surveillance',
  'identification_antecedents',
  'grossesse_actuelle',
  'accouchement',
  'postpartum_precoce_mere',
  'postpartum_precoce_nouveau_ne',
  'postpartum_tardif_mere',
  'postpartum_tardif_nouveau_ne',
] as const
/** 'unknown' : photo reçue mais page non reconnue par la lecture. */
export type PageType = (typeof PAGE_TYPES)[number] | 'unknown'

export const ROLES = ['MIDWIFE', 'SUPERVISOR', 'EPIDEMIOLOGIST'] as const
export type Role = (typeof ROLES)[number]

export const LANGS = ['fr', 'en'] as const
export type Lang = (typeof LANGS)[number]

/** Answers offered when a new visit may belong to an existing patient. */
export const LINK_DECISIONS = ['EXISTING', 'CREATE', 'UNSURE'] as const
export type LinkDecision = (typeof LINK_DECISIONS)[number]
