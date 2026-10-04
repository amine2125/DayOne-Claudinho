import { useId, useState } from 'react'
import { useWidth } from './kit'

export interface Segment {
  id: string
  /** null: fewer than K women, hidden (drawn as a thin hatched sliver, « < 5 »). */
  count: number | null
}

export interface StackRow {
  id: string
  label: string
  segments: Segment[]
}

export interface SegmentStyle {
  id: string
  label: string
  /** CSS color, or "hatch" for "not photographed". */
  fill: string
}

const SLIVER = 8

/**
 * One 100 % bar per row (e.g. one per infection test), segments in a fixed order with a 2px gap.
 * Legend above; value inside a segment only when it fits; every value in the tooltip.
 */
export function StackedBars({
  rows,
  styles,
  label,
  suppressedLabel,
  formatShare,
}: {
  rows: StackRow[]
  styles: SegmentStyle[]
  label: string
  suppressedLabel: string
  formatShare: (count: number, total: number) => string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [active, setActive] = useState<{ row: number; seg: number; x: number; y: number }>()
  const hatch = useId().replace(/:/g, '')
  const labelW = Math.min(150, width * 0.32)
  const barW = width - labelW
  const rowH = 30
  const style = (id: string) => styles.find((s) => s.id === id)!

  return (
    <div ref={ref} className="relative flex flex-col gap-3">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {styles.map((s) => (
          <li key={s.id} className="flex items-center gap-1.5">
            <svg width="12" height="12" aria-hidden>
              <rect width="12" height="12" rx="3" fill={s.fill === 'hatch' ? `url(#${hatch})` : s.fill} stroke={s.fill === 'hatch' ? 'var(--viz-missing)' : 'none'} />
            </svg>
            {s.label}
          </li>
        ))}
      </ul>
      <svg width={width} height={rows.length * (rowH + 10)} role="img" aria-label={label} className="block select-none">
        <defs>
          <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--card)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--viz-missing)" strokeWidth="3" />
          </pattern>
        </defs>
        {rows.map((row, ri) => {
          const known = row.segments.reduce((n, s) => n + (s.count ?? 0), 0)
          const slivers = row.segments.filter((s) => s.count === null).length
          const shown = row.segments.filter((s) => s.count !== 0)
          const gaps = Math.max(0, shown.length - 1) * 2
          const free = Math.max(0, barW - gaps - slivers * SLIVER)
          const y = ri * (rowH + 10)
          let x = labelW
          return (
            <g key={row.id}>
              <text x={0} y={y + rowH / 2} dy="0.32em" className="fill-foreground text-[13px] font-semibold">
                {row.label}
              </text>
              {shown.map((s) => {
                const w = s.count === null ? SLIVER : known ? (s.count / known) * free : 0
                const st = style(s.id)
                const seg = row.segments.indexOf(s)
                const x0 = x
                x += w + 2
                const share = s.count === null ? suppressedLabel : formatShare(s.count, known)
                const fits = w > share.length * 7 + 10
                const dark = st.fill.includes('viz-1') || st.fill.includes('viz-2')
                return (
                  <g
                    key={s.id}
                    tabIndex={0}
                    role="img"
                    aria-label={`${row.label} · ${st.label} : ${s.count ?? suppressedLabel}`}
                    className="outline-none"
                    onPointerEnter={() => setActive({ row: ri, seg, x: x0 + w / 2, y })}
                    onPointerLeave={() => setActive(undefined)}
                    onFocus={() => setActive({ row: ri, seg, x: x0 + w / 2, y })}
                    onBlur={() => setActive(undefined)}
                  >
                    <rect x={x0} y={y} width={Math.max(w, 1)} height={rowH} rx={4} fill={st.fill === 'hatch' || s.count === null ? `url(#${hatch})` : st.fill} />
                    {fits && (
                      <text x={x0 + w / 2} y={y + rowH / 2} dy="0.32em" textAnchor="middle" className={dark ? 'fill-white text-[12px] font-semibold' : 'fill-foreground text-[12px] font-semibold'}>
                        {share}
                      </text>
                    )}
                  </g>
                )
              })}
            </g>
          )
        })}
      </svg>
      {active && (
        <div
          className="pointer-events-none absolute z-10 w-max rounded-lg border bg-popover px-3 py-1.5 text-sm shadow-md"
          style={{ left: Math.min(Math.max(active.x - 70, 0), width - 160), top: active.y + 44 }}
        >
          {(() => {
            const row = rows[active.row]
            const s = row.segments[active.seg]
            const total = row.segments.reduce((n, x) => n + (x.count ?? 0), 0)
            return (
              <>
                <span className="font-semibold tabular-nums">{s.count ?? suppressedLabel}</span>
                {s.count != null && total > 0 && <span className="text-muted-foreground"> · {formatShare(s.count, total)}</span>}
                <div className="text-xs text-muted-foreground">
                  {row.label} · {style(s.id).label}
                </div>
              </>
            )
          })()}
        </div>
      )}
    </div>
  )
}
