import { useState, useEffect, useCallback } from 'react'
import { useStore } from '../store'
import { usePhaseRunner } from '../hooks/usePhaseRunner'
import { getCertificationStatus, resetPhase as apiResetPhase, saveSession } from '../api/client'
import PhaseProgress from '../components/shared/PhaseProgress'
import TierBadge from '../components/certification/TierBadge'
import CategoryRadarChart from '../components/certification/CategoryRadarChart'
import ScoreBreakdown from '../components/certification/ScoreBreakdown'
import ConfidenceMeter from '../components/certification/ConfidenceMeter'
import PrintableCertificate from '../components/certification/PrintableCertificate'
import type { CertificationReport } from '../api/types'

const CERT_STEPS = [
  { key: 'loading_data', label: 'Loading data...', pctThreshold: 5 },
  { key: 'scoring', label: 'Scoring categories...', pctThreshold: 50 },
  { key: 'saving', label: 'Saving certification report...', pctThreshold: 90 },
  { key: 'complete', label: 'Certification complete', pctThreshold: 95 },
]

const TIER_COLORS: Record<string, string> = {
  platinum: '#3B82F6',
  gold: '#F59E0B',
  silver: '#9CA3AF',
  not_certified: '#EF4444',
}

export default function Certification() {
  const sessionId = useStore((s) => s.sessionId)
  const phaseStatus = useStore((s) => s.certStatus)
  const progress = useStore((s) => s.certProgress)
  const certResult = useStore((s) => s.certResult)
  const setCertResult = useStore((s) => s.setCertResult)
  const setPhaseStatus = useStore((s) => s.setPhaseStatus)
  const phaseDCompleted = useStore((s) => s.phaseD) === 'completed'
  const phaseCCompleted = useStore((s) => s.phaseC) === 'completed'
  const storeResetPhase = useStore((s) => s.resetPhase)
  const { runCertification } = usePhaseRunner()

  const [error, setError] = useState('')
  const [showPrintable, setShowPrintable] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle')

  const handleSaveSession = useCallback(async () => {
    if (!sessionId) return
    setSaveState('saving')
    try {
      await saveSession(sessionId)
      setSaveState('saved')
      setTimeout(() => setSaveState('idle'), 3000)
    } catch {
      setSaveState('idle')
    }
  }, [sessionId])

  // Hydrate from server on mount
  useEffect(() => {
    if (sessionId && !certResult && phaseStatus !== 'running') {
      getCertificationStatus(sessionId).then((s) => {
        if (s.status === 'completed' && s.result) {
          setPhaseStatus('cert', 'completed')
          setCertResult(s.result as unknown as CertificationReport)
          setRevealed(true) // Skip animation for hydrated results
        }
      }).catch(() => {})
    }
  }, [sessionId, certResult, phaseStatus, setPhaseStatus, setCertResult])

  // Confetti on first reveal
  useEffect(() => {
    if (phaseStatus === 'completed' && certResult && !revealed) {
      setRevealed(true)
      if (certResult.tier !== 'not_certified') {
        import('canvas-confetti').then(({ default: confetti }) => {
          const color = TIER_COLORS[certResult.tier] || '#3B82F6'
          confetti({
            particleCount: 80,
            spread: 70,
            origin: { y: 0.3 },
            colors: [color, '#ffffff', color + '80'],
          })
        }).catch(() => {})
      }
    }
  }, [phaseStatus, certResult, revealed])

  const handleRerun = useCallback(async () => {
    if (!sessionId) return
    try {
      await apiResetPhase(sessionId, 'cert')
      storeResetPhase('cert')
      setRevealed(false)
    } catch (e) {
      setError(String(e))
    }
  }, [sessionId, storeResetPhase])

  const handleRun = useCallback(async () => {
    setError('')
    if (!sessionId) { setError('No active session'); return }
    try {
      setRevealed(false)
      await runCertification({ session_id: sessionId })
    } catch (e) {
      setError(String(e))
    }
  }, [sessionId, runCertification])

  const canRun = phaseDCompleted || phaseCCompleted

  // Running state
  if (phaseStatus === 'running') {
    return (
      <div className="p-6 max-w-3xl mx-auto space-y-6">
        <h2 className="text-2xl font-semibold text-pearl">Certification</h2>
        <PhaseProgress steps={CERT_STEPS} currentPct={progress.pct} currentMessage={progress.message} />
      </div>
    )
  }

  // Completed state
  if (phaseStatus === 'completed' && certResult) {
    const tierColor = TIER_COLORS[certResult.tier] || TIER_COLORS.not_certified
    const expiresAt = certResult.expires_at ? new Date(certResult.expires_at) : null
    const daysLeft = expiresAt ? Math.ceil((expiresAt.getTime() - Date.now()) / (1000 * 60 * 60 * 24)) : null

    return (
      <div className="p-6 max-w-5xl mx-auto space-y-8">
        {showPrintable && (
          <PrintableCertificate report={certResult} onClose={() => setShowPrintable(false)} />
        )}

        {/* Header with actions */}
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-semibold text-pearl">Certification Report</h2>
          <div className="flex items-center gap-2">
            <button onClick={handleSaveSession}
              disabled={saveState === 'saving'}
              className={`px-4 py-2 text-sm border rounded-lg font-medium transition-colors ${
                saveState === 'saved'
                  ? 'bg-green-50 border-green-200 text-green-700'
                  : 'border-border hover:bg-bg-card text-text-dim'
              }`}>
              {saveState === 'saved' ? 'Saved!' : saveState === 'saving' ? 'Saving...' : 'Save Session'}
            </button>
            <button onClick={() => setShowPrintable(true)}
              className="px-4 py-2 text-sm bg-accent text-white rounded-lg hover:bg-accent/90 font-medium transition-colors">
              View Certificate
            </button>
            <button onClick={handleRerun}
              className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-bg-card text-text-dim transition-colors">
              Re-run
            </button>
          </div>
        </div>

        {/* Hero card: Badge + Meta */}
        <div className="flex items-center gap-8 p-8 bg-bg-surface border border-border rounded-xl"
          style={{ borderTopColor: tierColor, borderTopWidth: 3 }}>
          <TierBadge tier={certResult.tier} score={certResult.overall_score} size={180} animated={!revealed} />

          <div className="flex-1 space-y-3">
            <div>
              <div className="text-sm text-text-muted">Agent</div>
              <div className="text-xl font-bold text-pearl">{certResult.agent_name}</div>
              <div className="text-sm text-text-dim">{certResult.agent_framework}</div>
            </div>

            <div className="flex gap-6 text-sm">
              <div>
                <span className="text-text-muted">Issued: </span>
                <span className="text-pearl">
                  {certResult.issued_at ? new Date(certResult.issued_at).toLocaleDateString() : 'N/A'}
                </span>
              </div>
              <div>
                <span className="text-text-muted">Expires: </span>
                <span className="text-pearl">
                  {expiresAt ? expiresAt.toLocaleDateString() : 'N/A'}
                </span>
                {daysLeft !== null && daysLeft > 0 && (
                  <span className={`ml-2 text-xs px-2 py-0.5 rounded-full ${
                    daysLeft <= 30 ? 'bg-yellow-100 text-yellow-700' : 'bg-green-100 text-green-700'
                  }`}>
                    {daysLeft}d left
                  </span>
                )}
              </div>
            </div>

            <div className="text-xs font-mono text-text-muted">ID: {certResult.certification_id}</div>
          </div>
        </div>

        {/* Radar + Breakdown side by side */}
        <div className="grid grid-cols-2 gap-6">
          <div className="p-6 bg-bg-surface border border-border rounded-xl">
            <CategoryRadarChart data={certResult.radar_chart_data} tier={certResult.tier} />
          </div>
          <div className="p-6 bg-bg-surface border border-border rounded-xl">
            <ScoreBreakdown categories={certResult.category_scores} />
          </div>
        </div>

        {/* Hard Blockers */}
        {certResult.hard_blockers.length > 0 && (
          <div className="p-6 bg-red-50 border border-red-200 rounded-xl space-y-3">
            <h3 className="text-lg font-medium text-red-700 flex items-center gap-2">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              Hard Blockers ({certResult.hard_blockers.length})
            </h3>
            <div className="space-y-2">
              {certResult.hard_blockers.map((b, i) => (
                <div key={i} className="flex items-start gap-3 p-3 bg-white/60 rounded-lg">
                  <div className="w-1.5 h-1.5 rounded-full bg-red-500 mt-2 shrink-0" />
                  <div className="flex-1">
                    <div className="text-sm font-medium text-red-800">{b.condition}</div>
                    {b.evidence && <div className="text-xs text-red-600/70 mt-1">{b.evidence}</div>}
                  </div>
                  <span className="text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded-full shrink-0">
                    Blocks {b.tier_blocked.replace('_', ' ')}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Strengths & Improvements */}
        <div className="grid grid-cols-2 gap-6">
          {certResult.strengths.length > 0 && (
            <div className="p-6 bg-bg-surface border border-border rounded-xl space-y-3">
              <h3 className="text-lg font-medium text-green-600 flex items-center gap-2">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
                Strengths
              </h3>
              {certResult.strengths.map((s, i) => (
                <div key={i} className="flex items-start gap-2 text-sm text-text-dim">
                  <span className="text-green-500 mt-0.5 shrink-0">+</span>
                  <span>{s}</span>
                </div>
              ))}
            </div>
          )}
          {certResult.improvements.length > 0 && (
            <div className="p-6 bg-bg-surface border border-border rounded-xl space-y-3">
              <h3 className="text-lg font-medium text-yellow-600 flex items-center gap-2">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                Areas for Improvement
              </h3>
              {certResult.improvements.map((s, i) => (
                <div key={i} className="flex items-start gap-2 text-sm text-text-dim">
                  <span className="text-yellow-500 mt-0.5 shrink-0">-</span>
                  <span>{s}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Confidence Meter */}
        <div className="p-6 bg-bg-surface border border-border rounded-xl">
          <ConfidenceMeter confidence={certResult.confidence} overallScore={certResult.overall_score} />
        </div>

        {/* Testing Conditions */}
        <div className="p-4 bg-bg-surface border border-border rounded-xl">
          <h3 className="text-sm font-medium text-pearl mb-3">Testing Conditions</h3>
          <div className="flex gap-6 text-sm text-text-dim flex-wrap">
            <span>Simulations: <strong className="text-pearl">{certResult.testing_conditions.total_simulations}</strong></span>
            <span>Personas: <strong className="text-pearl">{certResult.testing_conditions.persona_count}</strong></span>
            <span>Diversity: <strong className="text-pearl">{(certResult.testing_conditions.persona_diversity * 100).toFixed(0)}%</strong></span>
            <span>Chaos Tested: <strong className="text-pearl">{certResult.testing_conditions.chaos_tested ? 'Yes' : 'No'}</strong></span>
            {Object.entries(certResult.testing_conditions.by_difficulty).map(([d, n]) => (
              <span key={d}>{d}: <strong className="text-pearl">{n}</strong></span>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // Idle / pre-run state
  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <h2 className="text-2xl font-semibold text-pearl">Certification</h2>

      <div className="p-6 bg-bg-surface border border-border rounded-xl space-y-4">
        <p className="text-text-dim">
          Score the agent across 5 categories and assign a certification tier.
        </p>

        {/* Readiness check */}
        <div className="space-y-2">
          <div className="text-sm font-medium text-pearl">Readiness Check</div>
          <div className="flex gap-3">
            {[
              { label: 'Phase C (Execution)', done: phaseCCompleted },
              { label: 'Phase D (Diagnosis)', done: phaseDCompleted },
            ].map((p) => (
              <div key={p.label} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm border ${
                p.done ? 'bg-green-50 border-green-200 text-green-700' : 'bg-bg-card border-border text-text-muted'
              }`}>
                {p.done ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10" />
                  </svg>
                )}
                {p.label}
              </div>
            ))}
          </div>
        </div>

        {!canRun && (
          <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-700">
            Complete Phase C or D before running certification.
          </div>
        )}

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>
        )}

        <button
          onClick={handleRun}
          disabled={!canRun}
          className="px-6 py-3 bg-accent text-white font-medium rounded-lg hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          Run Certification
        </button>
      </div>

      {/* Tier legend */}
      <div className="p-4 bg-bg-surface border border-border rounded-xl">
        <div className="text-sm font-medium text-pearl mb-3">Certification Tiers</div>
        <div className="grid grid-cols-4 gap-3">
          {[
            { tier: 'Platinum', score: '90+', color: '#3B82F6', desc: '100+ sims, <1% hallucination' },
            { tier: 'Gold', score: '75+', color: '#F59E0B', desc: '50+ sims, <3% hallucination' },
            { tier: 'Silver', score: '60+', color: '#9CA3AF', desc: '20+ sims, <8% hallucination' },
            { tier: 'Not Certified', score: '<60', color: '#EF4444', desc: 'Does not meet minimum' },
          ].map((t) => (
            <div key={t.tier} className="text-center p-3 rounded-lg bg-white border border-border">
              <div className="w-3 h-3 rounded-full mx-auto mb-2" style={{ backgroundColor: t.color }} />
              <div className="text-sm font-medium text-pearl">{t.tier}</div>
              <div className="text-xs font-mono text-text-dim">{t.score}</div>
              <div className="text-[10px] text-text-muted mt-1">{t.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
