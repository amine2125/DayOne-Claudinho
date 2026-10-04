import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { niceTicks, useWidth } from './kit'

export interface TrendPoint {
  id: string
  x: number
  /** Main value (systolic for blood pressure). */
  y: number
  /** Second value of the same visit (diastolic). */
  y2?: number
  /** Still to check on the paper: drawn hollow, in the review color. */
  review?: boolean
  /** Confirmed or corrected by the midwife. */
  verified?: boolean
  /** Tooltip: where on the x axis ("22 SA · 28 sept. 2025"), the value ("62,7 kg"), a note. */
  xLabel: string
  valueLabel: string
  note?: string
  /** The registry page this value was read on. */
  href?: string
}

export interface TrendSeries {
  name: string
  color: string
}

const M = { top: 14, right: 14, bottom: 26, left: 40 }

/**
 * One measure over the pregnancy (or the newborn's first weeks), from the registry, as written.
 * No reference band, no threshold: the chart shows the values, the midwife reads them.
 * Hover or focus snaps a crosshair to the nearest visit; a click opens the page it was read on.
 */
export function TrendChart({
  points,
  series,
  height = 180,
  xTicks,
  formatX,
  label,
  className,
}: {
  points: TrendPoint[]
  /** One series, or two (systolic / diastolic) drawn from y and y2. */
  series: [TrendSeries] | [TrendSeries, TrendSeries]
  height?: number
  xTicks?: number[]
  formatX: (x: number) => string
  label: string
  className?: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [active, setActive] = useState<number>()
  const navigate = useNavigate()
  const pts = [...points].sort((a, b) => a.x - b.x)
  if (!pts.length) return null

  const xs = pts.map((p) => p.x)
  const ys = pts.flatMap((p) => (p.y2 == null ? [p.y] : [p.y, p.y2]))
  const xPad = Math.max(1, (Math.max(...xs) - Math.min(...xs)) * 0.06)
  const x0 = Math.min(...xs) - xPad
  const x1 = Math.max(...xs) + xPad
  const yRange = Math.max(...ys) - Math.min(...ys)
  const yTicks = niceTicks(Math.min(...ys) - Math.max(yRange * 0.15, 1), Math.max(...ys) + Math.max(yRange * 0.15, 1), 4)
  const y0 = yTicks[0]
  const y1 = yTicks[yTicks.length - 1]
  const W = width - M.left - M.right
  const H = height - M.top - M.bottom
  const sx = (x: number) => M.left + ((x - x0) / (x1 - x0 || 1)) * W
  const sy = (y: number) => M.top + H - ((y - y0) / (y1 - y0 || 1)) * H
  const ticksX = (xTicks ?? niceTicks(x0, x1, Math.max(2, Math.floor(W / 70)))).filter((t) => t >= x0 && t <= x1)
  const line = (get: (p: TrendPoint) => number | undefined) =>
    pts
      .filter((p) => get(p) != null)
      .map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(get(p)!).toFixed(1)}`)
      .join('')

  const nearest = (clientX: number, rect: DOMRect) => {
    const x = clientX - rect.left
    let best = 0
    pts.forEach((p, i) => Math.abs(sx(p.x) - x) < Math.abs(sx(pts[best].x) - x) && (best = i))
    return best
  }
  const open = (i: number | undefined) => i != null && pts[i].href && navigate(pts[i].href!)
  const a = active != null ? pts[active] : undefined

  return (
    <div ref={ref} className={cn('relative', className)}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={label}
        className="block overflow-visible select-none"
        onPointerMove={(e) => setActive(nearest(e.clientX, e.currentTarget.getBoundingClientRect()))}
        onPointerLeave={() => setActive(undefined)}
        onClick={() => open(active)}
      >
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={width - M.right} y1={sy(t)} y2={sy(t)} className="stroke-border" strokeWidth={1} />
            <text x={M.left - 6} y={sy(t)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[11px] tabular-nums">
              {t}
            </text>
          </g>
        ))}
        {ticksX.map((t) => (
          <text key={t} x={sx(t)} y={height - 6} textAnchor="middle" className="fill-muted-foreground text-[11px] tabular-nums">
            {formatX(t)}
          </text>
        ))}
        {a && <line x1={sx(a.x)} x2={sx(a.x)} y1={M.top} y2={M.top + H} className="stroke-muted-foreground/50" strokeWidth={1} />}
        {series.length === 2 &&
          pts.map((p) =>
            p.y2 == null ? null : (
              <line key={`r${p.id}`} x1={sx(p.x)} x2={sx(p.x)} y1={sy(p.y)} y2={sy(p.y2)} className="stroke-border" strokeWidth={2} />
            ),
          )}
        {series.map((s, si) => (
          <path
            key={s.name}
            d={line((p) => (si === 0 ? p.y : p.y2))}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
        {series.map((s, si) =>
          pts.map((p, i) => {
            const v = si === 0 ? p.y : p.y2
            if (v == null) return null
            return (
              <circle
                key={`${s.name}${p.id}`}
                cx={sx(p.x)}
                cy={sy(v)}
                r={i === active ? 5.5 : 4.5}
                fill={p.review ? 'var(--card)' : s.color}
                stroke={p.review ? 'var(--st-review)' : 'var(--card)'}
                strokeWidth={2}
              />
            )
          }),
        )}
        {/* Hit targets: 24px, focusable, so every value is reachable without a mouse. */}
        {pts.map((p, i) => (
          <circle
            key={`hit${p.id}`}
            cx={sx(p.x)}
            cy={sy(p.y)}
            r={12}
            fill="transparent"
            tabIndex={0}
            role="button"
            aria-label={`${p.xLabel} : ${p.valueLabel}${p.note ? ` — ${p.note}` : ''}`}
            className={cn('outline-none', p.href && 'cursor-pointer')}
            onFocus={() => setActive(i)}
            onBlur={() => setActive(undefined)}
            onKeyDown={(e) => e.key === 'Enter' && open(i)}
          />
        ))}
      </svg>
      {a && (
        <div
          className="pointer-events-none absolute z-10 w-max max-w-56 rounded-lg border bg-popover px-3 py-2 text-sm shadow-md"
          style={{
            left: Math.min(Math.max(sx(a.x) - 70, 0), width - 150),
            top: Math.max(sy(a.y) - 74, -8),
          }}
        >
          <div className="font-semibold tabular-nums">{a.valueLabel}</div>
          <div className="text-xs text-muted-foreground">{a.xLabel}</div>
          {a.note && <div className={cn('mt-1 text-xs', a.review ? 'text-review' : 'text-muted-foreground')}>{a.note}</div>}
        </div>
      )}
    </div>
  )
}
