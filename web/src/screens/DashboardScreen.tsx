import { ActivityIcon, MicroscopeIcon, ThermometerIcon, type LucideIcon } from 'lucide-react'
import { PageHeader } from '@/components/AppShell'
import { useRecords } from '@/services'
import { useT, type TKey } from '@/i18n'

/** Reserved slots for anonymised aggregates. No charts, no clinical computation yet. */
const SLOTS: { label: TKey; icon: LucideIcon }[] = [
  { label: 'dash.slot.bp', icon: ActivityIcon },
  { label: 'dash.slot.temp', icon: ThermometerIcon },
  { label: 'dash.slot.infections', icon: MicroscopeIcon },
]

export function DashboardScreen() {
  const t = useT()
  const records = useRecords()
  const fields = records.flatMap((r) => r.pages.flatMap((p) => Object.values(p.fields)))
  const written = fields.filter((f) => f.status !== 'NOT_PROVIDED' && f.status !== 'NOT_APPLICABLE')
  const stats = [
    { label: 'dash.pages' as TKey, value: String(records.reduce((n, r) => n + r.pages.filter((p) => Object.keys(p.fields).length).length, 0)) },
    {
      label: 'dash.autoRead' as TKey,
      value: written.length ? `${Math.round((written.filter((f) => f.origin === 'AI' && f.status === 'KNOWN').length / written.length) * 100)} %` : '—',
    },
    { label: 'dash.humanChecked' as TKey, value: String(fields.filter((f) => f.origin !== 'AI').length) },
  ]
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title={t('dash.title')} subtitle={t('dash.subtitle')} />
      <div className="flex flex-col gap-6 px-4 sm:px-6 lg:px-8">
        <div className="grid gap-3 sm:grid-cols-3">
          {stats.map((s) => (
            <div key={s.label} className="rounded-2xl border bg-card p-5">
              <div className="text-3xl font-bold tabular-nums">{s.value}</div>
              <div className="text-sm text-muted-foreground">{t(s.label)}</div>
            </div>
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {SLOTS.map((s) => (
            <div key={s.label} className="flex min-h-48 flex-col gap-3 rounded-2xl border-2 border-dashed p-5">
              <h2 className="flex items-center gap-2 font-semibold">
                <s.icon className="size-5 text-primary" /> {t(s.label)}
              </h2>
              <p className="mt-auto text-sm text-muted-foreground">{t('dash.slot.hint')}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
