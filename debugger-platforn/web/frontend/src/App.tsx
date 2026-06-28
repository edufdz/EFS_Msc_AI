import { Routes, Route, Navigate } from 'react-router-dom'
import AppShell from './components/layout/AppShell'
import Dashboard from './pages/Dashboard'
import PhaseA from './pages/PhaseA'
import PhaseB from './pages/PhaseB'
import PhaseC from './pages/PhaseC'
import PhaseD from './pages/PhaseD'
import Certification from './pages/Certification'
import SessionOverview from './pages/SessionOverview'

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/session/:id" element={<SessionOverview />} />
        <Route path="/phase-a" element={<PhaseA />} />
        <Route path="/phase-b" element={<PhaseB />} />
        <Route path="/phase-c" element={<PhaseC />} />
        <Route path="/phase-d" element={<PhaseD />} />
        <Route path="/certification" element={<Certification />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}
