import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store'
import { usePhaseRunner } from '../hooks/usePhaseRunner'
import { getPhaseDStatus, resetPhase as apiResetPhase } from '../api/client'
import DiagnosisControls from '../components/phase-d/DiagnosisControls'
import DiagnosisDashboard from '../components/phase-d/DiagnosisDashboard'
import PhaseProgress from '../components/shared/PhaseProgress'
import type { PhaseDResult } from '../api/types'

const PHASE_D_STEPS = [
  { key: 'loading_data', label: 'Loading failure data...', pctThreshold: 5 },
  { key: 'clustering', label: 'Clustering failures...', pctThreshold: 15 },
  { key: 'root_cause_analysis', label: 'Analyzing root causes...', pctThreshold: 35 },
  { key: 'minimal_reproduction', label: 'Generating reproductions...', pctThreshold: 55 },
  { key: 'fix_generation', label: 'Generating fix proposals...', pctThreshold: 75 },
  { key: 'priority_ranking', label: 'Ranking by priority...', pctThreshold: 90 },
  { key: 'saving_report', label: 'Saving report...', pctThreshold: 95 },
]

export default function PhaseD() {
  const navigate = useNavigate()
  const sessionId = useStore((s) => s.sessionId)
  const phaseStatus = useStore((s) => s.phaseD)
  const progress = useStore((s) => s.phaseDProgress)
  const phaseResult = useStore((s) => s.phaseDResult)
  const setPhaseDResult = useStore((s) => s.setPhaseDResult)
  const setPhaseStatus = useStore((s) => s.setPhaseStatus)
  const phaseCCompleted = useStore((s) => s.phaseC) === 'completed'
  const storeResetPhase = useStore((s) => s.resetPhase)
  const { runPhaseD } = usePhaseRunner()

  // Form state
  const [skipAi, setSkipAi] = useState(false)
  const [useEmbeddings, setUseEmbeddings] = useState(false)
  const [maxRetries, setMaxRetries] = useState(3)
  const [error, setError] = useState('')

  // Hydrate from server on mount
  useEffect(() => {
    if (sessionId && !phaseResult && phaseStatus !== 'running') {
      getPhaseDStatus(sessionId).then((s) => {
        if (s.status === 'completed' && s.result) {
          setPhaseStatus('d', 'completed')
          setPhaseDResult(s.result as unknown as PhaseDResult)
        }
      }).catch(() => {})
    }
  }, [sessionId, phaseResult, phaseStatus, setPhaseStatus, setPhaseDResult])

  const handleRerun = async () => {
    if (!sessionId) return
    try {
      await apiResetPhase(sessionId, 'd')
      storeResetPhase('d')
    } catch (e) {
      setError(String(e))
    }
  }

  const handleRun = async () => {
    setError('')
    if (!sessionId) {
      setError('No active session')
      return
    }
    try {
      await runPhaseD({
        session_id: sessionId,
        skip_ai: skipAi,
        use_embeddings: useEmbeddings,
        max_retries: maxRetries,
        backoff_base: 2.0,
        backoff_max: 60.0,
      })
    } catch (e) {
      setError(String(e))
    }
  }

  if (!sessionId) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <p className="text-smoke">No active session</p>
        <button onClick={() => navigate('/')} className="px-4 py-2 bg-platinum text-bg rounded-lg text-sm font-medium">
          Go to Dashboard
        </button>
      </div>
    )
  }

  if (!phaseCCompleted && phaseStatus === 'idle') {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <p className="text-smoke">Phase C must be completed first</p>
        <button onClick={() => navigate('/phase-c')} className="px-4 py-2 bg-platinum text-bg rounded-lg text-sm font-medium">
          Go to Phase C
        </button>
      </div>
    )
  }

  const status: string = phaseStatus

  // Completed — show dashboard
  if (status === 'completed' && phaseResult) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-pearl">Phase D: Diagnosis</h1>
            <p className="text-sm text-smoke mt-0.5">Failure analysis and fix recommendations</p>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={handleRerun}
              className="px-3 py-1.5 border border-border rounded-lg text-sm text-smoke hover:text-pearl hover:border-border-light transition-colors duration-200"
            >
              Re-run
            </button>
            <div className="text-right">
              <div className="text-2xl font-bold font-mono text-pearl">
                {phaseResult.clusters_found}
              </div>
              <div className="text-[11px] text-text-muted uppercase tracking-wider">Clusters Found</div>
            </div>
          </div>
        </div>
        <DiagnosisDashboard result={phaseResult} sessionId={sessionId} />
      </div>
    )
  }

  // Pre-run / running
  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-pearl">Phase D: Diagnosis</h1>
        <p className="text-sm text-smoke mt-0.5">Analyze test failures, identify root causes, and generate fix proposals</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-6">
          <DiagnosisControls
            skipAi={skipAi} onSkipAiChange={setSkipAi}
            useEmbeddings={useEmbeddings} onUseEmbeddingsChange={setUseEmbeddings}
            maxRetries={maxRetries} onMaxRetriesChange={setMaxRetries}
          />

          {error && (
            <div className="px-3 py-2 bg-graphite border border-border-light rounded-lg text-sm text-smoke">
              {error}
            </div>
          )}

          <button
            onClick={handleRun}
            disabled={status === 'running'}
            className="w-full px-4 py-3 bg-platinum text-bg rounded-lg font-medium hover:bg-pearl transition-colors duration-200 disabled:opacity-50"
          >
            {status === 'running' ? 'Diagnosing...' : 'Run Phase D'}
          </button>
        </div>

        <div>
          {status === 'running' ? (
            <PhaseProgress
              steps={PHASE_D_STEPS}
              currentPct={progress.pct}
              currentMessage={progress.message}
            />
          ) : (
            <div className="flex items-center justify-center h-64 bg-bg-card border border-border rounded-lg">
              <p className="text-text-muted text-sm">Diagnosis results will appear here</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
