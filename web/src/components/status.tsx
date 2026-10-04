import {
  CircleCheckIcon,
  CircleHelpIcon,
  CircleSlashIcon,
  EyeOffIcon,
  SquareIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from 'lucide-react'
import type { FieldOrigin, FieldStatus } from '@/contract/enums'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'

export const STATUS_STYLE: Record<FieldStatus, { icon: LucideIcon; text: string; soft: string; ring: string }> = {
  KNOWN: { icon: CircleCheckIcon, text: 'text-known', soft: 'bg-known-soft', ring: 'ring-known/30' },
  NEEDS_REVIEW: { icon: TriangleAlertIcon, text: 'text-review', soft: 'bg-review-soft', ring: 'ring-review/40' },
  ILLEGIBLE: { icon: EyeOffIcon, text: 'text-illegible', soft: 'bg-illegible-soft', ring: 'ring-illegible/40' },
  UNKNOWN: { icon: CircleHelpIcon, text: 'text-unknown', soft: 'bg-unknown-soft', ring: 'ring-unknown/30' },
  NOT_PROVIDED: { icon: SquareIcon, text: 'text-blank', soft: 'bg-blank-soft', ring: 'ring-blank/20' },
  NOT_APPLICABLE: { icon: CircleSlashIcon, text: 'text-blank', soft: 'bg-blank-soft', ring: 'ring-blank/20' },
}

/** Field status: icon + plain word + color, with an explanation on hover. */
export function StatusBadge({ status, size = 'md', className }: { status: FieldStatus; size?: 'sm' | 'md'; className?: string }) {
  const t = useT()
  const s = STATUS_STYLE[status]
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            className={cn(
              'inline-flex shrink-0 items-center gap-1.5 rounded-full font-semibold whitespace-nowrap',
              s.text,
              s.soft,
              size === 'sm' ? 'h-6 px-2 text-xs' : 'h-7 px-2.5 text-sm',
              className,
            )}
          />
        }
      >
        <s.icon className={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden />
        {t(`status.${status}`)}
      </TooltipTrigger>
      <TooltipContent className="max-w-60">{t(`statusHelp.${status}`)}</TooltipContent>
    </Tooltip>
  )
}

/** Three bars and a word. The exact percentage is one hover away, not in the way. */
export function ConfidenceMeter({ value, className }: { value: number; className?: string }) {
  const t = useT()
  const level = value >= 0.9 ? 3 : value >= 0.7 ? 2 : 1
  const tone = level === 3 ? 'bg-known' : level === 2 ? 'bg-review' : 'bg-illegible'
  const word = t(level === 3 ? 'conf.high' : level === 2 ? 'conf.medium' : 'conf.low')
  return (
    <Tooltip>
      <TooltipTrigger render={<span className={cn('inline-flex items-center gap-1.5 text-xs text-muted-foreground', className)} />}>
        <span className="flex items-end gap-0.5" aria-hidden>
          {[1, 2, 3].map((i) => (
            <span key={i} className={cn('w-1 rounded-sm', i <= level ? tone : 'bg-border')} style={{ height: 4 + i * 3 }} />
          ))}
        </span>
        {word}
      </TooltipTrigger>
      <TooltipContent>{t('conf.label', { pct: Math.round(value * 100) })}</TooltipContent>
    </Tooltip>
  )
}

export function OriginTag({ origin }: { origin: FieldOrigin }) {
  const t = useT()
  return (
    <span
      className={cn(
        'text-xs',
        origin === 'AI' ? 'text-muted-foreground' : origin === 'CORRECTED' ? 'font-semibold text-info' : 'font-semibold text-known',
      )}
    >
      {t(`origin.${origin}`)}
    </span>
  )
}
