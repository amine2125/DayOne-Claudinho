import { ChevronDownIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { Field } from '@/contract/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'

const EMPTY = new Set(['NOT_PROVIDED', 'NOT_APPLICABLE'])

/**
 * A section of the registry page. Written fields are shown; blank ones are folded
 * into one line, so the eye goes to what is actually on the paper.
 */
export function SectionCard({
  title,
  fields,
  renderField,
  action,
  className,
}: {
  title: string
  fields: Field[]
  renderField: (f: Field) => ReactNode
  action?: ReactNode
  className?: string
}) {
  const t = useT()
  const [showEmpty, setShowEmpty] = useState(false)
  const filled = fields.filter((f) => !EMPTY.has(f.status))
  const empty = fields.filter((f) => EMPTY.has(f.status))
  return (
    <section className={cn('rounded-xl border bg-card', className)}>
      <header className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <h3 className="font-semibold">{t.section(title)}</h3>
        {action}
      </header>
      <div className="flex flex-col p-1.5">
        {filled.map((f) => (
          <div key={f.key}>{renderField(f)}</div>
        ))}
        {empty.length > 0 && (
          <>
            <button
              type="button"
              onClick={() => setShowEmpty((v) => !v)}
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-muted-foreground hover:bg-muted/60"
            >
              <ChevronDownIcon className={cn('size-4 transition-transform', showEmpty && 'rotate-180')} />
              {t('review.emptyFields', { n: empty.length })}
            </button>
            {showEmpty && empty.map((f) => <div key={f.key}>{renderField(f)}</div>)}
          </>
        )}
      </div>
    </section>
  )
}
