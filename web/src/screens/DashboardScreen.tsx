import { ActivityIcon, BabyIcon, ClipboardCheckIcon, LoaderIcon, MicroscopeIcon, ShieldCheckIcon, StethoscopeIcon, ThermometerIcon, type LucideIcon } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { PageHeader } from '@/components/AppShell'
import { ColumnChart, type Column } from '@/components/charts/ColumnChart'
import { fmt } from '@/components/charts/kit'
import { StackedBars, type SegmentStyle } from '@/components/charts/StackedBars'
import { Button } from '@/components/ui/button'
import { useRecords } from '@/services'
import { API_URL } from '@/services/httpApi'
import { useT, type T, type TKey } from '@/i18n'
import { cn } from '@/lib/utils'

/** GET /api/aggregates (api/aggregates.py). Counts only; null = fewer than k women, hidden. */
type Count = number | null
interface Histogram {
  n: number
  bins: { from: number | null; to: number | null; count: Count }[]
}
interface Aggregates {
  source: Source
  k: number
  women: Count
  suppressed?: boolean
  panels: {
    bp?: { systolic: Histogram; diastolic: Histogram } | null
    temperature?: Histogram | null
    hemoglobin?: Histogram | null
    tests?: ({ test: string } & Record<'pos' | 'neg' | 'notRecorded' | 'noPage', Count>)[]
    anc?: { firstVisit: Record<'t1' | 't2' | 't3', Count>; visitCounts: Record<string, Count> | null }
    delivery?: {
      n: number
      mode: Record<'vaginal' | 'cesarean', Count>
      place: Record<string, Count>
      birthWeight: Histogram
      gaAtBirth: Histogram
      preterm: Record<'preterm' | 'term', Count>
    }
    completeness?: { measure: string; recorded: Count; total: number }[]
  }
}
type Source = 'registry' | 'synthetic'

/**
 * Anonymised aggregates for the health system: distributions and counts, computed by the API.
 * Small cells are hidden server-side; nothing here can point to one woman. No threshold, no risk.
 */
export function DashboardScreen() {
  const t = useT()
  const records = useRecords()
  const [source, setSource] = useState<Source>('registry')
  const [data, setData] = useState<Aggregates>()
  const [failed, setFailed] = useState(false)
  const syncedCount = records.filter((r) => r.state === 'SYNCED').length

  useEffect(() => {
    let live = true
    fetch(`${API_URL}/api/aggregates?source=${source}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Aggregates) => live && (setData(d), setFailed(false)))
      .catch(() => live && setFailed(true))
    return () => {
      live = false
    }
  }, [source, syncedCount])

  const fields = records.flatMap((r) => r.pages.flatMap((p) => Object.values(p.fields)))
  const written = fields.filter((f) => f.status !== 'NOT_PROVIDED' && f.status !== 'NOT_APPLICABLE')
  const quality = [
    { label: 'dash.pages' as TKey, value: String(records.reduce((n, r) => n + r.pages.filter((p) => Object.keys(p.fields).length).length, 0)) },
    {
      label: 'dash.autoRead' as TKey,
      value: written.length ? `${Math.round((written.filter((f) => f.origin === 'AI' && f.status === 'KNOWN').length / written.length) * 100)} %` : '—',
    },
    { label: 'dash.humanChecked' as TKey, value: String(fields.filter((f) => f.origin !== 'AI').length) },
  ]
  const current = data?.source === source ? data : undefined
  const k = current?.k ?? 5
  const p = current?.panels

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title={t('dash.title')} subtitle={t('dash.subtitle')} />
      <div className="flex flex-col gap-6 px-4 pb-10 sm:px-6 lg:px-8">
        {/* Filters: one row, above everything they scope. */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-sm font-semibold text-muted-foreground">{t('dash.source')}</span>
          {(['registry', 'synthetic'] as const).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={s === source}
              onClick={() => setSource(s)}
              className={cn(
                'h-10 rounded-lg border-2 px-3 text-sm font-medium',
                s === source ? 'border-primary bg-secondary' : 'border-border bg-card hover:border-primary/40',
              )}
            >
              {t(`dash.source.${s}`)}
            </button>
          ))}
          {current && !current.suppressed && (
            <span className="ml-auto text-sm text-muted-foreground">
              {t('dash.women')} : <b className="text-foreground">{current.women ?? t('dash.lessThan', { k })}</b>
            </span>
          )}
        </div>

        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">{t('dash.quality')}</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            {quality.map((s) => (
              <div key={s.label} className="rounded-2xl border bg-card p-5">
                <div className="text-3xl font-bold">{s.value}</div>
                <div className="text-sm text-muted-foreground">{t(s.label)}</div>
              </div>
            ))}
          </div>
        </section>

        {failed && !current && <p className="rounded-2xl border p-6 text-muted-foreground">{t('dash.error')}</p>}
        {!failed && !current && (
          <p className="flex items-center gap-2 text-muted-foreground">
            <LoaderIcon className="size-4 animate-spin" /> {t('dash.loading')}
          </p>
        )}
        {current?.suppressed && (
          <div className="flex flex-col items-start gap-3 rounded-2xl border-2 border-dashed p-6">
            <p className="flex items-start gap-2 text-muted-foreground">
              <ShieldCheckIcon className="mt-0.5 size-5 shrink-0 text-primary" /> {t('dash.suppressed', { k })}
            </p>
            <Button variant="outline" onClick={() => setSource('synthetic')}>
              {t('dash.source.synthetic')}
            </Button>
          </div>
        )}

        {p && !current?.suppressed && (
          <div className={cn('grid gap-5 lg:grid-cols-2', failed && 'opacity-60')}>
            {p.bp && (
              <Panel title={t('dash.bp')} hint={t('dash.bpHint')} icon={ActivityIcon} className="lg:col-span-2">
                <div className="grid gap-5 md:grid-cols-2">
                  <Hist t={t} k={k} title={`${t('trends.systolic')} (mmHg)`} h={p.bp.systolic} />
                  <Hist t={t} k={k} title={`${t('trends.diastolic')} (mmHg)`} h={p.bp.diastolic} />
                </div>
              </Panel>
            )}

            {p.tests && p.tests.length > 0 && (
              <Panel title={t('dash.tests')} hint={t('dash.testsHint')} icon={MicroscopeIcon} className="lg:col-span-2">
                <Tests t={t} k={k} tests={p.tests} />
              </Panel>
            )}

            <Panel title={t('dash.temperature')} icon={ThermometerIcon}>
              {p.temperature ? <Hist t={t} k={k} title="°C" h={p.temperature} digits={1} /> : <p className="text-sm text-muted-foreground">{t('dash.temperatureNone')}</p>}
            </Panel>

            {p.hemoglobin && (
              <Panel title={t('dash.hemoglobin')} icon={StethoscopeIcon}>
                <Hist t={t} k={k} title="g/dL" h={p.hemoglobin} />
              </Panel>
            )}

            {p.anc && (
              <Panel title={t('dash.anc')} icon={ClipboardCheckIcon}>
                <div className="grid gap-5 sm:grid-cols-2">
                  <Categories t={t} k={k} title={t('dash.firstVisit')} counts={p.anc.firstVisit} label={(c) => t(`dash.${c}` as TKey)} />
                  {p.anc.visitCounts && <Categories t={t} k={k} title={t('dash.visitCounts')} counts={p.anc.visitCounts} label={(c) => (c === '9' ? '9+' : c)} />}
                </div>
              </Panel>
            )}

            {p.delivery && p.delivery.n > 0 && (
              <Panel title={t('dash.delivery')} icon={BabyIcon} className="lg:col-span-2">
                <div className="grid gap-5 md:grid-cols-3">
                  <Categories t={t} k={k} title={t('dash.modeTitle')} counts={p.delivery.mode} label={(c) => t(`dash.mode.${c}` as TKey)} />
                  <Hist t={t} k={k} title={t('dash.birthWeight')} h={p.delivery.birthWeight} />
                  <Hist t={t} k={k} title={t('dash.gaAtBirth')} h={p.delivery.gaAtBirth} footer={`${t('dash.preterm')} : ${p.delivery.preterm.preterm ?? t('dash.lessThan', { k })}`} />
                  {Object.values(p.delivery.place).some((c) => c !== 0) && (
                    <Categories t={t} k={k} title={t('dash.placeTitle')} counts={p.delivery.place} label={(c) => t(`dash.place.${c}` as TKey)} />
                  )}
                </div>
              </Panel>
            )}

            {p.completeness && (
              <Panel title={t('dash.completeness')} hint={t('dash.completenessHint')} icon={ClipboardCheckIcon}>
                <ul className="flex flex-col gap-2.5">
                  {p.completeness.map((c) => {
                    const share = c.recorded == null || !c.total ? null : c.recorded / c.total
                    return (
                      <li key={c.measure} className="grid grid-cols-[8rem_1fr_3.5rem] items-center gap-3 text-sm">
                        <span className="text-muted-foreground">{t(`dash.measure.${c.measure}` as TKey)}</span>
                        <span className="h-2.5 overflow-hidden rounded-full bg-muted">
                          <span className="block h-full rounded-full bg-viz-1" style={{ width: `${(share ?? 0) * 100}%` }} />
                        </span>
                        <span className="text-right font-semibold tabular-nums">{share == null ? t('dash.lessThan', { k }) : `${Math.round(share * 100)} %`}</span>
                      </li>
                    )
                  })}
                </ul>
              </Panel>
            )}
          </div>
        )}

        <p className="flex items-start gap-2 text-sm text-muted-foreground">
          <ShieldCheckIcon className="mt-0.5 size-4 shrink-0" /> {t('dash.kNote', { k })}
        </p>
      </div>
    </div>
  )
}

function Panel({ title, hint, icon: Icon, children, className }: { title: string; hint?: string; icon: LucideIcon; children: ReactNode; className?: string }) {
  return (
    <section className={cn('flex min-w-0 flex-col gap-3 rounded-2xl border bg-card p-4 sm:p-5', className)}>
      <header>
        <h2 className="flex items-center gap-2 text-lg font-bold">
          <Icon className="size-5 text-primary" /> {title}
        </h2>
        {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
      </header>
      {children}
    </section>
  )
}

function countText(t: T, k: number, c: Count) {
  return c == null ? t('dash.lessThan', { k }) : t('dash.womenCount', { n: c })
}

/** Histogram: empty open-ended classes at either end are dropped; edges labelled. */
function Hist({ t, k, title, h, digits = 0, footer }: { t: T; k: number; title: string; h: Histogram; digits?: number; footer?: string }) {
  let bins = h.bins
  if (bins[0]?.count === 0) bins = bins.slice(1)
  if (bins.at(-1)?.count === 0) bins = bins.slice(0, -1)
  const n = (v: number | null) => (v == null ? '' : fmt(v, t.lang, digits))
  const columns: Column[] = bins.map((b, i) => ({
    id: String(i),
    label: n(b.from),
    count: b.count,
    tooltip: `${b.from == null ? t('dash.classLow', { to: n(b.to) }) : b.to == null ? t('dash.classHigh', { from: n(b.from) }) : t('dash.class', { from: n(b.from), to: n(b.to) })} : ${countText(t, k, b.count)}`,
  }))
  const edges = [...bins.map((b) => n(b.from)), n(bins.at(-1)?.to ?? null)]
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ColumnChart columns={columns} histogram edgeLabels={edges} label={title} suppressedLabel={t('dash.lessThan', { k })} />
      {footer && <p className="text-xs text-muted-foreground">{footer}</p>}
    </div>
  )
}

function Categories<K extends string>({ t, k, title, counts, label }: { t: T; k: number; title: string; counts: Record<K, Count>; label: (c: K) => string }) {
  const columns: Column[] = (Object.entries(counts) as [K, Count][]).map(([c, n]) => ({
    id: c,
    label: label(c),
    count: n,
    tooltip: `${label(c)} : ${countText(t, k, n)}`,
  }))
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ColumnChart columns={columns} label={title} suppressedLabel={t('dash.lessThan', { k })} />
    </div>
  )
}

function Tests({ t, k, tests }: { t: T; k: number; tests: NonNullable<Aggregates['panels']['tests']> }) {
  const order = ['neg', 'pos', 'notRecorded', 'noPage'] as const
  const fills: Record<(typeof order)[number], string> = { neg: 'var(--viz-1)', pos: 'var(--viz-2)', notRecorded: 'var(--viz-missing)', noPage: 'hatch' }
  const used = order.filter((o) => tests.some((x) => x[o] !== 0))
  const styles: SegmentStyle[] = used.map((o) => ({ id: o, label: t(`dash.test.${o}`), fill: fills[o] }))
  return (
    <StackedBars
      rows={tests.map((x) => ({ id: x.test, label: t(`trends.test.${x.test}` as TKey), segments: used.map((o) => ({ id: o, count: x[o] })) }))}
      styles={styles}
      label={t('dash.tests')}
      suppressedLabel={t('dash.lessThan', { k })}
      formatShare={(c, total) => `${Math.round((c / total) * 100)} %`}
    />
  )
}
