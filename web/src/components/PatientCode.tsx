import { cn } from '@/lib/utils'

/**
 * The patient code, the only identity in DayOne. Big, monospace, slashed zero,
 * so it reads exactly like what is written on the paper registry.
 * `highlight` marks characters that differ from another code.
 */
export function PatientCode({
  code,
  size = 'md',
  highlight = [],
  className,
}: {
  code: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  highlight?: number[]
  className?: string
}) {
  return (
    <span
      className={cn(
        'font-code inline-flex items-center font-bold text-foreground',
        { sm: 'text-sm', md: 'text-lg', lg: 'text-2xl', xl: 'text-4xl sm:text-5xl' }[size],
        className,
      )}
      aria-label={code.split('').join(' ')}
    >
      {[...code].map((c, i) => (
        <span key={i} className={cn(highlight.includes(i) && 'rounded-sm bg-review-soft px-px text-review ring-2 ring-review/50')}>
          {c}
        </span>
      ))}
    </span>
  )
}
