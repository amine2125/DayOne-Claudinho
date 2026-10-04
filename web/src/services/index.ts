import { useMemo, useSyncExternalStore } from 'react'
import { STATUSES_TO_REVIEW } from '@/contract/enums'
import { WAITING_FOR_NETWORK } from '@/contract/lifecycle'
import type { Field, Page, Patient, RegistryRecord } from '@/contract/types'
import type { AppState, DayOneApi } from './api'
import { httpApi } from './httpApi'

export const api: DayOneApi = httpApi

export function useAppState<T>(select: (s: AppState) => T): T {
  return useSyncExternalStore(api.subscribe, () => select(api.getState()))
}

export function useRecords(): RegistryRecord[] {
  const records = useAppState((s) => s.records)
  return useMemo(() => Object.values(records).sort((a, b) => b.createdAt.localeCompare(a.createdAt)), [records])
}

export function usePatients(): Patient[] {
  const patients = useAppState((s) => s.patients)
  return useMemo(() => Object.values(patients).sort((a, b) => a.code.localeCompare(b.code)), [patients])
}

export function useWaitingCount(): number {
  const records = useRecords()
  return records.filter((r) => WAITING_FOR_NETWORK.includes(r.state)).length
}

/* ---- derived data, shared by screens ---- */

export function openFields(page: Page): Field[] {
  return Object.values(page.fields).filter((f) => STATUSES_TO_REVIEW.includes(f.status))
}

export function recordsOf(state: AppState, patient: Patient): RegistryRecord[] {
  return patient.visitIds
    .flatMap((v) => state.visits[v]?.recordIds ?? [])
    .map((id) => state.records[id])
    .filter(Boolean)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt))
}

/** Latest known value of each field for a patient: newer pages override older ones. */
export function latestFields(state: AppState, patient: Patient): Record<string, Field & { pageType: Page['pageType']; recordId: string }> {
  const out: Record<string, Field & { pageType: Page['pageType']; recordId: string }> = {}
  for (const r of recordsOf(state, patient))
    for (const p of r.pages)
      for (const f of Object.values(p.fields)) out[`${p.pageType}.${f.key}`] = { ...f, pageType: p.pageType, recordId: r.id }
  return out
}

export function lastVisitDate(state: AppState, patient: Patient): string | undefined {
  return patient.visitIds.map((v) => state.visits[v]?.date).filter(Boolean).sort().at(-1)
}
