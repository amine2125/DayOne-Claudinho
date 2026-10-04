import { BarChart3Icon, HomeIcon, SettingsIcon, UsersIcon, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { can, type Permission } from '@/auth/roles'
import { LANGS, ROLES, type Role } from '@/contract/enums'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api, useAppState } from '@/services'
import { followUpFor } from '@/services/followup'
import { useT, type TKey } from '@/i18n'
import { cn } from '@/lib/utils'
import { ConnectivityBanner, ConnectivityToggle } from './Connectivity'

interface NavItem {
  to: string
  label: TKey
  icon: LucideIcon
  need?: Permission
  badge?: 'todo'
}
/** Navigation as data: a new screen is one entry. */
const NAV: NavItem[] = [
  { to: '/', label: 'nav.today', icon: HomeIcon, need: 'patient_profiles', badge: 'todo' },
  { to: '/patients', label: 'nav.patients', icon: UsersIcon, need: 'patient_profiles' },
  // Anonymised aggregates: only for supervisor and epidemiologist roles.
  { to: '/dashboard', label: 'nav.dashboard', icon: BarChart3Icon, need: 'dashboard' },
]

export function useNav() {
  const role = useAppState((s) => s.role)
  return NAV.filter((n) => !n.need || can(role, n.need))
}

/** Patients whose expected visit has passed: the number worth a glance. */
function useTodoCount() {
  const state = useAppState((s) => s)
  return Object.values(state.patients).filter((p) => ['LATE', 'LOST'].includes(followUpFor(state, p).bucket)).length
}

function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <span className="flex size-9 items-center justify-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground">
        <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M6 3h9l3 3v15H6z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      </span>
      <span className="text-lg font-bold tracking-tight">DayOne</span>
    </span>
  )
}

export function AppShell() {
  const t = useT()
  const nav = useNav()
  const todo = useTodoCount()
  const role = useAppState((s) => s.role)
  const midwifeId = useAppState((s) => s.midwifeId)
  const lang = useAppState((s) => s.lang)

  const badge = (item: NavItem) =>
    item.badge === 'todo' && todo > 0 ? (
      <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-review px-1.5 text-xs font-bold text-white">{todo}</span>
    ) : null

  return (
    <div className="flex min-h-dvh bg-background">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col bg-sidebar text-sidebar-foreground lg:flex">
        <div className="px-5 pt-5 pb-6">
          <Logo />
          <p className="mt-2 text-xs leading-snug text-sidebar-foreground/60">{t('app.tagline')}</p>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex h-11 items-center gap-3 rounded-lg px-3 text-[0.95rem] font-medium transition-colors',
                  isActive ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground',
                )
              }
            >
              <item.icon className="size-5" />
              {t(item.label)}
              {badge(item)}
            </NavLink>
          ))}
        </nav>
        <NavLink
          to="/settings"
          className={({ isActive }) => cn('m-3 flex items-center gap-3 rounded-xl p-3 hover:bg-sidebar-accent', isActive ? 'bg-sidebar-accent' : 'bg-sidebar-accent/60')}
        >
          <span className="flex-1">
            <span className={cn('block text-sm', midwifeId ? 'font-code font-bold' : 'text-sidebar-foreground/70')}>{midwifeId || t('settings.midwifeId')}</span>
            <span className="block text-xs text-sidebar-foreground/60">{t(`settings.role.${role}`)}</span>
          </span>
          <SettingsIcon className="size-5 text-sidebar-foreground/70" aria-label={t('nav.settings')} />
        </NavLink>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur">
          <div className="flex h-16 items-center gap-2 px-4 sm:px-6">
            <span className="text-foreground lg:hidden [&_span.bg-sidebar-primary]:bg-primary [&_span.bg-sidebar-primary]:text-primary-foreground">
              <Logo />
            </span>
            <div className="ml-auto flex items-center gap-2">
              <ConnectivityToggle />
              <Select value={role} onValueChange={(v) => api.setRole(v as Role)}>
                <SelectTrigger className="hidden h-10 sm:flex" aria-label={t('settings.role')}>
                  <SelectValue>{t(`settings.role.${role}`)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((r) => (
                    <SelectItem key={r} value={r}>
                      {t(`settings.role.${r}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="flex h-10 rounded-lg border p-0.5" role="group" aria-label={t('settings.lang')}>
                {LANGS.map((l) => (
                  <button
                    key={l}
                    type="button"
                    onClick={() => api.setLang(l)}
                    className={cn('rounded-md px-2.5 text-sm font-semibold uppercase', lang === l ? 'bg-primary text-primary-foreground' : 'text-muted-foreground')}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <ConnectivityBanner />
        </header>

        <main className="flex-1 pb-24 lg:pb-10">
          <Outlet />
        </main>

        {/* Mobile bottom nav: big targets, icon + word */}
        <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-background/95 backdrop-blur lg:hidden">
          {[...nav, { to: '/settings', label: 'nav.settings' as TKey, icon: SettingsIcon }].map((item: NavItem) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                cn('relative flex h-16 flex-1 flex-col items-center justify-center gap-1 text-[0.7rem] font-medium', isActive ? 'text-primary' : 'text-muted-foreground')
              }
            >
              <item.icon className="size-5" />
              <span className="max-w-full truncate px-1">{t(item.label)}</span>
              {item.badge === 'todo' && todo > 0 && (
                <span className="absolute top-2 left-1/2 ml-2 flex h-4 min-w-4 items-center justify-center rounded-full bg-review px-1 text-[0.65rem] font-bold text-white">{todo}</span>
              )}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  )
}

/** Standard page header: one title, one sentence, optional actions. */
export function PageHeader({ title, subtitle, actions, children }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 px-4 pt-6 pb-4 sm:px-6 lg:px-8 lg:pt-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
          {subtitle && <p className="max-w-2xl text-muted-foreground">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}
