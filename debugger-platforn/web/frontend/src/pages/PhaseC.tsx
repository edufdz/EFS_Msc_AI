import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store'
import { usePhaseRunner } from '../hooks/usePhaseRunner'
import { getPhaseCStatus, getPhaseCTraces, resetPhase as apiResetPhase } from '../api/client'
import ExecutionControls from '../components/phase-c/ExecutionControls'
import PersonaContextInput from '../components/phase-c/PersonaContextInput'
import LlmProviderSelect from '../components/shared/LlmProviderSelect'
import LiveMonitor from '../components/phase-c/LiveMonitor'
import type { PhaseCResult } from '../api/types'

export default function PhaseC() {
  const navigate = useNavigate()
  const sessionId = useStore((s) => s.sessionId)
  const phaseStatus = useStore((s) => s.phaseC)
  const progress = useStore((s) => s.phaseCProgress)
  const phaseResult = useStore((s) => s.phaseCResult)
  const setPhaseCResult = useStore((s) => s.setPhaseCResult)
  const setPhaseStatus = useStore((s) => s.setPhaseStatus)
  const hydratePhaseCFromResult = useStore((s) => s.hydratePhaseCFromResult)
  const hydratePhaseCTraces = useStore((s) => s.hydratePhaseCTraces)
  const phaseBCompleted = useStore((s) => s.phaseB) === 'completed'
  const phaseBResult = useStore((s) => s.phaseBResult)
  const completedTests = useStore((s) => s.completedTests)
  const totalTests = useStore((s) => s.totalTests)
  const triageSummary = useStore((s) => s.triageSummary)
  const storeResetPhase = useStore((s) => s.resetPhase)
  const { runPhaseC } = usePhaseRunner()

  // Form state
  const [workers, setWorkers] = useState(10)
  const [count, setCount] = useState(10)
  const [aiPersonas, setAiPersonas] = useState(true)
  const [traces, setTraces] = useState(true)
  const [seed, setSeed] = useState<number | null>(null)
  const [language, setLanguage] = useState('')
  const [personaContext, setPersonaContext] = useState('')
  const [validate, setValidate] = useState(true)
  const [agentEndpoint, setAgentEndpoint] = useState('http://localhost:3099')
  const [llmProvider, setLlmProvider] = useState('')
  const [llmModel, setLlmModel] = useState('')
  const [llmBaseUrl, setLlmBaseUrl] = useState('')
  const [error, setError] = useState('')

  // If Phase B produced no non-AI personas, force AI personas on
  const hasNonAiPersonas = phaseBResult?.personas?.some((p) => p.source !== 'ai_generated') ?? false
  const forceAiPersonas = !hasNonAiPersonas

  useEffect(() => {
    if (forceAiPersonas && !aiPersonas) setAiPersonas(true)
  }, [forceAiPersonas, aiPersonas])

  useEffect(() => {
    if (sessionId && !phaseResult && phaseStatus !== 'running') {
      getPhaseCStatus(sessionId).then((s) => {
        if (s.status === 'completed' && s.result) {
          const result = s.result as unknown as PhaseCResult
          setPhaseStatus('c', 'completed')
          hydratePhaseCFromResult(result)
          setPhaseCResult(result)
          // Load saved conversation traces
          getPhaseCTraces(sessionId).then((t) => {
            if (t.traces.length > 0) {
              hydratePhaseCTraces(t.traces)
            }
          }).catch(() => {})
        }
      }).catch(() => {})
    }
  }, [sessionId, phaseResult, phaseStatus, setPhaseStatus, setPhaseCResult, hydratePhaseCFromResult, hydratePhaseCTraces])

  const handleRun = async () => {
    setError('')
    if (!sessionId) {
      setError('No active session')
      return
    }
    try {
      await runPhaseC({
        session_id: sessionId,
        workers,
        count,
        ai_personas: aiPersonas,
        traces,
        seed,
        language: language || null,
        persona_context: personaContext || null,
        validate,
        agent_endpoint: agentEndpoint || null,
        llm_provider: llmProvider || null,
        llm_model: llmModel || null,
        llm_base_url: llmBaseUrl || null,
      })
    } catch (e) {
      setError(String(e))
    }
  }

  const handleRerun = async () => {
    if (!sessionId) return
    try {
      await apiResetPhase(sessionId, 'c')
      storeResetPhase('c')
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

  const status: string = phaseStatus
  if (!phaseBCompleted && status === 'idle') {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <p className="text-smoke">Phase B must be completed first</p>
        <button onClick={() => navigate('/phase-b')} className="px-4 py-2 bg-platinum text-bg rounded-lg text-sm font-medium">
          Go to Phase B
        </button>
      </div>
    )
  }

  // Show live monitor when running or when completed (keep it visible so you can still see conversations/results)
  const showMonitor = status === 'running' || (status === 'completed' && (completedTests > 0 || phaseResult != null))
  const failedCount = phaseResult ? phaseResult.failed + phaseResult.errors + phaseResult.timeouts : 0
  const triage = phaseResult?.triage ?? triageSummary

  if (showMonitor) {
    // Show loading state when execution just started and no tests have completed yet
    const isInitializing = status === 'running' && completedTests === 0 && totalTests === 0

    return (
      <div className="h-full">
        {isInitializing && (
          <div className="flex flex-col items-center justify-center py-16 space-y-4">
            <div className="w-8 h-8 border-2 border-platinum/30 border-t-platinum rounded-full animate-spin" />
            <p className="text-sm text-smoke">Starting test execution...</p>
            {progress.message && <p className="text-xs text-text-muted">{progress.message}</p>}
          </div>
        )}
        {/* Phase C → D CTA banner */}
        {status === 'completed' && phaseResult && failedCount > 0 && (
          <div className="mb-4 bg-bg-card border border-border rounded-lg px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              {triage ? (
                <>
                  <span className="text-sm text-pearl font-medium">
                    {triage.genuine_failures} genuine failure{triage.genuine_failures !== 1 ? 's' : ''}
                  </span>
                  <span className="text-xs text-text-muted">
                    {triage.persona_filtered > 0 && `${triage.persona_filtered} persona-filtered`}
                    {triage.persona_filtered > 0 && triage.chaos_filtered > 0 && ', '}
                    {triage.chaos_filtered > 0 && `${triage.chaos_filtered} chaos-filtered`}
                    {triage.false_successes > 0 && ` + ${triage.false_successes} false success${triage.false_successes !== 1 ? 'es' : ''} caught`}
                  </span>
                </>
              ) : (
                <>
                  <span className="text-sm text-pearl font-medium">
                    {failedCount} failure{failedCount !== 1 ? 's' : ''} detected
                  </span>
                  <span className="text-xs text-text-muted">Ready for diagnosis</span>
                </>
              )}
            </div>
            <button
              onClick={() => navigate('/phase-d')}
              className="px-4 py-1.5 bg-platinum text-bg rounded-lg text-sm font-medium hover:bg-pearl transition-colors duration-200"
            >
              Diagnose &rarr;
            </button>
          </div>
        )}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-pearl">Phase C: Live Monitor</h1>
            <p className="text-sm text-smoke mt-0.5">
              {status === 'running' ? 'Test execution in progress...' : 'Execution completed'}
            </p>
          </div>
          {status === 'completed' && phaseResult && (
            <div className="flex items-center gap-4">
              <button
                onClick={handleRerun}
                className="px-3 py-1.5 border border-border rounded-lg text-sm text-smoke hover:text-pearl hover:border-border-light transition-colors duration-200"
              >
                Re-run
              </button>
              <div className="text-right">
                <div className={`text-2xl font-bold font-mono ${phaseResult.pass_rate >= 80 ? 'text-pearl' : 'text-smoke'}`}>
                  {phaseResult.pass_rate.toFixed(1)}%
                </div>
                <div className="text-[11px] text-text-muted uppercase tracking-wider">Final Pass Rate</div>
              </div>
            </div>
          )}
        </div>
        <LiveMonitor />
      </div>
    )
  }

  // Pre-run configuration
  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-pearl">Phase C: Execute Tests</h1>
        <p className="text-sm text-smoke mt-0.5">Run the test suite against the agent with live monitoring</p>
      </div>

      {/* Agent Endpoint */}
      <div className="p-4 bg-bg-card border border-border rounded-lg space-y-2">
        <label className="block text-sm font-medium text-pearl">Agent Endpoint</label>
        <p className="text-xs text-text-muted">The URL where your agent's HTTP API is running (must expose POST /chat)</p>
        <input
          type="text"
          value={agentEndpoint}
          onChange={(e) => setAgentEndpoint(e.target.value)}
          placeholder="http://localhost:3099"
          className="w-full px-3 py-2 bg-bg border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-6">
          <ExecutionControls
            workers={workers} onWorkersChange={setWorkers}
            count={count} onCountChange={setCount}
            aiPersonas={aiPersonas} onAiPersonasChange={setAiPersonas}
            traces={traces} onTracesChange={setTraces}
            seed={seed} onSeedChange={setSeed}
            language={language} onLanguageChange={setLanguage}
            validate={validate} onValidateChange={setValidate}
            forceAiPersonas={forceAiPersonas}
          />
        </div>

        <div className="space-y-6">
          <PersonaContextInput value={personaContext} onChange={setPersonaContext} />
          <LlmProviderSelect
            provider={llmProvider} onProviderChange={setLlmProvider}
            model={llmModel} onModelChange={setLlmModel}
            baseUrl={llmBaseUrl} onBaseUrlChange={setLlmBaseUrl}
          />
        </div>
      </div>

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
        {status === 'running' ? 'Executing...' : 'Run Phase C'}
      </button>

      {status === 'running' && (
        <div className="space-y-2">
          <div className="h-1 bg-border rounded-full overflow-hidden">
            <div className="h-full bg-platinum rounded-full transition-all duration-500" style={{ width: `${progress.pct}%` }} />
          </div>
          <div className="text-xs text-smoke">{progress.message || 'Starting execution...'}</div>
        </div>
      )}
    </div>
  )
}
