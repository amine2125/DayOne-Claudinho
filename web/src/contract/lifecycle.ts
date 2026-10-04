/**
 * The record state machine, in one place. The service layer refuses any
 * transition not listed here; the UI uses STEPS to show progress in plain words.
 */
import type { LifecycleState } from './enums'

export const TRANSITIONS: Record<LifecycleState, readonly LifecycleState[]> = {
  CAPTURED: ['PENDING_AI', 'MANUAL_REVIEW_REQUIRED'],
  PENDING_AI: ['AI_PROCESSED', 'PROCESSING_FAILED'],
  AI_PROCESSED: ['NEEDS_REVIEW'],
  NEEDS_REVIEW: ['VALIDATED', 'CAPTURED', 'MANUAL_REVIEW_REQUIRED'],
  MANUAL_REVIEW_REQUIRED: ['VALIDATED', 'CAPTURED'],
  PROCESSING_FAILED: ['PENDING_AI', 'MANUAL_REVIEW_REQUIRED', 'CAPTURED'],
  VALIDATED: ['PATIENT_LINKED', 'SUSPECTED_DUPLICATE'],
  SUSPECTED_DUPLICATE: ['PATIENT_LINKED'],
  PATIENT_LINKED: ['SAVED'],
  SAVED: ['SYNCED', 'SYNC_FAILED'],
  SYNC_FAILED: ['SYNCED', 'SAVED'],
  SYNCED: [],
}

export function canTransition(from: LifecycleState, to: LifecycleState): boolean {
  return TRANSITIONS[from].includes(to)
}

/**
 * Five steps a midwife understands, each grouping technical states.
 * The stepper shows the step; the exact state is a small caption.
 */
export const STEPS = [
  { id: 'photo', states: ['CAPTURED', 'PENDING_AI'] },
  { id: 'reading', states: ['AI_PROCESSED', 'PROCESSING_FAILED'] },
  { id: 'review', states: ['NEEDS_REVIEW', 'MANUAL_REVIEW_REQUIRED'] },
  { id: 'patient', states: ['VALIDATED', 'SUSPECTED_DUPLICATE'] },
  { id: 'sent', states: ['PATIENT_LINKED', 'SAVED', 'SYNC_FAILED', 'SYNCED'] },
] as const satisfies readonly { id: string; states: readonly LifecycleState[] }[]
export type StepId = (typeof STEPS)[number]['id']

export function stepIndex(state: LifecycleState): number {
  return STEPS.findIndex((s) => (s.states as readonly LifecycleState[]).includes(state))
}

/** What the midwife has to do next, if anything. Drives buttons and the home screen. */
export type NextAction = 'WAIT_NETWORK' | 'REVIEW' | 'LINK' | 'RETRY' | 'NONE'
export function nextAction(state: LifecycleState, online: boolean): NextAction {
  switch (state) {
    case 'CAPTURED':
    case 'PENDING_AI':
    case 'SAVED':
      return online ? 'NONE' : 'WAIT_NETWORK'
    case 'NEEDS_REVIEW':
    case 'MANUAL_REVIEW_REQUIRED':
      return 'REVIEW'
    case 'VALIDATED':
    case 'SUSPECTED_DUPLICATE':
      return 'LINK'
    case 'PROCESSING_FAILED':
    case 'SYNC_FAILED':
      return 'RETRY'
    default:
      return 'NONE'
  }
}

/** States that still need the network: counted in "N waiting for sync". */
export const WAITING_FOR_NETWORK: readonly LifecycleState[] = ['CAPTURED', 'PENDING_AI', 'SAVED', 'SYNC_FAILED']
