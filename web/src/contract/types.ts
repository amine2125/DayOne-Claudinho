/**
 * The data contract shared by the model team (producer) and the UI (consumer).
 * A Field is what dayone/extract.py writes ({label, kind, value, status, confidence, source}),
 * plus traceability (origin, history). The reading has no template: a field read on a page
 * that matches a reference page (schema/*.json) takes that page's key and section.
 *
 * Privacy: no type here has a slot for a name, phone, national ID or address.
 * A patient is only a code written by the midwife plus an internal random ID.
 */
import type { FieldOrigin, FieldStatus, LifecycleState, PageType, Role } from './enums'
import type { FieldKind } from './registry'

export type FieldValue = string | number | boolean | null

/** [x1, y1, x2, y2] in the pixel space of the page template (see Page.imageSize). */
export type BBox = [number, number, number, number]

export interface FieldChange {
  at: string // ISO date
  by: string // midwife ID, or "AI"
  origin: FieldOrigin
  value: FieldValue
  status: FieldStatus
}

export interface Field {
  key: string // reference field id ("nn_poids"), or the id given by the reading
  /** Label as printed on the page (from the reading). */
  label?: string
  kind?: FieldKind
  section: string // reference group, e.g. "Nouveau-né", or "Autres champs lus"
  value: FieldValue
  status: FieldStatus
  confidence: number // 0..1
  origin: FieldOrigin
  /** Reader that produced the AI value: ocr, case, encre, regle, ocr+modele… */
  method?: string
  bbox?: BBox
  page: number // index of the page inside its Record
  /** Value the AI proposed, kept when the midwife corrects it. */
  aiValue?: FieldValue
  history: FieldChange[]
  /** Reserved for consistency rules (not implemented yet). */
  alerts?: string[]
  /** Checkbox group: the boxes printed on the page. */
  options?: string[]
  /** Why the reading doubts this field (dayone/extract.py `raison`). */
  reason?: 'non_rattache' | 'etiquette_douteuse' | 'champ_nouveau' | 'choix_nouveau' | 'valeur_douteuse'
  /** Value as read, before missing accented letters were restored. */
  readValue?: string
}

export interface Page {
  id: string
  /** Index of the page inside its Record (used by the API routes). */
  index?: number
  pageType: PageType
  /** Title read at the top of the page. */
  title?: string
  /** Why the page could not be read. */
  error?: string
  /** The served image already has personal zones blacked out. */
  masked?: boolean
  /** Opaque reference to the original image (role-restricted). */
  imageUrl?: string
  imageSize: [number, number]
  capturedAt: string
  quality?: { ok: boolean; issue?: 'BLUR' | 'DARK' | 'TILT' | 'LAYOUT' }
  /** Empty until the AI has read the page. Keyed by Field.key. */
  fields: Record<string, Field>
  /** ID of the page this one replaces when a registry page is photographed again. */
  supersedes?: string
}

export interface LifecycleEvent {
  state: LifecycleState
  at: string
  note?: string
}

/** One capture session: one or more pages of the same registry. */
export interface RegistryRecord {
  id: string
  midwifeId: string
  createdAt: string
  state: LifecycleState
  history: LifecycleEvent[]
  /** Code as written on the paper registry, typed by the midwife. */
  patientCode: string
  patientId?: string
  visitId?: string
  pages: Page[]
  failure?: { reason: string; at: string }
}

export interface Visit {
  id: string
  patientId: string
  date: string
  midwifeId: string
  recordIds: string[]
}

export interface Patient {
  /** Internal random ID, never derived from personal data. */
  id: string
  /** Code chosen by the midwife and written on the registry. */
  code: string
  createdAt: string
  visitIds: string[]
}

/** A plausible existing patient for a new visit, with the reasons shown to the midwife. */
export interface LinkCandidate {
  patient: Patient
  reasons: LinkReason[]
  score: number
}
export type LinkReason =
  | { kind: 'SAME_CODE' }
  | { kind: 'SIMILAR_CODE'; distance: number }
  | { kind: 'SAME_AGE' | 'CLOSE_AGE'; age: number }
  | { kind: 'SAME_GESTATION'; gestation: number }

export interface Session {
  midwifeId: string
  role: Role
}
