import {
  CalendarCheck2Icon,
  CalendarClockIcon,
  CalendarIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleAlertIcon,
  CircleCheckBigIcon,
  ImageIcon,
  MessageCircleIcon,
  PhoneCallIcon,
  SearchIcon,
  type LucideIcon,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BUCKETS, FOLLOW_UP, type Bucket, type FollowUp } from '@/contract/followup'
import type { Patient, RegistryRecord } from '@/contract/types'
import { PageHeader } from '@/components/AppShell'
import { PatientCode } from '@/components/PatientCode'
import { RecordStatusNote } from '@/components/RecordRow'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { latestFields, useAppState, usePatients, useRecords } from '@/services'
import type { AppState } from '@/services/api'
import { followUpFor } from '@/services/followup'
import { codeDistance, normalizeCode } from '@/services/linking'
import { useT, type T, type TKey } from '@/i18n'
import { cn } from '@/lib/utils'

/** Look of each group. Timing only: these colors say "when", never "how sick". */
const BUCKET_STYLE: Record<Bucket, { icon: LucideIcon; tone: string; soft: string; border: string }> = {
  LATE: { icon: CircleAlertIcon, tone: 'text-review', soft: 'bg-review-soft', border: 'border-l-review' },
  SOON: { icon: CalendarClockIcon, tone: 'text-info', soft: 'bg-info-soft', border: 'border-l-info' },
  LOST: { icon: PhoneCallIcon, tone: 'text-illegible', soft: 'bg-illegible-soft', border: 'border-l-illegible' },
  LATER: { icon: CalendarIcon, tone: 'text-muted-foreground', soft: 'bg-muted', border: 'border-l-border' },
  DONE: { icon: CalendarCheck2Icon, tone: 'text-known', soft: 'bg-known-soft', border: 'border-l-known' },
}

interface Row {
  patient: Patient
  follow: FollowUp
  /** Photos with this code not yet processed or not yet attached to her file. */
  waiting: RegistryRecord[]
}

/** Most urgent first: late (most late first), this week (soonest first), to recontact, later, done. */
function sortRows(rows: Row[]): Row[] {
  const rank = (r: Row) => BUCKETS.indexOf(r.follow.bucket)
  return [...rows].sort((a, b) => rank(a) - rank(b) || b.follow.daysLate - a.follow.daysLate)
}

function urgency(t: T, f: FollowUp): string {
  const n = Math.abs(f.daysLate)
  if (f.bucket === 'DONE') return t('urgency.done')
  if (f.bucket === 'LATE' || f.bucket === 'LOST') return t('urgency.late', { n })
  if (n === 0) return t('urgency.today')
  return t('urgency.in', { n })
}

function why(t: T, f: FollowUp): string {
  if (!f.anchor) return ''
  if (f.step === 'ANTENATAL') return t('why.antenatal', { n: FOLLOW_UP.antenatalEveryDays, date: t.date(f.anchor.date) })
  const s = FOLLOW_UP.postpartum.find((x) => x.step === f.step)
  return s ? t('why.postpartum', { n: s.dueDaysAfterDelivery, date: t.date(f.anchor.date) }) : t('why.done', { date: t.date(f.anchor.date) })
}

function PatientFollowRow({ row, rank, state }: { row: Row; rank: number; state: AppState }) {
  const t = useT()
  const { patient, follow, waiting } = row
  const s = BUCKET_STYLE[follow.bucket]
  const f = latestFields(state, patient)
  const age = f['identification_antecedents.age']?.value
  const g = f['identification_antecedents.gestation']?.value
  const p = f['identification_antecedents.parite']?.value

  return (
    <Link
      to={`/patients/${patient.id}`}
      className={cn('group flex flex-col gap-3 rounded-xl border border-l-4 bg-card p-4 transition-shadow hover:shadow-md sm:flex-row sm:items-center', s.border)}
    >
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-bold text-muted-foreground">{rank}</span>
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <PatientCode code={patient.code} size="lg" />
            <span className="text-sm text-muted-foreground">
              {[typeof age === 'number' ? t('patient.age', { n: age }) : null, g != null ? t('patient.gp', { g: String(g), p: p == null ? '?' : String(p) }) : null]
                .filter(Boolean)
                .join(' · ')}
            </span>
          </div>
          <span className="font-semibold">{t(`next.${follow.step}`)}</span>
          <Tooltip>
            <TooltipTrigger render={<span className="w-fit text-sm text-muted-foreground underline decoration-dotted underline-offset-4" />}>
              {follow.due ? t('next.due', { date: t.date(follow.due) }) : why(t, follow)}
            </TooltipTrigger>
            <TooltipContent className="max-w-72">{why(t, follow)}</TooltipContent>
          </Tooltip>
          {waiting.length > 0 && (
            <span className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs font-medium">
              <ImageIcon className="size-3.5" /> {t('today.photoWaiting', { n: waiting.length })}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <span className={cn('inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-bold whitespace-nowrap', s.tone, s.soft)}>
          <s.icon className="size-4" />
          {urgency(t, follow)}
        </span>
        <ChevronRightIcon className="size-5 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
      </div>
    </Link>
  )
}

function CodeSearch() {
  const t = useT()
  const navigate = useNavigate()
  const patients = usePatients()
  const [q, setQ] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const exact = patients.find((p) => normalizeCode(p.code) === normalizeCode(q))
  const near = submitted && !exact && q ? patients.filter((p) => codeDistance(p.code, q) <= 2).slice(0, 4) : []
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        setSubmitted(true)
        if (exact) navigate(`/patients/${exact.id}`)
      }}
    >
      <div className="relative">
        <SearchIcon className="absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => {
            setQ(e.target.value.toUpperCase())
            setSubmitted(false)
          }}
          aria-label={t('today.search.label')}
          placeholder={t('today.search.placeholder')}
          autoComplete="off"
          className="font-code h-12 pl-11 text-lg font-bold uppercase placeholder:font-sans placeholder:text-sm placeholder:font-normal placeholder:normal-case"
        />
      </div>
      {submitted && !exact && q && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">{t('today.search.none', { code: q })}</span>
          {near.map((p) => (
            <Link key={p.id} to={`/patients/${p.id}`} className="rounded-md border bg-card px-2 py-1 hover:border-primary">
              <PatientCode code={p.code} size="sm" />
            </Link>
          ))}
        </div>
      )}
    </form>
  )
}

/** Right column: what is moving in the pipeline, read-only. */
function Activity({ records }: { records: RegistryRecord[] }) {
  const t = useT()
  const state = useAppState((s) => s)
  const pending = records.filter((r) => r.state !== 'SYNCED')
  const recent = records
    .filter((r) => r.state === 'SYNCED')
    .sort((a, b) => (b.history.at(-1)?.at ?? '').localeCompare(a.history.at(-1)?.at ?? ''))
    .slice(0, 5)
  const code = (r: RegistryRecord) => (r.patientId ? state.patients[r.patientId]?.code : undefined) ?? r.patientCode
  return (
    <div className="flex flex-col gap-4">
      <section className="flex flex-col gap-2 rounded-2xl border bg-card p-4">
        <h2 className="font-bold">{t('today.inProgress')}</h2>
        <p className="text-sm text-muted-foreground">{t('today.inProgressHint')}</p>
        {pending.length === 0 && <p className="text-sm text-known">{t('today.nothingPending')}</p>}
        {pending.map((r) => (
          <Link key={r.id} to={`/records/${r.id}`} className="flex flex-col gap-1.5 rounded-lg bg-muted/60 p-2.5 hover:bg-muted">
            <span className="flex items-center justify-between gap-2">
              <PatientCode code={code(r)} size="sm" />
              <span className="text-xs text-muted-foreground">{t.relative(r.createdAt)}</span>
            </span>
            <span className="truncate text-xs">{r.pages.map((p) => t(`page.${p.pageType}`)).join(' + ')}</span>
            <RecordStatusNote record={r} />
          </Link>
        ))}
      </section>
      {recent.length > 0 && (
      <section className="flex flex-col gap-2 rounded-2xl border bg-card p-4">
        <h2 className="font-bold">{t('today.recentSynced')}</h2>
        {recent.map((r) => (
          <Link key={r.id} to={`/records/${r.id}`} className="flex items-center justify-between gap-2 rounded-lg px-1 py-1.5 text-sm hover:bg-muted/60">
            <PatientCode code={code(r)} size="sm" />
            <span className="truncate text-muted-foreground">{t(`page.${r.pages[0]?.pageType ?? 'identification_antecedents'}`)}</span>
          </Link>
        ))}
      </section>
      )}
    </div>
  )
}

export function HomeScreen() {
  const t = useT()
  const state = useAppState((s) => s)
  const patients = usePatients()
  const records = useRecords()
  const [filter, setFilter] = useState<Bucket | null>(null)
  const [showDone, setShowDone] = useState(false)

  const rows = useMemo(
    () =>
      sortRows(
        patients.map((patient) => ({
          patient,
          follow: followUpFor(state, patient),
          waiting: records.filter((r) => !r.patientId && normalizeCode(r.patientCode) === normalizeCode(patient.code)),
        })),
      ),
    [patients, records, state],
  )
  const count = (b: Bucket) => rows.filter((r) => r.follow.bucket === b).length
  const visible = rows.filter((r) => (filter ? r.follow.bucket === filter : r.follow.bucket !== 'DONE' || showDone))
  const today = new Date().toLocaleDateString(t.lang === 'fr' ? 'fr-FR' : 'en-GB', { weekday: 'long', day: 'numeric', month: 'long' })

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title={t('nav.today')} subtitle={<span className="first-letter:uppercase">{today} · {t('today.subtitle')}</span>} />

      <div className="flex flex-col gap-6 px-4 pb-10 sm:px-6 lg:px-8">
        {/* Counters double as filters */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {BUCKETS.map((b) => {
            const s = BUCKET_STYLE[b]
            const active = filter === b
            return (
              <button
                key={b}
                type="button"
                aria-pressed={active}
                onClick={() => setFilter(active ? null : b)}
                className={cn(
                  'flex items-center gap-3 rounded-2xl border-2 bg-card p-3 text-left transition-colors sm:flex-col sm:items-start sm:gap-1 sm:p-4',
                  active ? 'border-primary' : 'border-transparent ring-1 ring-border hover:ring-primary/40',
                )}
              >
                <span className={cn('flex size-9 items-center justify-center rounded-xl', s.soft, s.tone)}>
                  <s.icon className="size-5" />
                </span>
                <span className="flex flex-col sm:gap-1">
                  <span className="text-2xl font-bold tabular-nums sm:text-3xl">{count(b)}</span>
                  <span className="text-sm leading-tight font-medium">{t(`bucket.${b}`)}</span>
                </span>
              </button>
            )
          })}
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <section className="flex min-w-0 flex-col gap-2">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <h2 className="text-lg font-bold">{filter ? t(`bucket.${filter}`) : t('today.priority')}</h2>
              <span className="text-sm text-muted-foreground">{t('today.priorityHint')}</span>
            </div>
            {patients.length === 0 ? (
              <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-6 py-12 text-center">
                <span className="flex size-12 items-center justify-center rounded-2xl bg-secondary text-primary">
                  <MessageCircleIcon className="size-6" />
                </span>
                <p className="text-lg font-bold">{t('today.empty.title')}</p>
                <p className="max-w-md text-muted-foreground">{t('today.empty.hint')}</p>
              </div>
            ) : (
              visible.length === 0 && (
                <div className="flex items-center gap-3 rounded-2xl bg-known-soft p-5">
                  <CircleCheckBigIcon className="size-7 text-known" />
                  <span className="font-semibold">{t('today.nobody')}</span>
                </div>
              )
            )}
            {visible.map((row, i) => {
              const header = !filter && (i === 0 || visible[i - 1].follow.bucket !== row.follow.bucket)
              return (
                <div key={row.patient.id} className="flex flex-col gap-2">
                  {header && (
                    <h3 className={cn('mt-3 flex flex-wrap items-baseline gap-x-2 text-sm font-bold tracking-wide uppercase', BUCKET_STYLE[row.follow.bucket].tone)}>
                      {t(`bucket.${row.follow.bucket}`)}
                      <span className="font-normal tracking-normal text-muted-foreground normal-case">{t(`bucketHint.${row.follow.bucket}` as TKey)}</span>
                    </h3>
                  )}
                  <PatientFollowRow row={row} rank={i + 1} state={state} />
                </div>
              )
            })}
            {!filter && count('DONE') > 0 && (
              <button
                type="button"
                onClick={() => setShowDone((v) => !v)}
                className="mt-2 flex items-center gap-2 self-start rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
              >
                <ChevronDownIcon className={cn('size-4 transition-transform', showDone && 'rotate-180')} />
                {t(showDone ? 'today.hideDone' : 'today.showDone', { n: count('DONE') })}
              </button>
            )}
          </section>

          <aside className="flex flex-col gap-4">
            <div className="rounded-2xl border bg-card p-4">
              <CodeSearch />
            </div>
            <Activity records={records} />
          </aside>
        </div>
      </div>
    </div>
  )
}
