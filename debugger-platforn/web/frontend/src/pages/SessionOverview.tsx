import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getSession, saveSession } from '../api/client'
import type { SessionSummary } from '../api/client'
import { useStore } from '../store'
import type {
  PhaseAResult,
  PhaseBResult,
  PhaseCResult,
  PhaseDResult,
  CertificationReport,
  CertificationTier,
} from '../api/types'
import TierBadge from '../components/certification/TierBadge'

const PHASE_META = [
  { key: 'a', label: 'Phase A', sub: 'Agent Analysis', icon: 'M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2' },
  { key: 'b', label: 'Phase B', sub: 'Test Generation', icon: 'M12 6v6l4 2M22 12A10 10 0 1 1 2 12a10 10 0 0 1 20 0z' },
  { key: 'c', label: 'Phase C', sub: 'Execution', icon: 'M13 2L3 14h9l-1 10 10-12h-9l1-10z' },
  { key: 'd', label: 'Phase D', sub: 'Diagnosis', icon: 'M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z' },
  { key: 'cert', label: 'Certification', sub: 'Score & Certify', icon: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' },
]

function PhaseIcon({ path }: { path: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  )
}

function StatusDot({ status }: { status: string }) {
  if (status === 'completed') return <span className="w-2.5 h-2.5 rounded-full bg-green-500" />
  if (status === 'error') return <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
  return <span className="w-2.5 h-2.5 rounded-full bg-border" />
}

function PhaseACard({ result }: { result: PhaseAResult }) {
  return (
    <div className="grid grid-cols-3 gap-3 text-sm">
      <div>
        <div className="text-text-muted text-xs">Framework</div>
        <div className="font-medium text-pearl">{result.framework}</div>
        <div className="text-xs text-text-muted">{(result.framework_confidence * 100).toFixed(0)}% confidence</div>
      </div>
      <div>
        <div className="text-text-muted text-xs">Tools Found</div>
        <div className="font-mono font-bold text-pearl text-lg">{result.tools_count}</div>
      </div>
      <div>
        <div className="text-text-muted text-xs">Risks Identified</div>
        <div className={`font-mono font-bold text-lg ${result.risks_count > 0 ? 'text-yellow-600' : 'text-green-600'}`}>{result.risks_count}</div>
      </div>
    </div>
  )
}

function PhaseBCard({ result }: { result: PhaseBResult }) {
  return (
    <div className="grid grid-cols-3 gap-3 text-sm">
      <div>
        <div className="text-text-muted text-xs">Tests Generated</div>
        <div className="font-mono font-bold text-pearl text-lg">{result.total_tests}</div>
      </div>
      <div>
        <div className="text-text-muted text-xs">Personas</div>
        <div className="font-mono font-bold text-pearl text-lg">{result.persona_count}</div>
      </div>
      <div>
        <div className="text-text-muted text-xs">Scenarios</div>
        <div className="font-mono font-bold text-pearl text-lg">{result.scenario_count}</div>
      </div>
    </div>
  )
}

function PhaseCCard({ result }: { result: PhaseCResult }) {
  const passColor = result.pass_rate >= 85 ? 'text-green-600' : result.pass_rate >= 70 ? 'text-yellow-600' : 'text-red-600'
  return (
    <div className="grid grid-cols-4 gap-3 text-sm">
      <div>
        <div className="text-text-muted text-xs">Pass Rate</div>
        <div className={`font-mono font-bold text-lg ${passColor}`}>{(result.pass_rate * 100).toFixed(1)}%</div>
      </div>
      <div>
        <div className="text-text-muted text-xs">Tests Run</div>
        <div className="font-mono text-pearl">{result.passed}/{result.total_tests} passed</div>
      </div>
      <div>
        <div className="text-text-muted text-xs">Tool Coverage</div>
        <div className="font-mono text-pearl">{result.tool_coverage_pct.toFixed(0)}%</div>
      </div>
      <div>
        <div className="text-text-muted text-xs">Cost</div>
        <div className="font-mono text-pearl">${result.total_cost_usd.toFixed(2)}</div>
      </div>
    </div>
  )
}

function PhaseDCard({ result }: { result: PhaseDResult }) {
  return (
    <div className="grid grid-cols-3 gap-3 text-sm">
      <div>
        <div className="text-text-muted text-xs">Failure Clusters</div>
        <div className="font-mono font-bold text-pearl text-lg">{result.clusters_found}</div>
      </div>
      <div>
        <div className="text-text-muted text-xs">Fix Proposals</div>
        <div className="font-mono font-bold text-pearl text-lg">{result.fix_proposals.length}</div>
      </div>
      <div>
        <div className="text-text-muted text-xs">Failures Analyzed</div>
        <div className="font-mono text-pearl">{result.total_failures}</div>
      </div>
    </div>
  )
}

function CertCard({ result }: { result: CertificationReport }) {
  return (
    <div className="flex items-center gap-6">
      <TierBadge tier={result.tier} score={result.overall_score} size={100} animated={false} />
      <div className="flex-1 space-y-2">
        <div className="grid grid-cols-3 gap-3 text-sm">
          <div>
            <div className="text-text-muted text-xs">Agent</div>
            <div className="font-medium text-pearl">{result.agent_name}</div>
          </div>
          <div>
            <div className="text-text-muted text-xs">Framework</div>
            <div className="text-pearl">{result.agent_framework}</div>
          </div>
          <div>
            <div className="text-text-muted text-xs">Simulations</div>
            <div className="font-mono text-pearl">{result.testing_conditions.total_simulations}</div>
          </div>
        </div>
        {result.strengths.length > 0 && (
          <div className="text-xs text-green-600">
            {result.strengths.slice(0, 2).join(' | ')}
          </div>
        )}
      </div>
    </div>
  )
}

export default function SessionOverview() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const hydrateSession = useStore((s) => s.hydrateSession)
  const [session, setSession] = useState<SessionSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    getSession(id)
      .then(setSession)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [id])

  const handleLoadSession = () => {
    if (!session) return
    hydrateSession(
      session.session_id,
      session.phase_status || {},
      session.phase_results || {},
    )
    // Navigate to the most advanced completed phase
    const order = ['cert', 'd', 'c', 'b', 'a']
    const routes: Record<string, string> = {
      cert: '/certification', d: '/phase-d', c: '/phase-c', b: '/phase-b', a: '/phase-a',
    }
    for (const p of order) {
      if (session.phases_completed.includes(p)) {
        navigate(routes[p])
        return
      }
    }
    navigate('/phase-a')
  }

  const handleSave = async () => {
    if (!id) return
    setSaving(true)
    try {
      await saveSession(id)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch {
      // ignore
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="text-text-muted">Loading session...</div>
      </div>
    )
  }

  if (!session) {
    return (
      <div className="max-w-4xl mx-auto p-6 space-y-4">
        <div className="text-red-600">Session not found</div>
        <button onClick={() => navigate('/')} className="text-accent hover:underline text-sm">
          Back to Dashboard
        </button>
      </div>
    )
  }

  const results = session.phase_results || {}
  const statuses = session.phase_status || {}
  const certResult = results.cert as unknown as CertificationReport | undefined

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button onClick={() => navigate('/')} className="text-xs text-text-muted hover:text-accent mb-1 block">
            &larr; Back to Dashboard
          </button>
          <h2 className="text-2xl font-semibold text-pearl">Session Overview</h2>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-sm font-mono text-text-dim">{session.session_id}</span>
            <span className="text-xs text-text-muted">
              {new Date(session.created_at).toLocaleString()}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={handleSave}
            className={`px-4 py-2 text-sm border rounded-lg transition-colors ${
              saved
                ? 'bg-green-50 border-green-200 text-green-700'
                : 'border-border hover:bg-bg-card text-text-dim'
            }`}
            disabled={saving}
          >
            {saved ? 'Saved!' : saving ? 'Saving...' : 'Save Session'}
          </button>
          <button onClick={handleLoadSession}
            className="px-4 py-2 text-sm bg-accent text-white rounded-lg hover:bg-accent/90 font-medium transition-colors">
            Load & Continue
          </button>
        </div>
      </div>

      {/* Cert badge hero (if certified) */}
      {certResult && certResult.tier && (
        <div className="flex items-center gap-6 p-6 bg-bg-surface border border-border rounded-xl">
          <TierBadge tier={certResult.tier as CertificationTier} score={certResult.overall_score} size={120} animated={false} />
          <div>
            <div className="text-sm text-text-muted">Certification Result</div>
            <div className="text-2xl font-bold text-pearl">{certResult.agent_name}</div>
            <div className="text-sm text-text-dim mt-1">
              Score: {certResult.overall_score.toFixed(1)} / 100
            </div>
          </div>
        </div>
      )}

      {/* Phase timeline */}
      <div className="space-y-2">
        {PHASE_META.map((phase, i) => {
          const status = statuses[phase.key] || 'idle'
          const result = results[phase.key]
          const isCompleted = status === 'completed'
          const isExpanded = expanded === phase.key

          return (
            <div key={phase.key}>
              <button
                onClick={() => setExpanded(isExpanded ? null : (isCompleted ? phase.key : null))}
                className={`w-full flex items-center gap-4 p-4 rounded-xl border transition-all text-left ${
                  isCompleted
                    ? 'bg-bg-surface border-border hover:border-border-light cursor-pointer'
                    : 'bg-bg-card/50 border-border/50 opacity-60 cursor-default'
                } ${isExpanded ? 'border-accent/30 bg-bg-surface' : ''}`}
              >
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
                  isCompleted ? 'bg-green-50 text-green-600' : 'bg-bg-card text-text-muted'
                }`}>
                  <PhaseIcon path={phase.icon} />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-pearl">{phase.label}</span>
                    <span className="text-xs text-text-muted">{phase.sub}</span>
                  </div>
                  {isCompleted && result && phase.key === 'a' && (
                    <div className="text-xs text-text-dim mt-0.5">
                      {(result as unknown as PhaseAResult).framework} — {(result as unknown as PhaseAResult).tools_count} tools
                    </div>
                  )}
                  {isCompleted && result && phase.key === 'c' && (
                    <div className="text-xs text-text-dim mt-0.5">
                      {((result as unknown as PhaseCResult).pass_rate * 100).toFixed(1)}% pass rate — {(result as unknown as PhaseCResult).total_tests} tests
                    </div>
                  )}
                  {isCompleted && result && phase.key === 'cert' && (
                    <div className="text-xs text-text-dim mt-0.5">
                      {(result as unknown as CertificationReport).tier.replace('_', ' ')} — {(result as unknown as CertificationReport).overall_score.toFixed(1)} score
                    </div>
                  )}
                </div>

                <StatusDot status={status} />

                {isCompleted && (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    className={`text-text-muted transition-transform ${isExpanded ? 'rotate-180' : ''}`}>
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                )}
              </button>

              {/* Expanded detail */}
              {isExpanded && result && (
                <div className="mx-4 mt-1 mb-2 p-4 bg-white border border-border rounded-lg animate-slide-in">
                  {phase.key === 'a' && <PhaseACard result={result as unknown as PhaseAResult} />}
                  {phase.key === 'b' && <PhaseBCard result={result as unknown as PhaseBResult} />}
                  {phase.key === 'c' && <PhaseCCard result={result as unknown as PhaseCResult} />}
                  {phase.key === 'd' && <PhaseDCard result={result as unknown as PhaseDResult} />}
                  {phase.key === 'cert' && <CertCard result={result as unknown as CertificationReport} />}

                  <div className="mt-3 pt-3 border-t border-border flex justify-end">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleLoadSession()
                      }}
                      className="text-xs text-accent hover:underline"
                    >
                      View full details &rarr;
                    </button>
                  </div>
                </div>
              )}

              {/* Connector */}
              {i < PHASE_META.length - 1 && (
                <div className="ml-9 h-2 border-l border-border" />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
