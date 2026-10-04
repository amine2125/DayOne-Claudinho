/**
 * Role-based access in one table. Screens ask useCan('original_image'),
 * never "role === …", so adding a role or a permission is one line here.
 */
import type { Role } from '@/contract/enums'
import { useAppState } from '@/services'

export const PERMISSIONS = {
  patient_profiles: ['MIDWIFE', 'SUPERVISOR'],
  /** The registry photo, always with personal zones masked. */
  original_image: ['MIDWIFE', 'SUPERVISOR'],
  dashboard: ['SUPERVISOR', 'EPIDEMIOLOGIST'],
} as const satisfies Record<string, readonly Role[]>

export type Permission = keyof typeof PERMISSIONS

export function can(role: Role, permission: Permission): boolean {
  return (PERMISSIONS[permission] as readonly Role[]).includes(role)
}

export function useCan(permission: Permission): boolean {
  return can(useAppState((s) => s.role), permission)
}
