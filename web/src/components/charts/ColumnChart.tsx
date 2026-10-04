import { useId, useState } from 'react'
import { cn } from '@/lib/utils'
import { niceTicks, useWidth } from './kit'

export interface Column {
  id: string
  /** Under the column (categories), or at the left edge of a histogram class. */
  label: string
  /** null: fewer than K women, hidden to protect anonymity (drawn hatched, « < 5 »). */
  count: number | null
  tooltip: string
}

const M = { top: 18, right: 8, bottom: 26, left: 34 }

/**
 * Counts as columns: a histogram (classes side by side) or a few categories.
 * Columns ≤ 24px with a 4px rounded top, one hue; values on the cap only when there are few columns.
 */
export function ColumnChart({
  columns,
  color = 'var(--viz-1)',
  height = 170,
  histogram,
  edgeLabels,
  label,
  suppressedLabel,
}: {
  columns: Column[]
  color?: string
  height?: number
  /** Classes of a histogram: labels sit on the edges between columns, every other one if crowded. */
  histogram?: boolean
  /** Histogram: n+1 edge labels for n columns ("" for an open end). */
  edgeLabels?: string[]
  label: string
  suppressedLabel: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [active, setActive] = useState<number>()
  const hatch = useId().replace(/:/g, '')
  const counts = columns.map((c) => c.count ?? 0)
  const ticks = niceTicks(0, Math.max(4, ...counts), 3)
  const top = ticks[ticks.length - 1] || 1
  const W = width - M.left - M.right
  const H = height - M.top - M.bottom
  const slot = W / Math.max(1, columns.length)
  const bar = Math.min(24, slot - 2)
  const sy = (v: number) => M.top + H - (v / top) * H
  const showValues = !histogram && columns.length <= 6
  const edgeStep = edgeLabels && edgeLabels.length * 34 > W ? 2 : 1

  return (
    <div ref={ref} className="relative">
      <svg width={width} height={height} role="img" aria-label={label} className="block overflow-visible select-none">
        <defs>
          <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--card)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--viz-missing)" strokeWidth="3" />
          </pattern>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={width - M.right} y1={sy(t)} y2={sy(t)} className="stroke-border" strokeWidth={1} />
            <text x={M.left - 6} y={sy(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[11px] tabular-nums">
              {t}
            </text>
          </g>
        ))}
        {columns.map((c, i) => {
          const cx = M.left + slot * i + slot / 2
          const suppressed = c.count === null
          const h = suppressed ? Math.min(H, 10) : Math.max(0, H - (sy(c.count!) - M.top))
          const x = cx - bar / 2
          const y = M.top + H - h
          const r = Math.min(4, h, bar / 2)
          return (
            <g
              key={c.id}
              tabIndex={0}
              role="img"
              aria-label={c.tooltip}
              onPointerEnter={() => setActive(i)}
              onPointerLeave={() => setActive(undefined)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(undefined)}
              className="outline-none"
            >
              <rect x={cx - slot / 2} y={M.top} width={slot} height={H} fill="transparent" />
              {h > 0 && (
                <path
                  d={`M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + bar - r}Q${x + bar},${y} ${x + bar},${y + r}V${y + h}Z`}
                  fill={suppressed ? `url(#${hatch})` : color}
                  opacity={active === undefined || active === i ? 1 : 0.55}
                />
              )}
              {(showValues || suppressed) && (
                <text x={cx} y={y - 5} textAnchor="middle" className="fill-foreground text-[11px] font-semibold tabular-nums">
                  {suppressed ? suppressedLabel : c.count}
                </text>
              )}
              {!histogram && (
                <text x={cx} y={height - 6} textAnchor="middle" className="fill-muted-foreground text-[11px]">
                  {c.label}
                </text>
              )}
            </g>
          )
        })}
        {histogram &&
          edgeLabels?.map((l, i) =>
            l && i % edgeStep === 0 ? (
              <text key={i} x={M.left + slot * i} y={height - 6} textAnchor="middle" className="fill-muted-foreground text-[11px] tabular-nums">
                {l}
              </text>
            ) : null,
          )}
      </svg>
      {active !== undefined && (
        <div
          className={cn('pointer-events-none absolute z-10 w-max max-w-52 rounded-lg border bg-popover px-3 py-1.5 text-sm shadow-md')}
          style={{ left: Math.min(Math.max(M.left + slot * active + slot / 2 - 60, 0), width - 130), top: 0 }}
        >
          {columns[active].tooltip}
        </div>
      )}
    </div>
  )
}
