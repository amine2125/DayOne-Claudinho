import { CheckIcon, LoaderIcon, XIcon } from 'lucide-react'
import { FAILURE_STATES, type LifecycleState } from '@/contract/enums'
import { STEPS, stepIndex } from '@/contract/lifecycle'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'

/** Where a record is, in five steps a midwife understands. The exact state is the caption. */
export function LifecycleStepper({
  state,
  busy = false,
  compact = false,
  className,
}: {
  state: LifecycleState
  busy?: boolean
  compact?: boolean
  className?: string
}) {
  const t = useT()
  const current = stepIndex(state)
  const done = state === 'SYNCED'
  const failed = FAILURE_STATES.includes(state)

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <ol className="flex items-center" aria-label={t(`state.${state}`)}>
        {STEPS.map((step, i) => {
          const isDone = i < current || done
          const isCurrent = i === current && !done
          return (
            <li key={step.id} className={cn('flex items-center', i < STEPS.length - 1 && 'flex-1')}>
              <span className="flex flex-col items-center gap-1">
                <span
                  className={cn(
                    'flex items-center justify-center rounded-full border-2 transition-colors',
                    compact ? 'size-4' : 'size-7',
                    isDone && 'border-primary bg-primary text-primary-foreground',
                    isCurrent && !failed && 'border-primary bg-background text-primary',
                    isCurrent && failed && 'border-illegible bg-illegible-soft text-illegible',
                    !isDone && !isCurrent && 'border-border bg-background text-muted-foreground',
                  )}
                >
                  {!compact &&
                    (isDone ? (
                      <CheckIcon className="size-4" />
                    ) : isCurrent && failed ? (
                      <XIcon className="size-4" />
                    ) : isCurrent && busy ? (
                      <LoaderIcon className="size-4 animate-spin" />
                    ) : (
                      <span className="text-xs font-bold">{i + 1}</span>
                    ))}
                </span>
                {!compact && (
                  <span className={cn('text-xs', isCurrent ? 'font-semibold text-foreground' : 'text-muted-foreground')}>
                    {t(`step.${step.id}`)}
                  </span>
                )}
              </span>
              {i < STEPS.length - 1 && (
                <span className={cn('mx-1 h-0.5 flex-1 rounded', compact ? '' : '-mt-5', i < current || done ? 'bg-primary' : 'bg-border')} />
              )}
            </li>
          )
        })}
      </ol>
      {compact && (
        <span className={cn('text-xs', failed ? 'font-semibold text-illegible' : 'text-muted-foreground')}>
          {busy ? t('captures.processing') : t(`state.${state}`)}
        </span>
      )}
    </div>
  )
}
