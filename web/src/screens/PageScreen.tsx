import {
  ArrowLeftIcon,
  CircleCheckIcon,
  FileJsonIcon,
  ImageIcon,
  LoaderIcon,
  MessageCircleIcon,
  ScanSearchIcon,
  SquareIcon,
  TriangleAlertIcon,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { STATUSES_TO_REVIEW } from '@/contract/enums'
import { SCHEMAS } from '@/contract/registry'
import type { Field, Page } from '@/contract/types'
import { PageHeader } from '@/components/AppShell'
import { FieldRow } from '@/components/FieldRow'
import { LifecycleStepper } from '@/components/LifecycleStepper'
import { PageImage, type Zone } from '@/components/PageImage'
import { PatientCode } from '@/components/PatientCode'
import { RecordStatusNote } from '@/components/RecordRow'
import { SectionCard } from '@/components/SectionCard'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { finalUrl, openFields, useAppState } from '@/services'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'

/** Reference fields in schema order, then the other fields in reading order (top to bottom). */
function orderedFields(page: Page): Field[] {
  const order = SCHEMAS[page.pageType]?.fields.map((f) => f.id) ?? []
  const rank = (f: Field, i: number) => (order.includes(f.key) ? order.indexOf(f.key) : order.length + i)
  return Object.values(page.fields)
    .map((f, i) => [f, rank(f, i)] as const)
    .sort((a, b) => a[1] - b[1])
    .map(([f]) => f)
}

function bySection(fields: Field[]) {
  const out: { id: string; fields: Field[] }[] = []
  for (const f of fields) (out.find((s) => s.id === f.section) ?? out[out.push({ id: f.section, fields: [] }) - 1]).fields.push(f)
  return out
}

/**
 * A registry record as read and checked: the masked photo next to its fields.
 * Read-only on purpose: corrections are made by the midwife on WhatsApp.
 */
export function PageScreen() {
  const { id = '' } = useParams()
  const t = useT()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const record = useAppState((s) => s.records[id])
  const patient = useAppState((s) => (record?.patientId ? s.patients[record.patientId] : undefined))
  const busy = useAppState((s) => s.busy.includes(id))
  const [pageIndex, setPageIndex] = useState(Number(params.get('page') ?? 0))
  const [focus, setFocus] = useState<string>()

  const page = record?.pages[pageIndex]
  const fields = useMemo(() => (page ? orderedFields(page) : []), [page])
  if (!record) return <p className="p-8 text-muted-foreground">{t('patient.notFound')}</p>

  const open = fields.filter((f) => STATUSES_TO_REVIEW.includes(f.status))
  const alerted = fields.filter((f) => f.alerts?.length).length
  const counts = {
    read: fields.filter((f) => f.status === 'KNOWN').length,
    blank: fields.filter((f) => f.status === 'NOT_PROVIDED' || f.status === 'NOT_APPLICABLE').length,
  }
  const zones: Zone[] = fields
    .filter((f) => f.bbox && f.status !== 'NOT_PROVIDED')
    .map((f) => ({ id: f.key, bbox: f.bbox!, tone: STATUSES_TO_REVIEW.includes(f.status) ? 'review' : 'muted' }))

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Button variant="ghost" size="icon-lg" aria-label={t('action.back')} onClick={() => navigate(-1)}>
              <ArrowLeftIcon />
            </Button>
            <PatientCode code={patient?.code ?? record.patientCode} size="lg" />
            <span className="text-xl font-semibold text-muted-foreground">{record.pages.map((p) => t.page(p)).join(' + ')}</span>
          </span>
        }
        subtitle={
          <span className="text-sm">
            {t.date(record.createdAt, true)} · {record.midwifeId}
          </span>
        }
        actions={<LifecycleStepper state={record.state} busy={busy} className="w-full min-w-80 sm:w-96" />}
      >
        <div className="flex flex-wrap items-center gap-2">
          <RecordStatusNote record={record} />
          {record.hasFinal && (
            <Button variant="outline" size="sm" render={<a href={finalUrl(record.id)} target="_blank" rel="noreferrer" />}>
              <FileJsonIcon /> {t('record.finalJson')}
            </Button>
          )}
          {record.pages.length > 1 &&
            record.pages.map((p, i) => (
              <button
                key={p.id}
                type="button"
                aria-pressed={i === pageIndex}
                onClick={() => setPageIndex(i)}
                className={cn(
                  'flex h-10 items-center gap-2 rounded-lg border-2 px-3 text-sm font-medium',
                  i === pageIndex ? 'border-primary bg-secondary' : 'border-border bg-card hover:border-primary/40',
                )}
              >
                {openFields(p).length > 0 ? <TriangleAlertIcon className="size-4 text-review" /> : <CircleCheckIcon className="size-4 text-known" />}
                {t.page(p)}
              </button>
            ))}
        </div>
      </PageHeader>

      {page && (
        <div className="grid gap-6 px-4 pb-10 sm:px-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:px-8">
          <div className="lg:sticky lg:top-24 lg:self-start">
            <PageImage page={page} zones={zones} focus={focus} onZoneClick={setFocus} className="mx-auto max-w-xl" />
          </div>

          <div className="flex min-w-0 flex-col gap-4">
            {record.state === 'PENDING_AI' || record.state === 'CAPTURED' ? (
              <Alert>
                <LoaderIcon className={cn(busy && 'animate-spin')} />
                <AlertDescription>{t(`state.${record.state}`)}</AlertDescription>
              </Alert>
            ) : fields.length === 0 ? (
              <Alert>
                <ImageIcon />
                <AlertDescription>{page.error ?? (record.failure ? t('failure.LAYOUT') : t('review.notReadable'))}</AlertDescription>
              </Alert>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-known-soft px-3 py-1.5 font-semibold text-known">
                    <CircleCheckIcon className="size-4" /> {t('review.summary.read', { n: counts.read })}
                  </span>
                  {open.length > 0 && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-review-soft px-3 py-1.5 font-semibold text-review">
                      <TriangleAlertIcon className="size-4" /> {t('review.summary.toCheck', { n: open.length })}
                    </span>
                  )}
                  {alerted > 0 && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-review-soft px-3 py-1.5 font-semibold text-review">
                      <ScanSearchIcon className="size-4" /> {t('review.summary.alerts', { n: alerted })}
                    </span>
                  )}
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-blank-soft px-3 py-1.5 text-blank">
                    <SquareIcon className="size-4" /> {t('review.summary.blank', { n: counts.blank })}
                  </span>
                </div>
                {open.length > 0 && (
                  <Alert>
                    <MessageCircleIcon />
                    <AlertDescription>{t('page.reviewOnWhatsapp')}</AlertDescription>
                  </Alert>
                )}
                {bySection(fields).map((s) => (
                  <SectionCard
                    key={s.id}
                    title={s.id}
                    fields={s.fields}
                    renderField={(f) => <FieldRow field={f} pageType={page.pageType} focused={focus === f.key} onFocus={() => setFocus(f.key)} />}
                  />
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
