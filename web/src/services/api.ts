/**
 * The only door between screens and data, backed by the local Python API
 * (httpApi.ts). Screens never call the network themselves.
 */
import type { Lang, Role } from '@/contract/enums'
import type { Patient, RegistryRecord, Visit } from '@/contract/types'

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
  /** Records the backend is reading right now. */
  busy: string[]
  activity: ActivityEvent[]
}

/** The dashboard only reads. Records are written by the backend (WhatsApp agent). */
export interface DayOneApi {
  getState(): AppState
  subscribe(listener: () => void): () => void
  /** Ask the backend for fresh data now (otherwise it polls). */
  refresh(): Promise<void>

  setRole(role: Role): void
  setLang(lang: Lang): void
  setMidwifeId(id: string): void
  /** Forget this browser's settings. */
  clearLocalSettings(): void
}
