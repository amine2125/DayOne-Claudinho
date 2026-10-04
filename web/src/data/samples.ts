/**
 * Demo material: real pipeline outputs (outputs/predictions) and the matching
 * specimen pages. Only the dev split (patients 1–8) is used; patients 9–10 are
 * the locked test set and are never bundled.
 */
import { PAGE_TYPES, type FieldStatus, type PageType } from '@/contract/enums'
import type { FieldValue } from '@/contract/types'

export interface PredictedField {
  value: FieldValue
  status: FieldStatus
  confidence: number
  source?: string
}
export interface Sample {
  id: string
  pageNumber: number | null
  patient: number | null // fictitious patient number in the specimen
  pageType: PageType
  imageUrl: string
  imageSize: [number, number]
  /** Null when the pipeline cannot read the page (unknown layout). */
  fields: Record<string, PredictedField> | null
}

const predictions = import.meta.glob<{ fields: Record<string, PredictedField> }>('@predictions/*.json', {
  eager: true,
  import: 'default',
})

function prediction(page: number, pageType: PageType) {
  const name = `page_${String(page).padStart(2, '0')}_${pageType}.json`
  const hit = Object.entries(predictions).find(([path]) => path.endsWith(name))
  return hit ? hit[1].fields : null
}

// Explicit list: Vite bundles only these files (never the locked test pages).
const URLS = import.meta.glob<string>(
  [
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-02.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-04.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-05.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-06.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-07__1O_M-H0E7z.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-08.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-10__1U_S1pqftP.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-12__1D4u3zWyes.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-13.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-14__1NRsJ9Ddo8.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-15__1NMe1Ym5MK.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-16__1CB60L7TiS.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-18__1YDapV3RjJ.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-20__18kYVBTwE4.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-21__1YGNHKDIuK.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-22.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-23__1M0bYiZmc7.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-24__11w0IP6pSn.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-26__17ANHGh7D9.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-28__1OtF9rNsnr.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-29__1IIeCj5Sjq.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-30__1MEUrnbu5W.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-31__1Nue3NqAua.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-32__1Bx-67ocGy.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-34__1-TNB7bUpy.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-36__10YoYqH4k6.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-37__1ClQJtts9I.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-38__1CXcCUFyrj.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-39__17KgDI_D25.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-40__1WnbGI6FRA.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-42__1RrCOGAZgm.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-44__1XxzcLjCYe.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-45__1CU3r5Tdou.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-46__13tFG11aaA.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-47__1IUs1h6KZQ.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-48__1JY9DkRr_Z.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-50__1JrJI1k9zk.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-52__13GPlkmxU-.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-53__1Djbws5jOt.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-54__155-coOlhB.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-55__1t5UQZZmWv.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-56__14R5jqMZgt.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-58.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-60.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-61.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-62.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-63.png',
    '../../../data/Paper Registry/dossiers_specimen_10_patientes-64.png',
    '../../../data/Paper Registry/1-1.jpg',
  ],
  { eager: true, query: '?url', import: 'default' },
)
const url = (name: string) => {
  const hit = Object.entries(URLS).find(([path]) => path.endsWith(`/${name}`))
  if (!hit) throw new Error(`missing image ${name}`)
  return hit[1]
}
const IMAGES: Record<number, string> = {
  2: url('dossiers_specimen_10_patientes-02.png'),
  4: url('dossiers_specimen_10_patientes-04.png'),
  5: url('dossiers_specimen_10_patientes-05.png'),
  6: url('dossiers_specimen_10_patientes-06.png'),
  7: url('dossiers_specimen_10_patientes-07__1O_M-H0E7z.png'),
  8: url('dossiers_specimen_10_patientes-08.png'),
  10: url('dossiers_specimen_10_patientes-10__1U_S1pqftP.png'),
  12: url('dossiers_specimen_10_patientes-12__1D4u3zWyes.png'),
  13: url('dossiers_specimen_10_patientes-13.png'),
  14: url('dossiers_specimen_10_patientes-14__1NRsJ9Ddo8.png'),
  15: url('dossiers_specimen_10_patientes-15__1NMe1Ym5MK.png'),
  16: url('dossiers_specimen_10_patientes-16__1CB60L7TiS.png'),
  18: url('dossiers_specimen_10_patientes-18__1YDapV3RjJ.png'),
  20: url('dossiers_specimen_10_patientes-20__18kYVBTwE4.png'),
  21: url('dossiers_specimen_10_patientes-21__1YGNHKDIuK.png'),
  22: url('dossiers_specimen_10_patientes-22.png'),
  23: url('dossiers_specimen_10_patientes-23__1M0bYiZmc7.png'),
  24: url('dossiers_specimen_10_patientes-24__11w0IP6pSn.png'),
  26: url('dossiers_specimen_10_patientes-26__17ANHGh7D9.png'),
  28: url('dossiers_specimen_10_patientes-28__1OtF9rNsnr.png'),
  29: url('dossiers_specimen_10_patientes-29__1IIeCj5Sjq.png'),
  30: url('dossiers_specimen_10_patientes-30__1MEUrnbu5W.png'),
  31: url('dossiers_specimen_10_patientes-31__1Nue3NqAua.png'),
  32: url('dossiers_specimen_10_patientes-32__1Bx-67ocGy.png'),
  34: url('dossiers_specimen_10_patientes-34__1-TNB7bUpy.png'),
  36: url('dossiers_specimen_10_patientes-36__10YoYqH4k6.png'),
  37: url('dossiers_specimen_10_patientes-37__1ClQJtts9I.png'),
  38: url('dossiers_specimen_10_patientes-38__1CXcCUFyrj.png'),
  39: url('dossiers_specimen_10_patientes-39__17KgDI_D25.png'),
  40: url('dossiers_specimen_10_patientes-40__1WnbGI6FRA.png'),
  42: url('dossiers_specimen_10_patientes-42__1RrCOGAZgm.png'),
  44: url('dossiers_specimen_10_patientes-44__1XxzcLjCYe.png'),
  45: url('dossiers_specimen_10_patientes-45__1CU3r5Tdou.png'),
  46: url('dossiers_specimen_10_patientes-46__13tFG11aaA.png'),
  47: url('dossiers_specimen_10_patientes-47__1IUs1h6KZQ.png'),
  48: url('dossiers_specimen_10_patientes-48__1JY9DkRr_Z.png'),
  50: url('dossiers_specimen_10_patientes-50__1JrJI1k9zk.png'),
  52: url('dossiers_specimen_10_patientes-52__13GPlkmxU-.png'),
  53: url('dossiers_specimen_10_patientes-53__1Djbws5jOt.png'),
  54: url('dossiers_specimen_10_patientes-54__155-coOlhB.png'),
  55: url('dossiers_specimen_10_patientes-55__1t5UQZZmWv.png'),
  56: url('dossiers_specimen_10_patientes-56__14R5jqMZgt.png'),
  58: url('dossiers_specimen_10_patientes-58.png'),
  60: url('dossiers_specimen_10_patientes-60.png'),
  61: url('dossiers_specimen_10_patientes-61.png'),
  62: url('dossiers_specimen_10_patientes-62.png'),
  63: url('dossiers_specimen_10_patientes-63.png'),
  64: url('dossiers_specimen_10_patientes-64.png'),
}
const FIELD_PHOTO = url('1-1.jpg')

const SPECIMEN: Sample[] = Object.entries(IMAGES).map(([n, imageUrl]) => {
  const page = Number(n)
  // The specimen booklet repeats the same 8 pages for each fictitious patient.
  const pageType = PAGE_TYPES[(page - 1) % 8]
  return {
    id: `page_${String(page).padStart(2, '0')}`,
    pageNumber: page,
    patient: Math.floor((page - 1) / 8) + 1,
    pageType,
    imageUrl,
    imageSize: [1654, 2339] as [number, number],
    fields: prediction(page, pageType),
  }
})

export const SAMPLES: Sample[] = [
  ...SPECIMEN,
  {
    id: 'photo_1',
    pageNumber: null,
    patient: null,
    pageType: 'identification_antecedents',
    imageUrl: FIELD_PHOTO,
    imageSize: [900, 1600],
    fields: null, // real photo with another layout: the template cannot be aligned
  },
]

export function sample(id: string): Sample {
  const s = SAMPLES.find((x) => x.id === id)
  if (!s) throw new Error(`unknown sample ${id}`)
  return s
}
