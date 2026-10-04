/**
 * Reference pages (schema/*.json): field labels, kinds and sections of the two registry pages
 * the team annotated. The reading itself has no template; the API files the fields it reads
 * under these keys and sections when the labels match, and keeps the others as read.
 */
import accouchement from '@schema/accouchement.json'
import identification from '@schema/identification_antecedents.json'
import type { PageType } from './enums'
import type { BBox, FieldValue } from './types'

export type FieldKind = 'integer' | 'text' | 'checkbox' | 'date' | 'weeks' | 'weight' | 'length' | 'sex'

export interface FieldDef {
  id: string
  label: string
  group: string
  kind: FieldKind
  zone?: number[]
  box?: number[]
  table?: boolean
}

interface SchemaFile {
  page_type: string
  title: string
  // Template-era keys, absent since the reading works without a template
  image_size?: number[]
  excluded_zones?: Record<string, number[]>
  fields: FieldDef[]
}

export interface PageSchema {
  pageType: PageType
  title: string
  imageSize: [number, number]
  /** Personal data zones: always masked when the image is shown. */
  excludedZones: BBox[]
  fields: FieldDef[]
  sections: { id: string; fields: FieldDef[] }[]
}

function build(raw: SchemaFile): PageSchema {
  const sections: PageSchema['sections'] = []
  for (const f of raw.fields) {
    const s = sections.find((x) => x.id === f.group) ?? sections[sections.push({ id: f.group, fields: [] }) - 1]
    s.fields.push(f as FieldDef)
  }
  return {
    pageType: raw.page_type as PageType,
    title: raw.title,
    imageSize: raw.image_size ? [raw.image_size[0], raw.image_size[1]] : [0, 0],
    excludedZones: Object.values(raw.excluded_zones ?? {}).map((z) => z as BBox),
    fields: raw.fields as FieldDef[],
    sections,
  }
}

export const SCHEMAS: Partial<Record<PageType, PageSchema>> = {
  identification_antecedents: build(identification as SchemaFile),
  accouchement: build(accouchement as SchemaFile),
}

/** Pages with a reference schema. Any page can be read; only these get reference sections. */
export function isReadable(pageType: PageType): boolean {
  return pageType in SCHEMAS
}

export function fieldDef(pageType: PageType, key: string): FieldDef | undefined {
  return SCHEMAS[pageType]?.fields.find((f) => f.id === key)
}

/** Where the field sits on the page. Checkboxes get a wider box so their printed label is visible too. */
export function fieldBBox(def: FieldDef): BBox | undefined {
  if (def.zone) return def.zone as BBox
  if (def.box) {
    const [cx, cy, s] = def.box
    return [cx - s * 1.5, cy - s * 1.6, cx + s * 14, cy + s * 1.6]
  }
  return undefined
}

/** Fields shown in the patient summary card ("at a glance"), in this order. */
export const SUMMARY_FIELDS: { pageType: PageType; key: string }[] = [
  { pageType: 'identification_antecedents', key: 'age' },
  { pageType: 'identification_antecedents', key: 'gestation' },
  { pageType: 'identification_antecedents', key: 'parite' },
  { pageType: 'identification_antecedents', key: 'enfants_vivants' },
  { pageType: 'accouchement', key: 'date_accouchement' },
  { pageType: 'accouchement', key: 'nn_poids' },
  { pageType: 'accouchement', key: 'nn_sexe' },
]

/** Sections whose written entries are surfaced as "noted on the registry". Facts only, no clinical logic. */
export const NOTED_SECTIONS = [
  'Antécédents héréditaires et familiaux',
  'Antécédents de la femme',
  'Antécédents obstétricaux',
  'Complications',
]
/** Written words that mean "nothing to report" on the paper. */
const NOTHING_TO_REPORT = /^(ras|aucun|aucune|néant|neant|rien|normal|non|-|0)$/i

export function isNoteworthy(value: FieldValue): boolean {
  if (value === null || value === false) return false
  if (value === true) return true
  return !NOTHING_TO_REPORT.test(String(value).trim())
}
