import type { PageType } from '@/contract/enums'
import { fieldDef } from '@/contract/registry'
import type { Field } from '@/contract/types'
import { formatValue, useT } from '@/i18n'
import { cn } from '@/lib/utils'
import { ConfidenceMeter, OriginTag, StatusBadge } from './status'

/**
 * One line of a registry page, read-only: label, value, status, confidence and
 * who set it. Corrections happen on WhatsApp, never in this dashboard.
 */
export function FieldRow({ field, pageType, focused, onFocus }: { field: Field; pageType: PageType; focused?: boolean; onFocus?: () => void }) {
  const t = useT()
  const kind = field.kind ?? fieldDef(pageType, field.key)?.kind ?? 'text'
  return (
    <div className={cn('flex flex-col gap-1.5 rounded-lg px-3 py-2.5 transition-colors', focused ? 'bg-secondary' : 'hover:bg-muted/60')} onMouseEnter={onFocus}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="min-w-0 flex-1 basis-48 text-sm text-muted-foreground">{t.field(pageType, field.key, field.label)}</span>
        <span className={cn('text-base font-semibold', field.value === null && 'text-muted-foreground')}>{formatValue(t, kind, field.value)}</span>
        <StatusBadge status={field.status} size="sm" />
      </div>
      {field.reason && field.status !== 'KNOWN' && (
        <span className="text-xs text-review">
          {t(`reason.${field.reason}`)}
          {field.readValue && ` · ${t('review.readAs', { v: field.readValue })}`}
        </span>
      )}
      {field.value !== null && (
        <div className="flex items-center gap-3">
          <OriginTag origin={field.origin} />
          {field.origin === 'AI' && <ConfidenceMeter value={field.confidence} />}
          {field.aiValue !== undefined && field.origin === 'CORRECTED' && (
            <span className="text-xs text-muted-foreground">{t('review.wasAi', { v: formatValue(t, kind, field.aiValue) })}</span>
          )}
        </div>
      )}
    </div>
  )
}
