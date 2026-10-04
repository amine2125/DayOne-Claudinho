import { useCallback } from 'react'
import type { Lang, PageType } from '@/contract/enums'
import { fieldDef, type FieldKind } from '@/contract/registry'
import type { FieldValue, Page } from '@/contract/types'
import { useAppState } from '@/services'
import { en } from './en'
import { FIELDS_EN, SECTIONS_EN } from './fields.en'
import { fr, type Dict } from './fr'

export type TKey = keyof Dict
const DICTS: Record<Lang, Dict> = { fr, en }

export type T = ReturnType<typeof useT>

export function useT() {
  const lang = useAppState((s) => s.lang)
  const t = useCallback(
    (key: TKey, vars?: Record<string, string | number>) =>
      DICTS[lang][key].replace(/\{(\w+)\}/g, (_, k: string) => String(vars?.[k] ?? `{${k}}`)),
    [lang],
  )
  return Object.assign(t, {
    lang,
    /** English label for reference fields; otherwise the label read on the page. */
    field: (pageType: PageType, key: string, label?: string) =>
      (lang === 'en' ? FIELDS_EN[key] : undefined) ?? label ?? fieldDef(pageType, key)?.label ?? key,
    /** Page name: its reference type, or the title read on it. */
    page: (p: Pick<Page, 'pageType' | 'title'>) =>
      p.pageType === 'unknown' && p.title ? p.title : DICTS[lang][`page.${p.pageType}` as TKey],
    section: (id: string) => (lang === 'en' ? SECTIONS_EN[id] : undefined) ?? id,
    date: (iso: string | undefined, withTime = false) => {
      if (!iso) return '—'
      const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
      if (Number.isNaN(d.getTime())) return iso
      return d.toLocaleDateString(lang === 'fr' ? 'fr-FR' : 'en-GB', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
      })
    },
    relative: (iso: string) => {
      const rtf = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' })
      const hours = Math.floor((Date.now() - new Date(iso).getTime()) / 36e5)
      if (hours < 1) return rtf.format(0, 'minute')
      if (hours < 24) return rtf.format(-hours, 'hour')
      const days = Math.floor(hours / 24)
      if (days < 45) return rtf.format(-days, 'day')
      return rtf.format(-Math.round(days / 30), 'month')
    },
  })
}

/** A field value in words a midwife reads at a glance, with units. */
export function formatValue(t: T, kind: FieldKind | undefined, value: FieldValue): string {
  if (value === null || value === '') return t('value.empty')
  if (typeof value === 'boolean') return t(value ? 'value.checked' : 'value.unchecked')
  switch (kind) {
    case 'date':
      return t.date(String(value))
    case 'weeks':
      return `${value} ${t.lang === 'fr' ? 'SA' : 'wk'}`
    case 'weight':
      // The reading keeps weights in grams; a mother's weight reads better in kg.
      return typeof value === 'number' && value >= 10_000
        ? `${(value / 1000).toLocaleString(t.lang === 'fr' ? 'fr-FR' : 'en-GB', { maximumFractionDigits: 1 })} kg`
        : `${value} g`
    case 'length':
      return `${value} cm`
    case 'sex':
      return value === 'F' ? t('value.F') : value === 'M' ? t('value.M') : String(value)
    default:
      return String(value)
  }
}
