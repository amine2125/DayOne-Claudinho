import type { ReactNode } from 'react'
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useCan, type Permission } from '@/auth/roles'
import { AppShell } from '@/components/AppShell'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { DashboardScreen } from '@/screens/DashboardScreen'
import { HomeScreen } from '@/screens/HomeScreen'
import { PatientScreen } from '@/screens/PatientScreen'
import { PatientsScreen } from '@/screens/PatientsScreen'
import { PageScreen } from '@/screens/PageScreen'
import { SettingsScreen } from '@/screens/SettingsScreen'

/** Role gate: a screen the role cannot see sends to one it can. */
function Need({ permission, children }: { permission: Permission; children: ReactNode }) {
  const allowed = useCan(permission)
  const dashboard = useCan('dashboard')
  return allowed ? children : <Navigate to={dashboard ? '/dashboard' : '/settings'} replace />
}

export default function App() {
  return (
    <TooltipProvider>
      <HashRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Need permission="patient_profiles"><HomeScreen /></Need>} />
            <Route path="records/:id" element={<Need permission="patient_profiles"><PageScreen /></Need>} />
            {/* Older links from the patient page */}
            <Route path="records/:id/review" element={<Need permission="patient_profiles"><PageScreen /></Need>} />
            <Route path="patients" element={<Need permission="patient_profiles"><PatientsScreen /></Need>} />
            <Route path="patients/:id" element={<Need permission="patient_profiles"><PatientScreen /></Need>} />
            <Route path="dashboard" element={<Need permission="dashboard"><DashboardScreen /></Need>} />
            <Route path="settings" element={<SettingsScreen />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </HashRouter>
      <Toaster position="top-center" richColors />
    </TooltipProvider>
  )
}
