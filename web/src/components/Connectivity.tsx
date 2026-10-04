import { CloudOffIcon, LoaderIcon, WifiIcon, WifiOffIcon } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api, useAppState, useWaitingCount } from '@/services'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'

/** Backend reachable or not + how many records are waiting. Clicking it refreshes now. */
export function ConnectivityToggle({ className }: { className?: string }) {
  const t = useT()
  const online = useAppState((s) => s.online)
  const busy = useAppState((s) => s.busy.length > 0)
  const waiting = useWaitingCount()
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            onClick={() => void api.refresh()}
            className={cn(
              'inline-flex h-10 items-center gap-2 rounded-full border-2 px-3.5 text-sm font-semibold whitespace-nowrap transition-colors',
              online ? 'border-known/30 bg-known-soft text-known' : 'border-review/40 bg-review-soft text-review',
              className,
            )}
          />
        }
      >
        {busy ? <LoaderIcon className="size-4 animate-spin" /> : online ? <WifiIcon className="size-4" /> : <WifiOffIcon className="size-4" />}
        {online ? t('net.online') : t('net.offline')}
        {waiting > 0 && (
          <span className="rounded-full bg-background/80 px-2 py-0.5 text-xs text-foreground">
            <span className="sm:hidden">{waiting}</span>
            <span className="hidden sm:inline">{t('net.waiting', { n: waiting })}</span>
          </span>
        )}
      </TooltipTrigger>
      <TooltipContent>{t('net.refresh')}</TooltipContent>
    </Tooltip>
  )
}

/** Band shown while the backend is unreachable, or while it reads a photo. */
export function ConnectivityBanner() {
  const t = useT()
  const online = useAppState((s) => s.online)
  const busy = useAppState((s) => s.busy.length > 0)
  if (online && !busy) return null
  return (
    <div
      role="status"
      className={cn('flex items-center gap-3 px-4 py-2.5 text-sm sm:px-6', online ? 'bg-info-soft text-info' : 'bg-review-soft text-foreground')}
    >
      {online ? <LoaderIcon className="size-4 shrink-0 animate-spin" /> : <CloudOffIcon className="size-4 shrink-0 text-review" />}
      <span>
        {online ? (
          t('net.banner.syncing')
        ) : (
          <>
            <strong>{t('net.banner.offline')}</strong> {t('net.banner.offlineHint')}
          </>
        )}
      </span>
    </div>
  )
}
