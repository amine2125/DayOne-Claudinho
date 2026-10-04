/**
 * Local implementation of DayOneApi, used until the backend is connected.
 * It starts EMPTY: records and patients will come from the backend once the
 * WhatsApp agent sends real captures. Only the viewer's settings (role,
 * language, midwife ID) are remembered in this browser.
 *
 * The write operations follow the state machine so the backend client can be
 * swapped in without changing any screen.
 */
import { STATUSES_TO_REVIEW, type FieldStatus, type LifecycleState, type PageType } from '@/contract/enums'
import { canTransition } from '@/contract/lifecycle'
import { SCHEMAS, fieldBBox } from '@/contract/registry'
import type { Field, FieldValue, Page, Patient, RegistryRecord } from '@/contract/types'
import type { ActivityEvent, AppState, DayOneApi, LinkChoice, NewPage } from './api'
import { findCandidates } from './linking'

const SETTINGS_KEY = 'dayone.settings.v1'

const uid = (prefix: string) =>
  `${prefix}_${Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => 'abcdefghjkmnpqrstuvwxyz23456789'[b % 31]).join('')}`
const now = () => new Date().toISOString()

function blankFields(pageType: PageType, pageIndex: number): Record<string, Field> {
  const out: Record<string, Field> = {}
  for (const def of SCHEMAS[pageType]?.fields ?? [])
    out[def.id] = {
      key: def.id,
      section: def.group,
      value: null,
      status: 'NEEDS_REVIEW',
      confidence: 0,
      origin: 'MANUAL',
      bbox: fieldBBox(def),
      page: pageIndex,
      history: [],
    }
  return out
}

type Settings = Pick<AppState, 'midwifeId' | 'role' | 'lang'>

function emptyState(settings?: Partial<Settings>): AppState {
  return {
    online: true,
    records: {},
    patients: {},
    visits: {},
    midwifeId: settings?.midwifeId ?? '',
    role: settings?.role ?? 'MIDWIFE',
    lang: settings?.lang ?? 'fr',
    busy: [],
    activity: [],
  }
}

function loadSettings(): Partial<Settings> {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? '{}') as Partial<Settings>
  } catch {
    return {}
  }
}

class LocalApi implements DayOneApi {
  private state: AppState = emptyState(loadSettings())
  private listeners = new Set<() => void>()

  getState = () => this.state
  subscribe = (l: () => void) => {
    this.listeners.add(l)
    return () => this.listeners.delete(l)
  }

  private commit(mut: (s: AppState) => void) {
    const next = structuredClone(this.state)
    mut(next)
    this.state = next
    try {
      const { midwifeId, role, lang } = next
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({ midwifeId, role, lang }))
    } catch {
      /* private mode: settings live in memory only */
    }
    this.listeners.forEach((l) => l())
  }

  private log(s: AppState, e: Omit<ActivityEvent, 'id' | 'at'>) {
    s.activity = [{ id: uid('ev'), at: now(), ...e }, ...s.activity].slice(0, 60)
  }

  private move(s: AppState, id: string, to: LifecycleState, note?: string) {
    const r = s.records[id]
    if (!canTransition(r.state, to)) throw new Error(`Transition refused: ${r.state} → ${to}`)
    r.state = to
    r.history.push({ state: to, at: now(), note })
    this.log(s, { kind: 'TRANSITION', recordId: id, text: to })
  }

  /* ---- settings ---- */
  setOnline(online: boolean) {
    this.commit((s) => {
      s.online = online
      this.log(s, { kind: 'NETWORK', text: online ? 'ONLINE' : 'OFFLINE' })
    })
  }
  setRole(role: AppState['role']) {
    this.commit((s) => void (s.role = role))
  }
  setLang(lang: AppState['lang']) {
    this.commit((s) => void (s.lang = lang))
  }
  setMidwifeId(id: string) {
    this.commit((s) => void (s.midwifeId = id))
  }
  resetDemo() {
    this.commit((s) => Object.assign(s, emptyState({ lang: s.lang, role: s.role, midwifeId: s.midwifeId })))
  }

  /* ---- capture & queue (the AI reading itself is done by the backend) ---- */
  capture(patientCode: string, pages: NewPage[]) {
    const at = now()
    const record: RegistryRecord = {
      id: uid('rec'),
      midwifeId: this.state.midwifeId,
      createdAt: at,
      state: 'CAPTURED',
      history: [{ state: 'CAPTURED', at }],
      patientCode: patientCode.trim().toUpperCase(),
      pages: pages.map((p) => ({ id: uid('pg'), pageType: p.pageType, imageUrl: p.imageUrl, imageSize: p.imageSize, capturedAt: at, quality: { ok: true }, fields: {} })),
    }
    this.commit((s) => {
      s.records[record.id] = record
      this.log(s, { kind: 'CAPTURE', recordId: record.id, text: 'CAPTURED' })
      this.move(s, record.id, 'PENDING_AI')
    })
    return this.state.records[record.id]
  }

  retry(recordId: string) {
    this.commit((s) => {
      const r = s.records[recordId]
      if (r.state === 'PROCESSING_FAILED') this.move(s, recordId, 'PENDING_AI')
      if (r.state === 'SYNC_FAILED') this.move(s, recordId, 'SAVED')
    })
  }

  retakePhoto(recordId: string, pageIndex: number, page: NewPage) {
    this.commit((s) => {
      const r = s.records[recordId]
      r.pages[pageIndex] = { id: uid('pg'), pageType: page.pageType, imageUrl: page.imageUrl, imageSize: page.imageSize, capturedAt: now(), quality: { ok: true }, fields: {}, supersedes: r.pages[pageIndex]?.id }
      r.failure = undefined
      this.move(s, recordId, 'CAPTURED', 'RETAKE')
      this.move(s, recordId, 'PENDING_AI')
    })
  }

  startManualEntry(recordId: string) {
    this.commit((s) => {
      const r = s.records[recordId]
      r.pages.forEach((p, i) => {
        if (Object.keys(p.fields).length === 0) p.fields = blankFields(p.pageType, i)
      })
      this.move(s, recordId, 'MANUAL_REVIEW_REQUIRED')
    })
  }

  /* ---- review ---- */
  private editField(recordId: string, pageIndex: number, key: string, edit: (f: Field) => void) {
    this.commit((s) => {
      const f = s.records[recordId].pages[pageIndex].fields[key]
      edit(f)
      f.history.push({ at: now(), by: s.midwifeId, origin: f.origin, value: f.value, status: f.status })
      this.log(s, { kind: 'FIELD', recordId, text: key })
    })
  }

  confirmField(recordId: string, pageIndex: number, key: string) {
    this.editField(recordId, pageIndex, key, (f) => {
      f.origin = f.origin === 'MANUAL' ? 'MANUAL' : 'CONFIRMED'
      f.status = f.value === null ? 'NOT_PROVIDED' : 'KNOWN'
    })
  }

  setField(recordId: string, pageIndex: number, key: string, value: FieldValue, status: FieldStatus) {
    this.editField(recordId, pageIndex, key, (f) => {
      if (f.origin === 'AI' && f.aiValue === undefined) f.aiValue = f.value
      f.origin = f.origin === 'MANUAL' ? 'MANUAL' : value === f.value && status === f.status ? 'CONFIRMED' : 'CORRECTED'
      f.value = value
      f.status = status
    })
  }

  markSectionBlank(recordId: string, pageIndex: number, section: string) {
    this.commit((s) => {
      const page: Page = s.records[recordId].pages[pageIndex]
      for (const f of Object.values(page.fields)) {
        if (f.section !== section || !STATUSES_TO_REVIEW.includes(f.status) || f.value !== null) continue
        f.status = 'NOT_PROVIDED'
        f.history.push({ at: now(), by: s.midwifeId, origin: f.origin, value: null, status: 'NOT_PROVIDED' })
      }
    })
  }

  validate(recordId: string) {
    const open = this.state.records[recordId].pages.some((p) => Object.values(p.fields).some((f) => STATUSES_TO_REVIEW.includes(f.status)))
    if (open) throw new Error('Some fields still need review')
    this.commit((s) => this.move(s, recordId, 'VALIDATED'))
  }

  /* ---- patient linking ---- */
  private fieldsOf = (patient: Patient): Field[] =>
    patient.visitIds
      .flatMap((v) => this.state.visits[v]?.recordIds ?? [])
      .flatMap((r) => this.state.records[r]?.pages ?? [])
      .flatMap((p) => Object.values(p.fields))

  candidates(recordId: string) {
    return findCandidates(this.state.records[recordId], Object.values(this.state.patients), this.fieldsOf)
  }

  link(recordId: string, choice: LinkChoice) {
    this.commit((s) => {
      const r = s.records[recordId]
      if (choice.decision === 'UNSURE') {
        if (r.state === 'VALIDATED') this.move(s, recordId, 'SUSPECTED_DUPLICATE')
        return
      }
      let patientId: string
      if (choice.decision === 'EXISTING') patientId = choice.patientId
      else {
        patientId = uid('pt') // random, never derived from the code or the page
        s.patients[patientId] = { id: patientId, code: r.patientCode, createdAt: now(), visitIds: [] }
      }
      const patient = s.patients[patientId]
      // A page type already in the file is superseded by the new photo; the old one stays in history.
      const previous = patient.visitIds.flatMap((v) => s.visits[v].recordIds).flatMap((id) => s.records[id].pages)
      for (const p of r.pages) p.supersedes ??= previous.filter((x) => x.pageType === p.pageType).at(-1)?.id
      const day = r.createdAt.slice(0, 10)
      let visit = patient.visitIds.map((v) => s.visits[v]).find((v) => v.date.slice(0, 10) === day)
      if (!visit) {
        visit = { id: uid('vis'), patientId, date: r.createdAt, midwifeId: r.midwifeId, recordIds: [] }
        s.visits[visit.id] = visit
        patient.visitIds.push(visit.id)
      }
      visit.recordIds.push(r.id)
      r.patientId = patientId
      r.visitId = visit.id
      this.move(s, recordId, 'PATIENT_LINKED')
      this.log(s, { kind: 'LINK', recordId, text: choice.decision })
      this.move(s, recordId, 'SAVED')
    })
  }
}

export const localApi = new LocalApi()
