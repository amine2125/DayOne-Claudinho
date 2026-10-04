import { FileTextIcon, MessageCircleIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { nextAction } from '@/contract/lifecycle'
import type { RegistryRecord } from '@/contract/types'
import { openFields, useAppState } from '@/services'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { LifecycleStepper } from './LifecycleStepper'
import { PageImage } from './PageImage'
import { PatientCode } from './PatientCode'

/**
 * What the record is waiting for, in words. The dashboard never acts on a
 * record: review, retakes and patient choice happen on WhatsApp.
 */
export function RecordStatusNote({ record }: { record: RegistryRecord }) {
  const t = useT()
  const online = useAppState((s) => s.online)
  const action = nextAction(record.state, online)
  if (action === 'NONE') return null
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold',
        action === 'WAIT_NETWORK' ? 'bg-muted text-muted-foreground' : action === 'RETRY' ? 'bg-illegible-soft text-illegible' : 'bg-review-soft text-review',
      )}
    >
      {action !== 'WAIT_NETWORK' && <MessageCircleIcon className="size-3.5" />}
      {t(`pending.${action}`)}
    </span>
  )
}

export function RecordRow({ record, className }: { record: RegistryRecord; className?: string }) {
  const t = useT()
  const busy = useAppState((s) => s.busy.includes(record.id))
  const patient = useAppState((s) => (record.patientId ? s.patients[record.patientId] : undefined))
  const toCheck = record.pages.reduce((n, p) => n + openFields(p).length, 0)
  const first = record.pages[0]

  return (
    <div className={cn('flex flex-col gap-3 rounded-xl border bg-card p-3 sm:flex-row sm:items-center sm:gap-4', className)}>
      <Link to={`/records/${record.id}`} className="flex min-w-0 flex-1 items-center gap-3">
        <div className="w-14 shrink-0">
          {first?.imageUrl ? (
            <PageImage page={first} thumb />
          ) : (
            <div className="flex aspect-[3/4] items-center justify-center rounded-md bg-muted">
              <FileTextIcon className="size-5 text-muted-foreground" />
            </div>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <PatientCode code={patient?.code ?? record.patientCode} />
            {toCheck > 0 && record.state === 'NEEDS_REVIEW' && (
              <span className="text-xs font-semibold text-review">{t('review.summary.toCheck', { n: toCheck })}</span>
            )}
          </div>
          <span className="truncate text-sm">{record.pages.map((p) => t(`page.${p.pageType}`)).join(' + ')}</span>
          <span className="text-xs text-muted-foreground">
            {t.relative(record.createdAt)} · {record.midwifeId}
          </span>
        </div>
      </Link>
      <LifecycleStepper state={record.state} busy={busy} compact className="sm:w-44" />
      <div className="flex sm:w-48 sm:justify-end">
        <RecordStatusNote record={record} />
      </div>
    </div>
  )
}
