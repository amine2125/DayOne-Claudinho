/**
 * In-browser implementation of DayOneApi. It plays the role of the phone's
 * offline store and of the backend: queueing, AI processing (from real pipeline
 * outputs), review, patient linking and sync, all through the state machine.
 * Persisted in localStorage so a page reload does not lose the demo.
 */
import { STATUSES_TO_REVIEW, type FieldStatus, type LifecycleState, type PageType } from '@/contract/enums'
import { canTransition } from '@/contract/lifecycle'
import { SCHEMAS, fieldBBox, fieldDef, isReadable } from '@/contract/registry'
import type { Field, FieldValue, Page, Patient, RegistryRecord, Visit } from '@/contract/types'
import { SAMPLES, sample, type Sample } from '@/data/samples'
import type { ActivityEvent, AppState, DayOneApi, LinkChoice, NewPage } from './api'
import { findCandidates } from './linking'

const STORAGE_KEY = 'dayone.demo.v2'
const STEP_MS = 900

const uid = (prefix: string) =>
  `${prefix}_${Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => 'abcdefghjkmnpqrstuvwxyz23456789'[b % 31]).join('')}`
const now = () => new Date().toISOString()
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

/* ---------- building fields from a pipeline output ---------- */

function fieldsFromSample(s: Sample, pageIndex: number, at: string): Record<string, Field> {
  const out: Record<string, Field> = {}
  for (const [key, p] of Object.entries(s.fields ?? {})) {
    const def = fieldDef(s.pageType, key)
    if (!def) continue
    out[key] = {
      key,
      section: def.group,
      value: p.value,
      status: p.status,
      confidence: p.confidence,
      origin: 'AI',
      method: p.source,
      bbox: fieldBBox(def),
      page: pageIndex,
      history: [{ at, by: 'AI', origin: 'AI', value: p.value, status: p.status }],
    }
  }
  return out
}

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

/** Seed helper: a page already reviewed by a midwife. */
function reviewedFields(s: Sample, pageIndex: number, at: string, by: string): Record<string, Field> {
  const fields = fieldsFromSample(s, pageIndex, at)
  for (const f of Object.values(fields)) {
    if (!STATUSES_TO_REVIEW.includes(f.status)) continue
    f.status = f.value === null ? 'UNKNOWN' : 'KNOWN'
    f.origin = 'CONFIRMED'
    f.history.push({ at, by, origin: 'CONFIRMED', value: f.value, status: f.status })
  }
  return fields
}

/* ---------- seed: 8 specimen patients at different points of the lifecycle ---------- */

const MIDWIFE = 'SF-014'
const CODES = ['AMN-27', 'BKT-14', 'FZR-63', 'HDL-08', 'KSB-51', 'MRY-39', 'NJW-72', 'TQL-45']

function seed(): AppState {
  const s: AppState = {
    online: false,
    records: {},
    patients: {},
    visits: {},
    midwifeId: MIDWIFE,
    role: 'MIDWIFE',
    lang: 'fr',
    busy: [],
    activity: [],
  }
  const history = (states: LifecycleState[], at: string) => states.map((state) => ({ state, at }))
  const SYNCED_PATH: LifecycleState[] = ['CAPTURED', 'PENDING_AI', 'AI_PROCESSED', 'NEEDS_REVIEW', 'VALIDATED', 'PATIENT_LINKED', 'SAVED', 'SYNCED']

  const addRecord = (
    code: string,
    samples: Sample[],
    at: string,
    states: LifecycleState[],
    opts: { patientId?: string; read?: boolean; reviewed?: boolean } = {},
  ): RegistryRecord => {
    const r: RegistryRecord = {
      id: uid('rec'),
      midwifeId: MIDWIFE,
      createdAt: at,
      state: states[states.length - 1],
      history: history(states, at),
      patientCode: code,
      patientId: opts.patientId,
      pages: samples.map((smp, i) => ({
        id: uid('pg'),
        pageType: smp.pageType,
        imageUrl: smp.imageUrl,
        imageSize: smp.imageSize,
        capturedAt: at,
        quality: { ok: true },
        fields: !opts.read ? {} : opts.reviewed ? reviewedFields(smp, i, at, MIDWIFE) : fieldsFromSample(smp, i, at),
      })),
    }
    s.records[r.id] = r
    SAMPLE_OF.set(r.id, samples.map((x) => x.id))
    if (opts.patientId) {
      const v: Visit = { id: uid('vis'), patientId: opts.patientId, date: at, midwifeId: MIDWIFE, recordIds: [r.id] }
      s.visits[v.id] = v
      s.patients[opts.patientId].visitIds.push(v.id)
      r.visitId = v.id
    }
    return r
  }
  const addPatient = (code: string, at: string): Patient => {
    const p: Patient = { id: uid('pt'), code, createdAt: at, visitIds: [] }
    s.patients[p.id] = p
    return p
  }

  const page = (n: number) => sample(`page_${String(n).padStart(2, '0')}`)
  const deliveryDate = (n: number) => String(page(n * 8 - 4).fields?.date_accouchement?.value ?? '2026-06-01')
  const shift = (iso: string, days: number) => new Date(new Date(iso).getTime() + days * 864e5).toISOString()

  /**
   * Booklet pages photographed per patient (1..8 = page position in the booklet).
   * Chosen so the Today screen shows every case: late, this week, lost to follow-up, done.
   */
  const BOOKLET: Record<number, number[]> = {
    1: [2, 4, 5, 6, 7, 8], // follow-up complete
    2: [2, 4, 5, 6, 7, 8],
    3: [2, 4, 5, 6, 7, 8],
    4: [2, 4, 5, 6], // late postpartum visit missed for weeks: to recontact
    5: [2, 4, 5, 6, 7, 8],
    6: [2, 4, 5, 6], // late postpartum visit overdue
    7: [2, 4, 5, 6], // late postpartum visit due this week
    8: [2, 4], // early postpartum visit overdue (a photo is waiting for the network)
  }
  const POSTPARTUM_DAY: Record<number, number> = { 5: 3, 6: 3, 7: 41, 8: 41 }

  for (let n = 1; n <= 8; n++) {
    const code = CODES[n - 1]
    const birth = new Date(deliveryDate(n) + 'T10:00:00').toISOString()
    const p = addPatient(code, shift(birth, -(120 + n * 3)))
    for (const pos of BOOKLET[n]) {
      const at = pos === 2 ? p.createdAt : pos === 4 ? birth : shift(birth, POSTPARTUM_DAY[pos])
      // Pages 5–8 come in pairs (mother + newborn) photographed the same day: one record.
      if (pos === 6 || pos === 8) continue
      const pages = pos >= 5 ? [page(n * 8 - 8 + pos), page(n * 8 - 7 + pos)] : [page(n * 8 - 8 + pos)]
      const waitingSync = n === 4 && pos === 5
      addRecord(code, pages, at, waitingSync ? SYNCED_PATH.slice(0, 7) : SYNCED_PATH, { patientId: p.id, read: true, reviewed: true })
    }
  }

  // Photographed this morning without network: early postpartum pages of TQL-45, waiting for the AI.
  addRecord(CODES[7], [page(61), page(62)], '2026-10-03T08:12:00.000Z', ['CAPTURED', 'PENDING_AI'])

  // A look-alike code (NJW-12 vs NJW-72), entered by hand: still pregnant, next antenatal visit later this month.
  const twin = addPatient('NJW-12', '2026-09-20T09:00:00.000Z')
  const manual = addRecord('NJW-12', [], '2026-09-20T09:00:00.000Z', SYNCED_PATH, { patientId: twin.id })
  const manualFields = blankFields('identification_antecedents', 0)
  for (const [k, v] of Object.entries({ age: 25, gestation: 1, parite: 0, enfants_vivants: 0 })) {
    Object.assign(manualFields[k], { value: v, status: 'KNOWN', confidence: 1 })
    manualFields[k].history = [{ at: manual.createdAt, by: MIDWIFE, origin: 'MANUAL', value: v, status: 'KNOWN' }]
  }
  for (const f of Object.values(manualFields)) if (f.value === null) Object.assign(f, { status: 'NOT_PROVIDED', confidence: 1 })
  manual.pages = [{ id: uid('pg'), pageType: 'identification_antecedents', imageSize: [1654, 2339], capturedAt: manual.createdAt, fields: manualFields }]

  // A real field photo with another layout: the template cannot be aligned.
  addRecord('DRS-90', [sample('photo_1')], '2026-10-01T10:30:00.000Z', ['CAPTURED', 'PENDING_AI', 'PROCESSING_FAILED']).failure = {
    reason: 'LAYOUT',
    at: '2026-10-01T10:31:00.000Z',
  }
  return s
}

/** Demo-only link between a record's pages and the bundled samples (stands in for the backend reading the photo). */
const SAMPLE_OF = new Map<string, (string | undefined)[]>()

/* ---------- store ---------- */

function load(): AppState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const { state, samples } = JSON.parse(raw) as { state: AppState; samples: [string, (string | undefined)[]][] }
      samples.forEach(([k, v]) => SAMPLE_OF.set(k, v))
      return { ...state, busy: [] }
    }
  } catch {
    /* storage unavailable: start fresh */
  }
  return seed()
}

class MockApi implements DayOneApi {
  private state: AppState = load()
  private listeners = new Set<() => void>()

  constructor() {
    if (this.state.online) void this.drain()
  }

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
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ state: next, samples: [...SAMPLE_OF] }))
    } catch {
      /* private mode: keep going in memory */
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
    if (online) void this.drain()
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
    SAMPLE_OF.clear()
    const fresh = seed()
    this.commit((s) => Object.assign(s, fresh, { lang: s.lang, role: s.role }))
  }

  /* ---- capture & offline queue ---- */
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
    SAMPLE_OF.set(record.id, pages.map((p) => p.sampleId))
    this.commit((s) => {
      s.records[record.id] = record
      this.log(s, { kind: 'CAPTURE', recordId: record.id, text: 'CAPTURED' })
      this.move(s, record.id, 'PENDING_AI')
    })
    if (this.state.online) void this.drain()
    return this.state.records[record.id]
  }

  retry(recordId: string) {
    const r = this.state.records[recordId]
    this.commit((s) => {
      if (r.state === 'PROCESSING_FAILED') this.move(s, recordId, 'PENDING_AI')
      if (r.state === 'SYNC_FAILED') this.move(s, recordId, 'SAVED')
    })
    if (this.state.online) void this.drain()
  }

  retakePhoto(recordId: string, pageIndex: number, page: NewPage) {
    const ids = SAMPLE_OF.get(recordId) ?? []
    ids[pageIndex] = page.sampleId
    SAMPLE_OF.set(recordId, ids)
    this.commit((s) => {
      const r = s.records[recordId]
      r.pages[pageIndex] = { id: uid('pg'), pageType: page.pageType, imageUrl: page.imageUrl, imageSize: page.imageSize, capturedAt: now(), quality: { ok: true }, fields: {}, supersedes: r.pages[pageIndex]?.id }
      r.failure = undefined
      this.move(s, recordId, 'CAPTURED', 'RETAKE')
      this.move(s, recordId, 'PENDING_AI')
    })
    if (this.state.online) void this.drain()
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

  /** Runs whenever the network is back: AI reading for queued photos, then sync. */
  private draining = false
  private async drain() {
    if (this.draining) return
    this.draining = true
    try {
      while (this.state.online) {
        const next = Object.values(this.state.records).find((r) => r.state === 'PENDING_AI' || r.state === 'SAVED')
        if (!next) break
        this.commit((s) => void s.busy.push(next.id))
        await wait(STEP_MS * (next.state === 'PENDING_AI' ? next.pages.length + 1 : 1))
        if (!this.state.online) {
          this.commit((s) => void (s.busy = s.busy.filter((x) => x !== next.id)))
          break // connection lost mid-way: the record stays queued, nothing is lost
        }
        this.commit((s) => {
          s.busy = s.busy.filter((x) => x !== next.id)
          if (next.state === 'SAVED') return this.move(s, next.id, 'SYNCED')
          const r = s.records[next.id]
          const ids = SAMPLE_OF.get(r.id) ?? []
          // A page type without a template is kept as an image; a templated page the AI cannot align fails.
          const results = r.pages.map((p, i) => {
            const smp = ids[i] ? SAMPLES.find((x) => x.id === ids[i]) : undefined
            if (!isReadable(p.pageType)) return { ok: true, fields: {} }
            return smp?.fields ? { ok: true, fields: fieldsFromSample(smp, i, now()) } : { ok: false, fields: {} }
          })
          if (results.every((x) => !x.ok)) {
            r.failure = { reason: 'LAYOUT', at: now() }
            return this.move(s, r.id, 'PROCESSING_FAILED')
          }
          r.pages.forEach((p, i) => (p.fields = results[i].fields))
          this.move(s, r.id, 'AI_PROCESSED')
          this.move(s, r.id, 'NEEDS_REVIEW')
        })
      }
    } finally {
      this.draining = false
    }
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
    if (this.state.online) void this.drain()
  }
}

export const mockApi = new MockApi()
