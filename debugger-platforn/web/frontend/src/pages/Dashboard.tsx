import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { createSession, listSessions } from '../api/client'
import type { SessionSummary } from '../api/client'
import { useStore } from '../store'
import ProgressStepper from '../components/shared/ProgressStepper'
import type { CertificationReport, CertificationTier } from '../api/types'

const PHASE_KEYS = ['a', 'b', 'c', 'd', 'cert'] as const
const PHASE_LABELS: Record<string, string> = { a: 'A', b: 'B', c: 'C', d: 'D', cert: 'Cert' }

const TIER_COLORS: Record<string, { bg: string; text: string }> = {
  platinum: { bg: 'bg-blue-100', text: 'text-blue-700' },
  gold: { bg: 'bg-yellow-100', text: 'text-yellow-700' },
  silver: { bg: 'bg-gray-100', text: 'text-gray-700' },
  not_certified: { bg: 'bg-red-100', text: 'text-red-700' },
}

function TierPill({ tier }: { tier: CertificationTier }) {
  const c = TIER_COLORS[tier] || TIER_COLORS.not_certified
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${c.bg} ${c.text}`}>
      {tier.replace('_', ' ')}
    </span>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const setSessionId = useStore((s) => s.setSessionId)
  const sessionId = useStore((s) => s.sessionId)
  const hydrateSession = useStore((s) => s.hydrateSession)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    listSessions().then((res) => setSessions(res.sessions)).catch(() => {})
  }, [])

  const handleNewSession = async () => {
    setLoading(true)
    try {
      const session = await createSession()
      setSessionId(session.session_id)
      navigate('/phase-a')
    } catch (err) {
      console.error('Failed to create session:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleLoadSession = (s: SessionSummary) => {
    hydrateSession(
      s.session_id,
      s.phase_status || {},
      s.phase_results || {},
    )
    // Navigate to most advanced completed phase
    const order = ['cert', 'd', 'c', 'b', 'a']
    const routes: Record<string, string> = {
      cert: '/certification', d: '/phase-d', c: '/phase-c', b: '/phase-b', a: '/phase-a',
    }
    for (const p of order) {
      if (s.phases_completed.includes(p)) {
        navigate(routes[p])
        return
      }
    }
    navigate('/phase-a')
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Hero card */}
      <div className="bg-bg-card border border-border rounded-xl p-10 text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-pearl mb-3">
          Plavio Agent Debugger
        </h1>
        <p className="text-smoke mb-8 max-w-lg mx-auto text-sm leading-relaxed">
          Analyze agent codebases, generate comprehensive test suites, execute them
          with live monitoring, diagnose failures, and certify your agents.
        </p>

        {sessionId ? (
          <div className="space-y-5">
            <ProgressStepper />
            <button
              onClick={() => navigate('/phase-a')}
              className="px-6 py-3 bg-platinum text-bg rounded-lg font-medium hover:bg-pearl transition-colors duration-200"
            >
              Continue Session
            </button>
          </div>
        ) : (
          <button
            onClick={handleNewSession}
            disabled={loading}
            className="px-8 py-3 bg-platinum text-bg rounded-lg font-medium hover:bg-pearl transition-colors duration-200 disabled:opacity-50"
          >
            {loading ? 'Creating...' : 'Start New Debugging Session'}
          </button>
        )}
      </div>

      {/* Previous sessions */}
      {sessions.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-[11px] font-semibold text-text-muted uppercase tracking-widest">
            Saved Sessions ({sessions.length})
          </h2>
          <div className="grid gap-3">
            {sessions.map((s) => {
              const certResult = s.phase_results?.cert as unknown as CertificationReport | undefined
              const hasCert = s.phases_completed.includes('cert') && certResult
              const completedCount = s.phases_completed.length

              return (
                <div
                  key={s.session_id}
                  className="bg-bg-card border border-border rounded-xl hover:border-border-light transition-all duration-200 overflow-hidden group"
                >
                  <div className="flex items-center gap-4 p-4">
                    {/* Phase dots */}
                    <div className="flex gap-1">
                      {PHASE_KEYS.map((phase) => (
                        <span
                          key={phase}
                          className={`w-7 h-7 rounded-lg flex items-center justify-center text-[10px] font-bold transition-colors ${
                            s.phases_completed.includes(phase)
                              ? 'bg-pearl text-bg'
                              : 'bg-graphite text-text-muted'
                          }`}
                        >
                          {PHASE_LABELS[phase]}
                        </span>
                      ))}
                    </div>

                    {/* Session info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-mono text-pearl">{s.session_id}</span>
                        {hasCert && <TierPill tier={certResult.tier} />}
                      </div>
                      <div className="flex items-center gap-3 text-xs text-text-muted mt-0.5">
                        <span>{new Date(s.created_at).toLocaleString()}</span>
                        <span>{completedCount}/5 phases</span>
                        {hasCert && (
                          <span className="font-mono">Score: {certResult.overall_score.toFixed(1)}</span>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex gap-2 shrink-0">
                      <button
                        onClick={() => navigate(`/session/${s.session_id}`)}
                        className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-bg-card-hover text-text-dim transition-colors"
                      >
                        Overview
                      </button>
                      <button
                        onClick={() => handleLoadSession(s)}
                        className="px-3 py-1.5 text-xs bg-accent text-white rounded-lg hover:bg-accent/90 font-medium transition-colors"
                      >
                        Load
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
