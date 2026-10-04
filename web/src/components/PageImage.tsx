import { EyeIcon, ImageOffIcon, LockIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useCan } from '@/auth/roles'
import { SCHEMAS } from '@/contract/registry'
import type { BBox, Page } from '@/contract/types'
import { Button } from '@/components/ui/button'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'

export interface Zone {
  id: string
  bbox: BBox
  tone: 'review' | 'focus' | 'muted'
}

/** Personal-data zones for this page, or null when the photo does not match the template. */
function masksFor(page: Page): BBox[] | null {
  const schema = SCHEMAS[page.pageType]
  if (!schema) return null
  const [w, h] = schema.imageSize
  return page.imageSize[0] === w && page.imageSize[1] === h ? schema.excludedZones : null
}

const pct = (v: number, of: number) => `${(v / of) * 100}%`

/** Boxes positioned in the image's own pixel space, so they scale with it. */
function Overlay({ page, zones = [], focus, onZoneClick }: { page: Page; zones?: Zone[]; focus?: string; onZoneClick?: (id: string) => void }) {
  const t = useT()
  const [w, h] = page.imageSize
  const box = (b: BBox) => ({ left: pct(b[0], w), top: pct(b[1], h), width: pct(b[2] - b[0], w), height: pct(b[3] - b[1], h) })
  return (
    <>
      {masksFor(page)?.map((b, i) => (
        <span
          key={`m${i}`}
          style={box(b)}
          className="absolute flex items-center justify-center gap-1 overflow-hidden rounded-[2px] bg-foreground text-[clamp(6px,1.1cqw,12px)] font-semibold tracking-wide text-background uppercase"
          title={t('image.maskedHint')}
        >
          <LockIcon className="size-[1.2cqw] min-h-2 min-w-2" aria-hidden />
          {t('image.masked')}
        </span>
      ))}
      {zones.map((z) => (
        <button
          key={z.id}
          type="button"
          tabIndex={-1}
          style={box(z.bbox)}
          onClick={() => onZoneClick?.(z.id)}
          className={cn(
            'absolute rounded-[3px] border-2 transition-all',
            z.id === focus
              ? 'z-10 border-primary bg-primary/10 shadow-[0_0_0_9999px_rgb(0_0_0/0.35)]'
              : z.tone === 'review'
                ? 'border-review bg-review/15 hover:bg-review/25'
                : 'border-transparent hover:border-primary/60',
          )}
        />
      ))}
    </>
  )
}

function Guard({ page, children, className, thumb }: { page: Page; children: (blur: boolean) => ReactNode; className?: string; thumb?: boolean }) {
  const t = useT()
  const allowed = useCan('original_image')
  const [revealed, setRevealed] = useState(false)
  if (!allowed)
    return (
      <div className={cn('flex flex-col items-center justify-center gap-2 rounded-lg bg-muted text-center text-sm text-muted-foreground', thumb ? 'aspect-[3/4] p-1' : 'p-6', className)}>
        <LockIcon className="size-6" />
        {!thumb && t('image.noAccess')}
      </div>
    )
  if (!page.imageUrl)
    return (
      <div className={cn('flex flex-col items-center justify-center gap-2 rounded-lg bg-muted text-center text-sm text-muted-foreground', thumb ? 'aspect-[3/4] p-1' : 'p-6', className)}>
        <ImageOffIcon className="size-6" />
        {!thumb && t('image.none')}
      </div>
    )
  const blur = masksFor(page) === null && !revealed
  return (
    <div className={cn('relative', className)}>
      {children(blur)}
      {blur && !thumb && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-4 text-center">
          <p className="max-w-64 rounded-lg bg-background/90 p-3 text-sm shadow-sm">{t('image.blurred')}</p>
          <Button variant="outline" size="lg" onClick={() => setRevealed(true)}>
            <EyeIcon /> {t('image.show')}
          </Button>
        </div>
      )}
    </div>
  )
}

/** The full registry page with masks, optional field zones and a focused zone. */
export function PageImage({
  page,
  zones,
  focus,
  onZoneClick,
  className,
  thumb,
}: {
  page: Page
  zones?: Zone[]
  focus?: string
  onZoneClick?: (id: string) => void
  className?: string
  /** Small preview: no explanations, no buttons. */
  thumb?: boolean
}) {
  return (
    <Guard page={page} className={className} thumb={thumb}>
      {(blur) => (
        <div className="@container relative overflow-hidden rounded-lg bg-muted shadow-sm ring-1 ring-border" style={{ aspectRatio: `${page.imageSize[0]} / ${page.imageSize[1]}` }}>
          <img src={page.imageUrl} alt="" className={cn('absolute inset-0 size-full object-fill', blur && 'blur-xl')} draggable={false} />
          {!blur && <Overlay page={page} zones={zones} focus={focus} onZoneClick={onZoneClick} />}
        </div>
      )}
    </Guard>
  )
}

/**
 * Just the part of the page where a field is written, so the midwife compares
 * the handwriting and the AI's reading side by side without hunting.
 */
export function FieldCrop({ page, bbox, className }: { page: Page; bbox: BBox; className?: string }) {
  const [w, h] = page.imageSize
  const padX = (bbox[2] - bbox[0]) * 0.06 + 12
  const padY = (bbox[3] - bbox[1]) * 0.25 + 10
  const b: BBox = [Math.max(0, bbox[0] - padX), Math.max(0, bbox[1] - padY), Math.min(w, bbox[2] + padX), Math.min(h, bbox[3] + padY)]
  const bw = b[2] - b[0]
  const bh = b[3] - b[1]
  return (
    <Guard page={page} className={className}>
      {(blur) => (
        // Height capped (~9rem) so a tall table cell never pushes the answer buttons off screen.
        <div
          className="@container relative mx-auto w-full overflow-hidden rounded-md bg-white ring-1 ring-border"
          style={{ aspectRatio: `${bw} / ${bh}`, maxWidth: `${(bw / bh) * 9}rem` }}
        >
          <div
            className={cn('absolute', blur && 'blur-md')}
            style={{ width: pct(w, bw), height: pct(h, bh), left: `-${(b[0] / bw) * 100}%`, top: `-${(b[1] / bh) * 100}%` }}
          >
            <img src={page.imageUrl} alt="" className="absolute inset-0 size-full" draggable={false} />
            {!blur && <Overlay page={page} />}
          </div>
        </div>
      )}
    </Guard>
  )
}
