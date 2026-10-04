/**
 * Small shared pieces of the charts: container width, clean axis ticks.
 * Charts are hand-drawn SVG (no chart library): thin marks, hairline grid, text in text tokens.
 */
import { useEffect, useRef, useState } from 'react'

/** Width of a container, kept up to date (charts redraw at the real width, text never scales). */
export function useWidth<T extends HTMLElement>(fallback = 320) {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(160, Math.round(e.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

/** About `count` round ticks covering [lo, hi] (1, 2, 2.5, 5 × 10ⁿ steps). */
export function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return []
  if (lo === hi) {
    lo -= 1
    hi += 1
  }
  const raw = (hi - lo) / Math.max(1, count)
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.round(v * 1e6) / 1e6)
  return out
}

/** Number in the viewer's language: 62,7 in French, 62.7 in English. */
export function fmt(n: number, lang: string, digits = 1): string {
  return n.toLocaleString(lang === 'fr' ? 'fr-FR' : 'en-GB', { maximumFractionDigits: digits })
}
