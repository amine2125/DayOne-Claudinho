import { CircleCheckIcon, ImageIcon, TriangleAlertIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { isReadable } from '@/contract/registry'
import type { RegistryRecord, Visit } from '@/contract/types'
import { openFields } from '@/services'
import { useT } from '@/i18n'

/** Visits, newest first, each with the registry pages photographed that day. */
export function VisitTimeline({ visits, records }: { visits: Visit[]; records: Record<string, RegistryRecord> }) {
  const t = useT()
  const sorted = [...visits].sort((a, b) => b.date.localeCompare(a.date))
  return (
    <ol className="relative flex flex-col gap-6 pl-8 before:absolute before:top-2 before:bottom-2 before:left-[11px] before:w-0.5 before:bg-border">
      {sorted.map((v, i) => {
        const recs = v.recordIds.map((id) => records[id]).filter(Boolean)
        return (
          <li key={v.id} className="relative">
            <span className={`absolute top-1 -left-8 flex size-6 items-center justify-center rounded-full border-2 ${i === 0 ? 'border-primary bg-primary' : 'border-primary/40 bg-background'}`}>
              {i === 0 && <span className="size-2 rounded-full bg-primary-foreground" />}
            </span>
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="text-lg font-bold">{t.date(v.date)}</span>
                <span className="text-sm text-muted-foreground">
                  {t.relative(v.date)} · {t('patient.visit.by', { id: v.midwifeId })}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {recs.flatMap((r) =>
                  r.pages.map((p, pi) => {
                    const open = openFields(p).length
                    const Icon = !isReadable(p.pageType) || !Object.keys(p.fields).length ? ImageIcon : open ? TriangleAlertIcon : CircleCheckIcon
                    return (
                      <Link
                        key={p.id}
                        to={`/records/${r.id}/review?page=${pi}`}
                        className="inline-flex h-10 items-center gap-2 rounded-lg border bg-card px-3 text-sm hover:border-primary"
                      >
                        <Icon className={`size-4 ${open ? 'text-review' : Icon === CircleCheckIcon ? 'text-known' : 'text-muted-foreground'}`} />
                        {t(`page.${p.pageType}`)}
                      </Link>
                    )
                  }),
                )}
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
