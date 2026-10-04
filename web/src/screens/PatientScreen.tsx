import {
  ArrowRightIcon,
  BookOpenIcon,
  CalendarClockIcon,
  ChartLineIcon,
  CircleCheckIcon,
  ClipboardListIcon,
  HistoryIcon,
  ImageIcon,
  ImagesIcon,
  NotebookPenIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { can, type Permission } from '@/auth/roles'
import { PAGE_TYPES, type PageType } from '@/contract/enums'
import { NOTED_SECTIONS, SUMMARY_FIELDS, fieldDef, isNoteworthy } from '@/contract/registry'
import type { Field, Page, Patient, RegistryRecord } from '@/contract/types'
import { PageImage } from '@/components/PageImage'
import { PatientCode } from '@/components/PatientCode'
import { Appointments, Trends } from '@/components/PatientTrends'
import { RecordRow } from '@/components/RecordRow'
import { StatusBadge } from '@/components/status'
import { VisitTimeline } from '@/components/VisitTimeline'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { lastVisitDate, latestFields, openFields, recordsOf, useAppState } from '@/services'
import type { AppState } from '@/services/api'
import { normalizeCode } from '@/services/linking'
import { formatValue, useT, type T, type TKey } from '@/i18n'
import { cn } from '@/lib/utils'

type Latest = ReturnType<typeof latestFields>

interface Ctx {
  state: AppState
  patient: Patient
  latest: Latest
  records: RegistryRecord[]
  /** Records with this code still waiting for review or a patient decision. */
  pending: RegistryRecord[]
  t: T
}

/**
 * Profile tabs as a list of modules. Adding "Stocks" or "Expected appointments"
 * is one entry here; nothing else in the screen changes.
 */
const MODULES: { id: string; label: TKey; icon: LucideIcon; need?: Permission; soon?: boolean; render: (c: Ctx) => ReactNode }[] = [
  { id: 'summary', label: 'patient.tab.summary', icon: ClipboardListIcon, render: (c) => <Summary {...c} /> },
  { id: 'trends', label: 'patient.tab.trends', icon: ChartLineIcon, render: (c) => <Trends state={c.state} patient={c.patient} t={c.t} /> },
  { id: 'visits', label: 'patient.tab.visits', icon: HistoryIcon, render: (c) => <Visits {...c} /> },
  { id: 'appointments', label: 'patient.tab.appointments', icon: CalendarClockIcon, render: (c) => <Appointments state={c.state} patient={c.patient} t={c.t} /> },
  { id: 'booklet', label: 'patient.tab.booklet', icon: BookOpenIcon, render: (c) => <Booklet {...c} /> },
  { id: 'images', label: 'patient.tab.images', icon: ImagesIcon, need: 'original_image', render: (c) => <Images {...c} /> },
]

export function PatientScreen() {
  const { id = '' } = useParams()
  const t = useT()
  const state = useAppState((s) => s)
  const patient = state.patients[id]
  if (!patient) return <p className="p-8 text-muted-foreground">{t('patient.notFound')}</p>

  const records = recordsOf(state, patient)
  const latest = latestFields(state, patient)
  const pending = Object.values(state.records).filter(
    (r) => !r.patientId && normalizeCode(r.patientCode) === normalizeCode(patient.code) && r.state !== 'SYNCED',
  )
  const ctx: Ctx = { state, patient, latest, records, pending, t }
  const v = (k: string) => latest[`identification_antecedents.${k}`]?.value
  const modules = MODULES.filter((m) => !m.need || can(state.role, m.need))

  return (
    <div className="mx-auto max-w-6xl">
      {/* Identity card: the code is the identity */}
      <div className="px-4 pt-6 sm:px-6 lg:px-8 lg:pt-8">
        <div className="flex flex-col gap-4 rounded-2xl bg-sidebar p-5 text-sidebar-foreground sm:flex-row sm:items-end sm:justify-between sm:p-6">
          <div className="flex flex-col gap-1">
            <span className="text-xs font-semibold tracking-widest text-sidebar-foreground/60 uppercase">{t('patient.label')}</span>
            <PatientCode code={patient.code} size="xl" className="text-sidebar-foreground" />
            <span className="font-code text-xs text-sidebar-foreground/50">
              {t('patient.internalId')} · {patient.id}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {typeof v('age') === 'number' && <Chip>{t('patient.age', { n: v('age') as number })}</Chip>}
            {v('gestation') != null && (
              <Chip mono>{t('patient.gp', { g: String(v('gestation')), p: v('parite') == null ? '?' : String(v('parite')) })}</Chip>
            )}
            <Chip>{t('link.visits', { n: patient.visitIds.length })}</Chip>
            <Chip>{t('patient.lastVisit', { date: t.date(lastVisitDate(state, patient)) })}</Chip>
          </div>
        </div>
      </div>

      <Tabs defaultValue="summary" className="px-4 pt-5 pb-10 sm:px-6 lg:px-8">
        <TabsList className="mb-5 h-auto w-full flex-wrap justify-start gap-1 sm:w-auto">
          {modules.map((m) => (
            <TabsTrigger key={m.id} value={m.id} className="h-10 gap-2 px-3 text-sm">
              <m.icon className="size-4" />
              {t(m.label)}
              {m.soon && <span className="rounded bg-muted px-1.5 text-[0.65rem] text-muted-foreground uppercase">{t('patient.soon')}</span>}
            </TabsTrigger>
          ))}
        </TabsList>
        {modules.map((m) => (
          <TabsContent key={m.id} value={m.id}>
            {m.render(ctx)}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}

function Chip({ children, mono }: { children: ReactNode; mono?: boolean }) {
  return <span className={cn('rounded-full bg-sidebar-accent px-3 py-1.5 text-sm font-semibold', mono && 'font-code')}>{children}</span>
}

function Card({ title, icon: Icon, hint, children, className }: { title: string; icon?: LucideIcon; hint?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('flex flex-col gap-3 rounded-2xl border bg-card p-4 sm:p-5', className)}>
      <header>
        <h2 className="flex items-center gap-2 text-lg font-bold">
          {Icon && <Icon className="size-5 text-primary" />}
          {title}
        </h2>
        {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
      </header>
      {children}
    </section>
  )
}

/* ---------------- Summary ---------------- */

function Summary({ latest, pending, records, t }: Ctx) {
  const value = (pageType: PageType, key: string) => latest[`${pageType}.${key}`]
  const noted = Object.values(latest).filter((f) => NOTED_SECTIONS.includes(f.section) && f.status === 'KNOWN' && isNoteworthy(f.value))
  const deliveries = [1, 2, 3, 4, 5]
    .map((n) => ['date', 'modalite', 'poids', 'complication'].map((k) => value('identification_antecedents', `acc${n}_${k}`)))
    .filter((row) => row.some((f) => f && f.value !== null))
  const todo = records.flatMap((r) => r.pages.flatMap((p) => openFields(p).map((f) => ({ r, f }))))

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card title={t('patient.keyFacts')} className="lg:col-span-2">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {SUMMARY_FIELDS.map(({ pageType, key }) => {
            const f = value(pageType, key)
            const kind = fieldDef(pageType, key)?.kind
            return (
              <div key={key} className="flex flex-col gap-1 rounded-xl bg-muted/70 p-3">
                <dt className="text-xs text-muted-foreground">{t(`fact.${key}` as TKey)}</dt>
                <dd className={cn('text-xl leading-tight font-bold', !f || f.value === null ? 'text-muted-foreground' : '')}>
                  {f ? formatValue(t, kind, f.value) : '—'}
                </dd>
                {f && f.status !== 'KNOWN' && <StatusBadge status={f.status} size="sm" />}
              </div>
            )
          })}
        </dl>
      </Card>

      <Card title={t('patient.dataTodo')} icon={NotebookPenIcon}>
        {pending.length === 0 && todo.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-known">
            <CircleCheckIcon className="size-4" /> {t('patient.dataTodoNone')}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {pending.map((r) => (
              <RecordRow key={r.id} record={r} className="sm:flex-col sm:items-stretch" />
            ))}
            {todo.map(({ r, f }) => (
              <Link key={r.id + f.key} to={`/records/${r.id}/review`} className="flex items-center gap-2 rounded-lg border p-2 text-sm hover:border-primary">
                <TriangleAlertIcon className="size-4 text-review" />
                {t.field(r.pages[f.page].pageType, f.key, f.label)}
                <ArrowRightIcon className="ml-auto size-4" />
              </Link>
            ))}
          </div>
        )}
      </Card>

      <Card title={t('patient.noted')} hint={t('patient.notedHint')} className="lg:col-span-2">
        {noted.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('patient.notedNone')}</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {noted.map((f) => (
              <NotedRow key={f.pageType + f.key} field={f} pageType={f.pageType} />
            ))}
          </ul>
        )}
        {deliveries.length > 0 && (
          <div className="mt-2 flex flex-col gap-2">
            <h3 className="text-sm font-semibold text-muted-foreground">{t('patient.previousDeliveries')}</h3>
            <ol className="flex flex-col gap-1.5">
              {deliveries.map((row, i) => (
                <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-muted/60 px-3 py-2 text-sm">
                  <span className="font-code font-bold">#{i + 1}</span>
                  {row.map((f, j) =>
                    f && f.value !== null ? (
                      <span key={j} className={j === 1 ? 'font-semibold' : ''}>
                        {formatValue(t, fieldDef('identification_antecedents', f.key)?.kind, f.value)}
                      </span>
                    ) : null,
                  )}
                </li>
              ))}
            </ol>
          </div>
        )}
      </Card>

      <Card title={t('patient.vaccines')}>
        <Vaccines latest={latest} t={t} />
      </Card>
    </div>
  )
}

function NotedRow({ field, pageType }: { field: Field; pageType: PageType }) {
  const t = useT()
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-2">
      <span className="text-sm text-muted-foreground">{t.field(pageType, field.key, field.label)}</span>
      <span className="font-semibold">{formatValue(t, field.kind ?? fieldDef(pageType, field.key)?.kind, field.value)}</span>
    </li>
  )
}

function Vaccines({ latest, t }: { latest: Latest; t: T }) {
  const f = (k: string) => latest[`identification_antecedents.${k}`]
  const ticked = (k: string) => f(k)?.value === true
  return (
    <div className="flex flex-col gap-3">
      <div>
        <span className="text-sm text-muted-foreground">VAT</span>
        <div className="mt-1 flex gap-1.5">
          {[1, 2, 3, 4, 5].map((n) => (
            <span
              key={n}
              className={cn(
                'flex size-9 items-center justify-center rounded-lg border-2 text-sm font-bold',
                ticked(`vat_${n}`) ? 'border-known bg-known-soft text-known' : 'border-dashed text-muted-foreground',
              )}
            >
              {n}
            </span>
          ))}
        </div>
      </div>
      {(['rubeole', 'hepatite_b'] as const).map((k) => (
        <div key={k} className="flex items-center justify-between gap-2 text-sm">
          <span className="flex items-center gap-2">
            {ticked(k) ? <CircleCheckIcon className="size-4 text-known" /> : <span className="size-4 rounded border-2 border-dashed" />}
            {t.field('identification_antecedents', k)}
          </span>
          <span className="text-muted-foreground">{f(`${k}_date`)?.value ? t.date(String(f(`${k}_date`)!.value)) : ''}</span>
        </div>
      ))}
    </div>
  )
}

/* ---------------- Visits ---------------- */

function Visits({ state, patient }: Ctx) {
  return (
    <div className="max-w-2xl rounded-2xl border bg-card p-5">
      <VisitTimeline visits={patient.visitIds.map((v) => state.visits[v])} records={state.records} />
    </div>
  )
}

/* ---------------- Booklet ---------------- */

type BookletState = 'done' | 'review' | 'image' | 'missing'

function Booklet({ records, pending, t }: Ctx) {
  const all = [...records, ...pending]
  const latestPage = (pt: PageType): { page: Page; record: RegistryRecord; index: number } | undefined => {
    let hit: { page: Page; record: RegistryRecord; index: number } | undefined
    for (const r of all) r.pages.forEach((p, i) => p.pageType === pt && (hit = { page: p, record: r, index: i }))
    return hit
  }
  const STYLE: Record<BookletState, { icon: LucideIcon; label: TKey; cls: string }> = {
    done: { icon: CircleCheckIcon, label: 'patient.booklet.done', cls: 'text-known bg-known-soft' },
    review: { icon: TriangleAlertIcon, label: 'patient.booklet.review', cls: 'text-review bg-review-soft' },
    image: { icon: ImageIcon, label: 'patient.booklet.image', cls: 'text-muted-foreground bg-muted' },
    missing: { icon: BookOpenIcon, label: 'patient.booklet.missing', cls: 'text-muted-foreground bg-transparent' },
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">{t('patient.booklet.hint')}</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {PAGE_TYPES.map((pt, i) => {
          const hit = latestPage(pt)
          const st: BookletState = !hit
            ? 'missing'
            : !Object.keys(hit.page.fields).length
              ? 'image'
              : openFields(hit.page).length || !hit.record.patientId
                ? 'review'
                : 'done'
          const s = STYLE[st]
          const body = (
            <>
              <div className="relative">
                {hit?.page.imageUrl ? (
                  <PageImage page={hit.page} thumb />
                ) : (
                  <div className="flex aspect-[3/4] items-center justify-center rounded-lg border-2 border-dashed text-3xl font-bold text-muted-foreground/40">{i + 1}</div>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-sm leading-tight font-semibold">
                  {i + 1}. {t(`page.${pt}`)}
                </span>
                <span className={cn('inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold', s.cls)}>
                  <s.icon className="size-3.5" /> {t(s.label)}
                </span>
              </div>
            </>
          )
          return hit ? (
            <Link key={pt} to={`/records/${hit.record.id}/review?page=${hit.index}`} className="flex flex-col gap-2 rounded-xl border bg-card p-2.5 hover:border-primary">
              {body}
            </Link>
          ) : (
            <div key={pt} className="flex flex-col gap-2 rounded-xl border border-dashed p-2.5 opacity-80">
              {body}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ---------------- Images ---------------- */

function Images({ records, t }: Ctx) {
  const pages = records.flatMap((r) => r.pages.map((p) => ({ p, r })).filter(({ p }) => p.imageUrl))
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">{t('image.maskedHint')}</p>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        {pages.map(({ p, r }) => (
          <figure key={p.id} className="flex flex-col gap-2">
            <PageImage page={p} />
            <figcaption className="text-sm">
              <b>{t.page(p)}</b> · {t.date(p.capturedAt)} · {r.midwifeId}
            </figcaption>
          </figure>
        ))}
      </div>
    </div>
  )
}
