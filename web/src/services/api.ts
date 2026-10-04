/**
 * The only door between screens and data. Today it is backed by an in-browser
 * mock (mockApi.ts); tomorrow an HTTP client implementing the same interface
 * talks to the Python backend. Screens never change.
 */
import type { FieldStatus, Lang, LinkDecision, PageType, Role } from '@/contract/enums'
import type { FieldValue, LinkCandidate, Patient, RegistryRecord, Visit } from '@/contract/types'

export interface ActivityEvent {
  id: string
  at: string
  recordId?: string
  kind: 'CAPTURE' | 'TRANSITION' | 'NETWORK' | 'FIELD' | 'LINK'
  text: string // already-translated codes are not stored: this is a state code or field key
}

export interface AppState {
  online: boolean
  records: Record<string, RegistryRecord>
  patients: Record<string, Patient>
  visits: Record<string, Visit>
  midwifeId: string
  role: Role
  lang: Lang
  /** Records the (mock) pipeline is working on right now. */
  busy: string[]
  activity: ActivityEvent[]
}

export interface NewPage {
  pageType: PageType
  imageUrl?: string
  imageSize: [number, number]
  /** Demo only: which bundled sample the photo is, so the mock can return its prediction. */
  sampleId?: string
}

export type LinkChoice = { decision: Extract<LinkDecision, 'EXISTING'>; patientId: string } | { decision: Exclude<LinkDecision, 'EXISTING'> }

export interface DayOneApi {
  getState(): AppState
  subscribe(listener: () => void): () => void

  setOnline(online: boolean): void
  setRole(role: Role): void
  setLang(lang: Lang): void
  setMidwifeId(id: string): void
  resetDemo(): void

  /** Store the photos on the device (encrypted in the real app) and queue them for the AI. */
  capture(patientCode: string, pages: NewPage[]): RegistryRecord
  retry(recordId: string): void
  retakePhoto(recordId: string, pageIndex: number, page: NewPage): void
  /** AI unavailable or page unreadable: open every field for manual entry. */
  startManualEntry(recordId: string): void

  confirmField(recordId: string, pageIndex: number, key: string): void
  setField(recordId: string, pageIndex: number, key: string, value: FieldValue, status: FieldStatus): void
  /** Mark every still-open field of a section as blank on paper. */
  markSectionBlank(recordId: string, pageIndex: number, section: string): void
  validate(recordId: string): void

  candidates(recordId: string): LinkCandidate[]
  link(recordId: string, choice: LinkChoice): void
}
