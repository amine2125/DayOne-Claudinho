import { CalendarClockIcon, CircleCheckIcon, ClockIcon, FlaskConicalIcon, ScanSearchIcon, TableIcon, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { MeasureCode, Patient, SeriesValue } from '@/contract/types'
import type { AppState } from '@/services/api'
import { appointmentsOf, nextWrittenAppointment, patientTrends, pointsOf, type Fact, type TrendVisit } from '@/services/trends'
import { fmt } from '@/components/charts/kit'
import { TrendChart, type TrendPoint, type TrendSeries } from '@/components/charts/TrendChart'
import type { T, TKey } from '@/i18n'
import { alertText } from '@/i18n/alerts'
import { cn } from '@/lib/utils'

const pageHref = (v: { recordId: string; pageIndex: number }) => `/records/${v.recordId}/review?page=${v.pageIndex}`
const review = (e?: { status: string }) => e?.status === 'NEEDS_REVIEW' || e?.status === 'ILLEGIBLE'

function Card({ title, icon: Icon, hint, children, className }: { title: string; icon?: LucideIcon; hint?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('flex min-w-0 flex-col gap-3 rounded-2xl border bg-card p-4 sm:p-5', className)}>
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

/** Value of a measure in words, with its unit. */
function show(t: T, measure: MeasureCode | 'ga', e: SeriesValue | undefined): string {
  if (!e) return '—'
  const v = e.value
  if (Array.isArray(v)) return `${v[0]}/${v[1]}`
  if (typeof v === 'boolean') return v ? '✓' : '—'
  if (typeof v === 'string') return v
  const unit: Partial<Record<string, string>> = { weight: 'kg', fundalHeight: 'cm', fhr: '', temperature: '°C', pulse: '', hemoglobin: 'g/dL', headCirc: 'cm', length: 'cm' }
  return `${fmt(v, t.lang)}${unit[measure] ? ` ${unit[measure]}` : ''}`
}

function note(t: T, e: SeriesValue): string | undefined {
  if (e.alerts?.length) return alertText(t, e.alerts[0])
  if (review(e)) return t('trends.toCheck')
  if (e.origin !== 'AI') return t('trends.verified')
  return undefined
}

function gaLabel(t: T, v: TrendVisit): string {
  const ga = v.x == null ? '' : v.xComputed ? t('trends.computedGa', { n: Math.round(v.x) }) : `${v.x} ${t('trends.col.ga')}`
  return [ga, v.date ? t.date(v.date) : ''].filter(Boolean).join(' · ')
}

/* ---------------- Évolution ---------------- */

export function Trends({ state, patient, t }: { state: AppState; patient: Patient; t: T }) {
  const tr = patientTrends(state, patient)
  const hasAny = tr.antenatal.length || tr.mother.length || tr.newborn.length || tr.delivery.birthWeight
  if (!hasAny) return <div className="rounded-2xl border-2 border-dashed p-10 text-center text-muted-foreground">{t('trends.empty')}</div>

  const viz1: TrendSeries = { name: t('trends.systolic'), color: 'var(--viz-1)' }
  const viz2: TrendSeries = { name: t('trends.diastolic'), color: 'var(--viz-2)' }
  const chartPoints = (measure: MeasureCode, valueLabel: (y: number, y2?: number) => string): TrendPoint[] =>
    pointsOf(tr.antenatal, measure).map(({ visit, entry, x, y, y2 }) => ({
      id: `${visit.recordId}.${visit.column}.${visit.date}`,
      x,
      y,
      y2,
      review: review(entry),
      verified: entry.origin !== 'AI',
      xLabel: gaLabel(t, visit),
      valueLabel: valueLabel(y, y2),
      note: note(t, entry),
      href: pageHref(visit),
    }))
  const weights = pointsOf(tr.antenatal, 'weight')
  const change = weights.length >= 2 ? weights[weights.length - 1].y - weights[0].y : undefined
  const last = [...tr.antenatal].reverse().find((v) => v.x != null)
  const facts: [TKey, Fact | undefined, 'date' | 'cm'][] = [
    ['trends.lmp', tr.facts.lmp, 'date'],
    ['trends.edd', tr.facts.edd, 'date'],
    ['trends.termDate', tr.facts.termDate, 'date'],
    ['trends.height', tr.facts.height, 'cm'],
  ]
  const gaTick = (x: number) => `${Math.round(x)}`

  return (
    <div className="flex flex-col gap-5">
      {tr.antenatal.length > 0 && (
        <>
          <Card title={t('trends.pregnancy')}>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
              {facts.map(([label, f, kind]) => (
                <FactTile key={label} label={t(label)} value={f ? (kind === 'date' ? t.date(String(f.value)) : `${f.value} cm`) : '—'} review={review(f)} href={f && pageHref(f)} />
              ))}
              <FactTile label={t('trends.visitsRead')} value={String(tr.antenatal.length)} />
              <FactTile label={t('trends.lastVisit')} value={last ? gaLabel(t, last) : '—'} />
              <FactTile label={t('trends.weightChange')} value={change == null ? '—' : `${change > 0 ? '+' : ''}${fmt(change, t.lang)} kg`} />
            </dl>
          </Card>

          <div className="grid gap-5 md:grid-cols-2">
            <ChartCard title={t('trends.weight')} unit="kg" t={t} points={chartPoints('weight', (y) => `${fmt(y, t.lang)} kg`)} series={[{ name: t('trends.weight'), color: 'var(--viz-1)' }]} formatX={gaTick} />
            <ChartCard title={t('trends.bp')} unit="mmHg" t={t} points={chartPoints('bp', (y, y2) => `${y}/${y2} mmHg`)} series={[viz1, viz2]} formatX={gaTick} />
            <ChartCard title={t('trends.fundalHeight')} unit="cm" t={t} points={chartPoints('fundalHeight', (y) => `${fmt(y, t.lang)} cm`)} series={[{ name: t('trends.fundalHeight'), color: 'var(--viz-1)' }]} formatX={gaTick} />
            <ChartCard title={t('trends.fhr')} unit="/min" t={t} points={chartPoints('fhr', (y) => `${y} /min`)} series={[{ name: t('trends.fhr'), color: 'var(--viz-1)' }]} formatX={gaTick} />
          </div>

          <VisitsTable t={t} visits={tr.antenatal} />
          <Labs t={t} visits={tr.antenatal} />
        </>
      )}

      {(tr.mother.length > 0 || tr.newborn.length > 0 || tr.delivery.birthWeight) && <Postpartum t={t} tr={tr} />}

      <footer className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <svg width="12" height="12" aria-hidden>
            <circle cx="6" cy="6" r="4.5" fill="var(--viz-1)" />
          </svg>
          {t('trends.legend.read')}
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="12" height="12" aria-hidden>
            <circle cx="6" cy="6" r="4" fill="var(--card)" stroke="var(--st-review)" strokeWidth="2" />
          </svg>
          {t('trends.legend.review')}
        </span>
        <span className="basis-full">{t('trends.note')}</span>
      </footer>
    </div>
  )
}

function FactTile({ label, value, review: toCheck, href }: { label: string; value: string; review?: boolean; href?: string }) {
  const body = (
    <>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('text-base leading-tight font-bold', value === '—' && 'text-muted-foreground', toCheck && 'text-review')}>{value}</dd>
    </>
  )
  return href ? (
    <Link to={href} className="flex flex-col gap-1 rounded-xl bg-muted/70 p-3 hover:ring-2 hover:ring-primary/30">
      {body}
    </Link>
  ) : (
    <div className="flex flex-col gap-1 rounded-xl bg-muted/70 p-3">{body}</div>
  )
}

function ChartCard({
  title,
  unit,
  points,
  series,
  formatX,
  t,
}: {
  title: string
  unit: string
  points: TrendPoint[]
  series: [TrendSeries] | [TrendSeries, TrendSeries]
  formatX: (x: number) => string
  t: T
}) {
  const last = points.at(-1)
  return (
    <section className="flex min-w-0 flex-col gap-2 rounded-2xl border bg-card p-4 sm:p-5">
      <header className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="font-bold">
          {title} <span className="text-sm font-normal text-muted-foreground">({unit})</span>
        </h3>
        {last && (
          <span className="text-sm text-muted-foreground">
            <b className="text-base text-foreground">{last.valueLabel}</b> · {last.xLabel}
          </span>
        )}
      </header>
      {series.length === 2 && points.length > 0 && (
        <ul className="flex gap-4 text-xs text-muted-foreground">
          {series.map((s) => (
            <li key={s.name} className="flex items-center gap-1.5">
              <svg width="14" height="8" aria-hidden>
                <line x1="0" x2="14" y1="4" y2="4" stroke={s.color} strokeWidth="2" strokeLinecap="round" />
              </svg>
              {s.name}
            </li>
          ))}
        </ul>
      )}
      {points.length ? (
        <TrendChart points={points} series={series} formatX={formatX} label={`${title} (${unit})`} />
      ) : (
        <p className="py-10 text-center text-sm text-muted-foreground">{t('trends.noValue')}</p>
      )}
      {points.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t('trends.points', { n: points.length })} · {t('trends.col.ga')}
        </p>
      )}
    </section>
  )
}

/** Table view of the charts: every value reachable without hovering, as on the paper. */
function VisitsTable({ t, visits }: { t: T; visits: TrendVisit[] }) {
  const cols: MeasureCode[] = ['weight', 'bp', 'fundalHeight', 'fhr', 'oedema', 'albuminuria', 'glycosuria']
  return (
    <Card title={t('trends.table')} icon={TableIcon} hint={t('trends.tableHint')}>
      <div className="-mx-1 overflow-x-auto">
        <table className="w-full min-w-[640px] border-separate border-spacing-x-1 text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 font-medium">{t('trends.col.date')}</th>
              <th className="py-1 font-medium">{t('trends.col.ga')}</th>
              {cols.map((c) => (
                <th key={c} className="py-1 font-medium">
                  {t(`trends.col.${c}` as TKey)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visits.map((v) => (
              <tr key={`${v.recordId}.${v.column}.${v.date}`} className="align-top">
                <td className="py-1.5 whitespace-nowrap">
                  <Link to={pageHref(v)} className="font-semibold text-primary underline-offset-2 hover:underline">
                    {v.date ? t.date(v.date) : `#${v.column}`}
                  </Link>
                </td>
                <td className="py-1.5 tabular-nums">{v.gaWeeks ?? '—'}</td>
                {cols.map((c) => {
                  const e = v.values[c]
                  return (
                    <td key={c} className={cn('py-1.5 tabular-nums', !e && 'text-muted-foreground', review(e) && 'rounded bg-review-soft px-1 text-review')}>
                      <span className="inline-flex items-center gap-1" title={e ? note(t, e) : undefined}>
                        {e?.alerts?.length ? <ScanSearchIcon className="size-3.5" aria-label={t('alert.check')} /> : null}
                        {show(t, c, e)}
                      </span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function Labs({ t, visits }: { t: T; visits: TrendVisit[] }) {
  const tests: MeasureCode[] = ['hiv', 'syphilis', 'hbs', 'hcv', 'toxo', 'rubella']
  const rows = tests.flatMap((m) => visits.filter((v) => v.values[m]).map((v) => ({ m, v, e: v.values[m]! })))
  const hb = visits.filter((v) => v.values.hemoglobin)
  return (
    <Card title={t('trends.labs')} icon={FlaskConicalIcon} hint={t('trends.labsHint')}>
      {rows.length === 0 && hb.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('trends.labsNone')}</p>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map(({ m, v, e }) => (
            <LabRow key={`${m}${v.column}`} label={t(`trends.test.${m}` as TKey)} value={show(t, m, e)} date={v.date && t.date(v.date)} href={pageHref(v)} toCheck={review(e)} />
          ))}
          {hb.map((v) => (
            <LabRow key={`hb${v.column}`} label={t('trends.hemoglobin')} value={show(t, 'hemoglobin', v.values.hemoglobin)} date={v.date && t.date(v.date)} href={pageHref(v)} toCheck={review(v.values.hemoglobin)} />
          ))}
        </ul>
      )}
    </Card>
  )
}

function LabRow({ label, value, date, href, toCheck }: { label: string; value: string; date?: string; href: string; toCheck: boolean }) {
  return (
    <li>
      <Link to={href} className={cn('flex items-baseline justify-between gap-3 rounded-lg border px-3 py-2 hover:border-primary', toCheck && 'border-review/50 bg-review-soft')}>
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="text-right">
          <b className={cn(toCheck && 'text-review')}>{value}</b>
          {date && <span className="block text-xs text-muted-foreground">{date}</span>}
        </span>
      </Link>
    </li>
  )
}

/* ---------------- après l'accouchement ---------------- */

function Postpartum({ t, tr }: { t: T; tr: ReturnType<typeof patientTrends> }) {
  const birth = tr.delivery.birthWeight
  const points: TrendPoint[] = [
    ...(birth && typeof birth.value === 'number'
      ? [{ id: 'birth', x: 0, y: birth.value, review: review(birth), xLabel: t('trends.birth'), valueLabel: `${birth.value} g`, note: note(t, birth), href: pageHref(birth) }]
      : []),
    ...tr.newborn.flatMap((v) => {
      const e = v.values.weight
      if (!e || typeof e.value !== 'number' || v.x == null) return []
      return [{ id: `${v.recordId}.${v.pageIndex}`, x: v.x, y: e.value, review: review(e), xLabel: [t('trends.ageDays', { n: v.x }), v.date && t.date(v.date)].filter(Boolean).join(' · '), valueLabel: `${e.value} g`, note: note(t, e), href: pageHref(v) }]
    }),
  ]
  const motherCols: MeasureCode[] = ['temperature', 'bp', 'pulse', 'weight']
  const babyCols: MeasureCode[] = ['weight', 'length', 'headCirc', 'temperature']
  return (
    <Card title={t('trends.postpartum')}>
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-2">
          <h3 className="font-bold">{t('trends.newbornWeight')} <span className="text-sm font-normal text-muted-foreground">(g)</span></h3>
          {points.length ? (
            <TrendChart points={points} series={[{ name: t('trends.newbornWeight'), color: 'var(--viz-1)' }]} formatX={(x) => t('trends.ageDays', { n: Math.round(x) })} label={t('trends.newbornWeight')} height={170} />
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">{t('trends.noValue')}</p>
          )}
          <MiniTable t={t} title={t('trends.newborn')} visits={tr.newborn} cols={babyCols} first={(v) => (v.x != null ? t('trends.ageDays', { n: v.x }) : '—')} weightUnit="g" />
        </div>
        <MiniTable t={t} title={t('trends.mother')} visits={tr.mother} cols={motherCols} first={(v) => (v.date ? t.date(v.date) : '—')} weightUnit="kg" />
      </div>
    </Card>
  )
}

function MiniTable({ t, title, visits, cols, first, weightUnit }: { t: T; title: string; visits: TrendVisit[]; cols: MeasureCode[]; first: (v: TrendVisit) => string; weightUnit: 'g' | 'kg' }) {
  if (!visits.length) return null
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <h3 className="font-bold">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-2 font-medium">{weightUnit === 'g' ? t('trends.col.age') : t('trends.col.date')}</th>
              {cols.map((c) => (
                <th key={c} className="py-1 pr-2 font-medium">
                  {t(`trends.col.${c}` as TKey)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visits.map((v) => (
              <tr key={`${v.recordId}.${v.pageIndex}`}>
                <td className="py-1.5 pr-2 whitespace-nowrap">
                  <Link to={pageHref(v)} className="font-semibold text-primary hover:underline">
                    {first(v)}
                  </Link>
                </td>
                {cols.map((c) => {
                  const e = v.values[c]
                  const text = c === 'weight' && e && typeof e.value === 'number' ? (weightUnit === 'g' ? `${e.value} g` : `${fmt(e.value, t.lang)} kg`) : show(t, c, e)
                  return (
                    <td key={c} className={cn('py-1.5 pr-2 tabular-nums', !e && 'text-muted-foreground', review(e) && 'text-review')} title={e ? note(t, e) : undefined}>
                      {text}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ---------------- Rendez-vous ---------------- */

const DAY = 864e5

export function Appointments({ state, patient, t }: { state: AppState; patient: Patient; t: T }) {
  const tr = patientTrends(state, patient)
  const rows = appointmentsOf(tr)
  const next = nextWrittenAppointment(tr)
  const inDays = next ? Math.round((new Date(`${next.due}T12:00:00`).getTime() - Date.now()) / DAY) : 0
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <Card title={t('appt.next')} icon={CalendarClockIcon}>
        {next ? (
          <Link to={pageHref(next)} className="flex flex-wrap items-baseline gap-x-3 rounded-xl bg-muted/70 p-4 hover:ring-2 hover:ring-primary/30">
            <span className="text-2xl font-bold">{t.date(next.due)}</span>
            <span className={cn('font-semibold', inDays < 0 ? 'text-review' : 'text-muted-foreground')}>
              {inDays === 0 ? t('appt.today') : inDays > 0 ? t('appt.in', { n: inDays }) : t('appt.ago', { n: -inDays })}
            </span>
            <span className="basis-full text-sm text-muted-foreground">
              {t(`appt.source.${next.source}` as TKey)} · {t('appt.givenOn', { date: t.date(next.givenOn) })}
            </span>
          </Link>
        ) : (
          <p className="text-sm text-muted-foreground">{t('appt.nextNone')}</p>
        )}
      </Card>
      <Card title={t('appt.list')} icon={ClockIcon} hint={t('appt.listHint')}>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('appt.none')}</p>
        ) : (
          <ol className="flex flex-col divide-y">
            {rows.map((r) => {
              const late = r.delay != null && r.delay > 3
              return (
                <li key={`${r.givenOn}${r.due}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
                  <Link to={pageHref(r)} className="min-w-40 font-semibold text-primary hover:underline">
                    {t('appt.due', { date: t.date(r.due) })}
                  </Link>
                  <span className="text-sm text-muted-foreground">{t('appt.givenOn', { date: t.date(r.givenOn) })}</span>
                  <span className={cn('ml-auto inline-flex items-center gap-1.5 text-sm font-semibold', late ? 'text-review' : r.cameOn ? 'text-known' : 'text-muted-foreground')}>
                    {r.cameOn ? (
                      <>
                        {!late && <CircleCheckIcon className="size-4" />}
                        {t('appt.came', { date: t.date(r.cameOn) })} ·{' '}
                        {late ? t('appt.late', { n: r.delay! }) : r.delay! < -3 ? t('appt.early', { n: -r.delay! }) : t('appt.onTime')}
                      </>
                    ) : (
                      t('appt.notYet')
                    )}
                  </span>
                </li>
              )
            })}
          </ol>
        )}
      </Card>
    </div>
  )
}
