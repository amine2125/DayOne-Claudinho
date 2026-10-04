/**
 * Consistency alerts in the viewer's language. The API writes them in French (the WhatsApp agent
 * sends that text as is); English is rebuilt here from the alert code and its parameters.
 */
import type { FieldAlert } from '@/contract/types'
import type { T } from './index'

const MEASURES_EN: Record<string, string> = {
  weight: 'Weight', fundalHeight: 'Fundal height', fhr: 'FHR', temperature: 'Temperature', pulse: 'Pulse',
  hemoglobin: 'Haemoglobin', headCirc: 'Head circumference', length: 'Length', bp: 'BP', gaWeeks: 'Gestational age',
}

export function alertText(t: T, a: FieldAlert): string {
  if (t.lang === 'fr') return a.text
  const p = a.params
  const d = (k: string) => (typeof p[k] === 'string' ? t.date(String(p[k])) : String(p[k] ?? ''))
  const m = MEASURES_EN[String(p.measure)] ?? 'Value'
  const say: Record<string, () => string> = {
    format: () => `${m} ${p.value}: not a possible value for this field`,
    bp_order: () => `BP ${p.value}: the first number should be the larger one`,
    spike: () => `${m} ${p.value}: far from the visits before and after (${p.before} and ${p.after})`,
    date_order: () => `Visit on ${d('value')}: not after the previous visit (${d('previous')})`,
    future: () => `Date ${d('value')}: in the future`,
    appointment_before_visit: () => `Appointment ${d('value')}: before the visit of ${d('visit')}`,
    ga_lmp: () => `${p.value} wk read: the LMP (${d('lmp')}) and the visit date (${d('visit')}) give about ${p.expected} wk`,
    ga_dates: () => `${p.value} wk read: ${p.weeks} weeks after the visit at ${p.previous} wk`,
    edd_lmp: () => `Due date ${d('value')}: the LMP (${d('lmp')}) gives ${d('expected')}`,
    termDate_lmp: () => `Overdue date ${d('value')}: the LMP (${d('lmp')}) gives ${d('expected')}`,
    parity_gravidity: () => `Parity ${p.parity} greater than gravidity ${p.gravidity}`,
    obstetric_sum: () => `Parity ${p.parity} + abortions ${p.abortions} exceed gravidity ${p.gravidity}`,
    living_parity: () => `${p.living} living children for a parity of ${p.parity} (multiple births?)`,
    deliveries_parity: () => `${p.listed} previous deliveries described for a parity of ${p.parity}`,
    two_modes: () => 'Vaginal and caesarean both ticked',
    alive_stillborn: () => 'Alive and stillborn both ticked',
    birth_ga: () => `${p.value} wk at birth: the LMP (${d('lmp')}) and the delivery date give about ${p.expected} wk`,
  }
  return `${(say[a.code] ?? (() => a.text))()} — check on the paper.`
}
