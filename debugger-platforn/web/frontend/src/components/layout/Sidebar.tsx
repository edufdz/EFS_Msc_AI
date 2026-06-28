import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useStore } from '../../store'
import { saveSession } from '../../api/client'

const phases = [
  { key: 'a' as const, label: 'Phase A', sub: 'Analyze', path: '/phase-a' },
  { key: 'b' as const, label: 'Phase B', sub: 'Generate Tests', path: '/phase-b' },
  { key: 'c' as const, label: 'Phase C', sub: 'Execute', path: '/phase-c' },
  { key: 'd' as const, label: 'Phase D', sub: 'Diagnose', path: '/phase-d' },
  { key: 'cert' as const, label: 'Certification', sub: 'Score & Certify', path: '/certification' },
]

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed')
    return <span className="w-5 h-5 rounded-full bg-pearl flex items-center justify-center text-[10px] text-bg font-bold">&#10003;</span>
  if (status === 'running')
    return <span className="w-5 h-5 rounded-full bg-accent animate-pulse-soft flex items-center justify-center text-[10px] text-bg font-bold">&#9654;</span>
  if (status === 'error')
    return <span className="w-5 h-5 rounded-full bg-text-muted flex items-center justify-center text-[10px] text-bg font-bold">!</span>
  return <span className="w-5 h-5 rounded-full bg-border flex items-center justify-center text-[10px] text-text-muted">&#8226;</span>
}

export default function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const phaseA = useStore((s) => s.phaseA)
  const phaseB = useStore((s) => s.phaseB)
  const phaseC = useStore((s) => s.phaseC)
  const phaseD = useStore((s) => s.phaseD)
  const certStatus = useStore((s) => s.certStatus)
  const sessionId = useStore((s) => s.sessionId)
  const resetSession = useStore((s) => s.resetSession)

  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle')

  const statuses = { a: phaseA, b: phaseB, c: phaseC, d: phaseD, cert: certStatus }

  const hasAnyCompleted = Object.values(statuses).some((s) => s === 'completed')

  const handleSave = async () => {
    if (!sessionId) return
    setSaveState('saving')
    try {
      await saveSession(sessionId)
      setSaveState('saved')
      setTimeout(() => setSaveState('idle'), 2500)
    } catch {
      setSaveState('idle')
    }
  }

  return (
    <aside className="w-[260px] min-w-[260px] bg-bg-surface border-r border-border flex flex-col">
      {/* Logo area */}
      <div
        className="px-5 py-4 border-b border-border cursor-pointer"
        onClick={() => navigate('/')}
      >
        <h1 className="text-lg font-semibold tracking-tight text-pearl">Plavio</h1>
        <p className="text-[11px] text-text-muted mt-0.5 uppercase tracking-wider">Trust your AI workforce</p>
      </div>

      {/* Phase stepper */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {phases.map((p, i) => {
          const isActive = location.pathname === p.path
          const status = statuses[p.key]
          return (
            <div key={p.key}>
              <button
                onClick={() => navigate(p.path)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-all duration-200 ${
                  isActive
                    ? 'bg-graphite/50 text-pearl'
                    : 'text-text-dim hover:bg-bg-card hover:text-text-primary'
                }`}
              >
                <StatusIcon status={status} />
                <div>
                  <div className="text-sm font-medium">{p.label}</div>
                  <div className="text-[11px] text-text-muted">{p.sub}</div>
                </div>
              </button>
              {/* Connector line between phases */}
              {i < phases.length - 1 && (
                <div className="ml-[22px] h-4 border-l border-border" />
              )}
            </div>
          )
        })}
      </nav>

      {/* Bottom actions */}
      <div className="px-3 pb-4 space-y-2">
        {sessionId && hasAnyCompleted && (
          <button
            onClick={handleSave}
            disabled={saveState === 'saving'}
            className={`w-full px-3 py-2 text-sm border rounded-lg transition-all duration-200 ${
              saveState === 'saved'
                ? 'bg-green-50 border-green-200 text-green-700'
                : 'border-border hover:bg-bg-card text-text-dim hover:text-text-primary'
            }`}
          >
            {saveState === 'saved' ? 'Session Saved' : saveState === 'saving' ? 'Saving...' : 'Save Session'}
          </button>
        )}
        {sessionId && (
          <button
            onClick={() => {
              resetSession()
              navigate('/')
            }}
            className="w-full px-3 py-2 text-sm text-text-dim border border-border rounded-lg hover:bg-bg-card hover:text-text-primary transition-all duration-200"
          >
            New Session
          </button>
        )}
      </div>
    </aside>
  )
}
