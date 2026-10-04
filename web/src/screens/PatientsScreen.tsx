import { ChevronRightIcon, SearchIcon, ShieldCheckIcon } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/AppShell'
import { PatientCode } from '@/components/PatientCode'
import { Input } from '@/components/ui/input'
import { lastVisitDate, latestFields, useAppState, usePatients } from '@/services'
import { codeDistance, normalizeCode } from '@/services/linking'
import { useT } from '@/i18n'

export function PatientsScreen() {
  const t = useT()
  const patients = usePatients()
  const state = useAppState((s) => s)
  const [q, setQ] = useState('')
  const shown = q ? patients.filter((p) => normalizeCode(p.code).includes(normalizeCode(q)) || codeDistance(p.code, q) <= 1) : patients

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title={t('patients.title')}
        subtitle={
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheckIcon className="size-4 text-known" /> {t('patients.subtitle')}
          </span>
        }
      />
      <div className="flex flex-col gap-4 px-4 sm:px-6 lg:px-8">
        <div className="relative">
          <SearchIcon className="absolute top-1/2 left-4 size-5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value.toUpperCase())}
            placeholder={t('patients.search')}
            className="font-code h-14 pl-12 text-xl font-bold placeholder:font-sans placeholder:font-normal"
          />
        </div>
        <ul className="flex flex-col divide-y rounded-2xl border bg-card">
          {shown.length === 0 && <li className="p-6 text-center text-muted-foreground">{t('patients.empty')}</li>}
          {shown.map((p) => {
            const f = latestFields(state, p)
            const age = f['identification_antecedents.age']?.value
            const g = f['identification_antecedents.gestation']?.value
            const par = f['identification_antecedents.parite']?.value
            return (
              <li key={p.id}>
                <Link to={`/patients/${p.id}`} className="flex items-center gap-4 px-4 py-4 hover:bg-muted/60">
                  <PatientCode code={p.code} size="lg" className="w-32 shrink-0" />
                  <span className="flex min-w-0 flex-1 flex-wrap gap-x-4 gap-y-1 text-sm">
                    {typeof age === 'number' && <span>{t('patient.age', { n: age })}</span>}
                    {g != null && <span className="font-code">{t('patient.gp', { g: String(g), p: par == null ? '?' : String(par) })}</span>}
                    <span className="text-muted-foreground">{t('link.visits', { n: p.visitIds.length })}</span>
                    <span className="text-muted-foreground">{t('link.lastVisit', { date: t.date(lastVisitDate(state, p)) })}</span>
                  </span>
                  <ChevronRightIcon className="size-5 text-muted-foreground" />
                </Link>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
