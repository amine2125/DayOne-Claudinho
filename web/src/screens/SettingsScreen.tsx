import { RotateCcwIcon, ShieldCheckIcon } from 'lucide-react'
import { toast } from 'sonner'
import { LANGS, ROLES } from '@/contract/enums'
import { PageHeader } from '@/components/AppShell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api, useAppState } from '@/services'
import { useT, type TKey } from '@/i18n'
import { cn } from '@/lib/utils'

export function SettingsScreen() {
  const t = useT()
  const role = useAppState((s) => s.role)
  const lang = useAppState((s) => s.lang)
  const midwifeId = useAppState((s) => s.midwifeId)

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title={t('settings.title')} />
      <div className="flex flex-col gap-6 px-4 sm:px-6 lg:px-8">
        <section className="flex flex-col gap-3">
          <h2 className="font-bold">{t('settings.role')}</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            {ROLES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => api.setRole(r)}
                className={cn('flex flex-col gap-1 rounded-xl border-2 p-4 text-left', role === r ? 'border-primary bg-secondary' : 'bg-card hover:border-primary/40')}
              >
                <span className="font-semibold">{t(`settings.role.${r}`)}</span>
                <span className="text-sm text-muted-foreground">{t(`settings.roleHelp.${r}`)}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="font-bold">{t('settings.lang')}</h2>
          <div className="flex gap-3">
            {LANGS.map((l) => (
              <Button key={l} size="lg" variant={lang === l ? 'default' : 'outline'} className="h-12 px-6 text-base" onClick={() => api.setLang(l)}>
                {l === 'fr' ? 'Français' : 'English'}
              </Button>
            ))}
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <label htmlFor="mw" className="font-bold">
            {t('settings.midwifeId')}
          </label>
          <Input id="mw" value={midwifeId} onChange={(e) => api.setMidwifeId(e.target.value.toUpperCase())} className="font-code h-12 max-w-48 text-lg font-bold" />
        </section>

        <section className="flex flex-col gap-3 rounded-2xl border bg-card p-5">
          <h2 className="flex items-center gap-2 font-bold">
            <ShieldCheckIcon className="size-5 text-known" /> {t('settings.privacy')}
          </h2>
          <ul className="flex list-disc flex-col gap-1.5 pl-5 text-sm">
            {[1, 2, 3, 4].map((i) => (
              <li key={i}>{t(`settings.privacy.${i}` as TKey)}</li>
            ))}
          </ul>
        </section>

        <div>
          <Button
            variant="outline"
            onClick={() => {
              api.clearLocalSettings()
              toast.success(t('settings.resetDone'))
            }}
          >
            <RotateCcwIcon /> {t('settings.reset')}
          </Button>
        </div>
      </div>
    </div>
  )
}
