import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store'
import { usePhaseRunner } from '../hooks/usePhaseRunner'
import { getPhaseBStatus, resetPhase as apiResetPhase } from '../api/client'
import GenerationControls from '../components/phase-b/GenerationControls'
import TestSuitePreview from '../components/phase-b/TestSuitePreview'
import PhaseProgress from '../components/shared/PhaseProgress'
import type { PhaseBResult } from '../api/types'

const PHASE_B_STEPS = [
  { key: 'loading_agent_map', label: 'Loading Agent Map...', pctThreshold: 3 },
  { key: 'building_personas', label: 'Generating personas...', pctThreshold: 10 },
  { key: 'creating_scenarios', label: 'Creating scenarios...', pctThreshold: 30 },
  { key: 'generating_variants', label: 'Generating test variants...', pctThreshold: 50 },
  { key: 'saving_artifacts', label: 'Saving generated artifacts...', pctThreshold: 70 },
  { key: 'loading_results', label: 'Loading test suite results...', pctThreshold: 82 },
  { key: 'loading_personas', label: 'Loading persona library...', pctThreshold: 88 },
  { key: 'loading_scenarios', label: 'Loading scenario catalog...', pctThreshold: 93 },
]

export default function PhaseB() {
  const navigate = useNavigate()
  const sessionId = useStore((s) => s.sessionId)
  const phaseStatus = useStore((s) => s.phaseB)
  const progress = useStore((s) => s.phaseBProgress)
  const phaseResult = useStore((s) => s.phaseBResult)
  const setPhaseBResult = useStore((s) => s.setPhaseBResult)
  const setPhaseStatus = useStore((s) => s.setPhaseStatus)
  const phaseACompleted = useStore((s) => s.phaseA) === 'completed'
  const storeResetPhase = useStore((s) => s.resetPhase)
  const { runPhaseB } = usePhaseRunner()

  // Form state
  const [count, setCount] = useState(150)
  const [personaCount, setPersonaCount] = useState(8)
  const [scenarioCount, setScenarioCount] = useState(10)
  const [variants, setVariants] = useState(3)
  const [includeTemplates, setIncludeTemplates] = useState(false)
  const [seed, setSeed] = useState<number | null>(null)
  const [language, setLanguage] = useState('')
  const [llmProvider, setLlmProvider] = useState('')
  const [llmModel, setLlmModel] = useState('')
  const [llmBaseUrl, setLlmBaseUrl] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (sessionId && !phaseResult && phaseStatus !== 'running') {
      getPhaseBStatus(sessionId).then((s) => {
        if (s.status === 'completed' && s.result) {
          setPhaseStatus('b', 'completed')
          setPhaseBResult(s.result as unknown as PhaseBResult)
        }
      }).catch(() => {})
    }
  }, [sessionId, phaseResult, phaseStatus, setPhaseStatus, setPhaseBResult])

  const handleRun = async () => {
    setError('')
    if (!sessionId) {
      setError('No active session. Go back to Phase A.')
      return
    }
    try {
      // Reset this phase and downstream (C, D) so results are fresh
      if (phaseStatus === 'completed') {
        await apiResetPhase(sessionId, 'b')
        storeResetPhase('b')
      }
      await runPhaseB({
        session_id: sessionId,
        count,
        persona_count: personaCount,
        scenario_count: scenarioCount,
        variants,
        seed,
        language: language || null,
        include_templates: includeTemplates,
        llm_provider: llmProvider || null,
        llm_model: llmModel || null,
        llm_base_url: llmBaseUrl || null,
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

  if (!phaseACompleted && phaseStatus === 'idle') {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <p className="text-smoke">Phase A must be completed first</p>
        <button onClick={() => navigate('/phase-a')} className="px-4 py-2 bg-platinum text-bg rounded-lg text-sm font-medium">
          Go to Phase A
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-pearl">Phase B: Generate Tests</h1>
          <p className="text-sm text-smoke mt-0.5">Create personas, scenarios, and test suite from the Agent Map</p>
        </div>
        {phaseStatus === 'completed' && (
          <button
            onClick={() => navigate('/phase-c')}
            className="px-4 py-2 bg-platinum text-bg rounded-lg text-sm font-medium hover:bg-pearl transition-colors duration-200"
          >
            Continue to Phase C &rarr;
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Controls */}
        <div className="space-y-6">
          <GenerationControls
            count={count} onCountChange={setCount}
            personaCount={personaCount} onPersonaCountChange={setPersonaCount}
            scenarioCount={scenarioCount} onScenarioCountChange={setScenarioCount}
            variants={variants} onVariantsChange={setVariants}
            includeTemplates={includeTemplates} onIncludeTemplatesChange={setIncludeTemplates}
            seed={seed} onSeedChange={setSeed}
            language={language} onLanguageChange={setLanguage}
            llmProvider={llmProvider} onLlmProviderChange={setLlmProvider}
            llmModel={llmModel} onLlmModelChange={setLlmModel}
            llmBaseUrl={llmBaseUrl} onLlmBaseUrlChange={setLlmBaseUrl}
          />

          {error && (
            <div className="px-3 py-2 bg-graphite border border-border-light rounded-lg text-sm text-smoke">
              {error}
            </div>
          )}

          <button
            onClick={handleRun}
            disabled={phaseStatus === 'running'}
            className="w-full px-4 py-3 bg-platinum text-bg rounded-lg font-medium hover:bg-pearl transition-colors duration-200 disabled:opacity-50"
          >
            {phaseStatus === 'running' ? 'Generating...' : phaseStatus === 'completed' ? 'Re-generate Tests' : 'Run Phase B'}
          </button>

          {phaseStatus === 'running' && (
            <PhaseProgress
              steps={PHASE_B_STEPS}
              currentPct={progress.pct}
              currentMessage={progress.message}
            />
          )}
        </div>

        {/* Right: Results */}
        <div>
          {phaseStatus === 'completed' && phaseResult ? (
            <TestSuitePreview result={phaseResult} />
          ) : phaseStatus === 'idle' ? (
            <div className="flex items-center justify-center h-64 bg-bg-card border border-border rounded-lg">
              <p className="text-text-muted text-sm">Test suite preview will appear here</p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
