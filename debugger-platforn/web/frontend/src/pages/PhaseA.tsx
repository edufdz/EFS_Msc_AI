import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store'
import { usePhaseRunner } from '../hooks/usePhaseRunner'
import { createSession, getPhaseAStatus } from '../api/client'
import RepoSelector from '../components/phase-a/RepoSelector'
import AnalysisOptions from '../components/phase-a/AnalysisOptions'
import AgentMapViewer from '../components/phase-a/AgentMapViewer'
import PhaseProgress from '../components/shared/PhaseProgress'
import type { PhaseAResult } from '../api/types'

const PHASE_A_STEPS = [
  { key: 'scanning_codebase', label: 'Scanning codebase...', pctThreshold: 5 },
  { key: 'parsing_treesitter', label: 'Parsing with Tree-sitter...', pctThreshold: 20 },
  { key: 'detecting_patterns', label: 'Detecting agent patterns...', pctThreshold: 40 },
  { key: 'analyzing_risks', label: 'Analyzing risks...', pctThreshold: 55 },
  { key: 'ai_analysis', label: 'Running AI semantic analysis...', pctThreshold: 65 },
  { key: 'building_map', label: 'Building Agent Map...', pctThreshold: 85 },
]

export default function PhaseA() {
  const navigate = useNavigate()
  const sessionId = useStore((s) => s.sessionId)
  const setSessionId = useStore((s) => s.setSessionId)
  const phaseStatus = useStore((s) => s.phaseA)
  const progress = useStore((s) => s.phaseAProgress)
  const phaseResult = useStore((s) => s.phaseAResult)
  const setPhaseAResult = useStore((s) => s.setPhaseAResult)
  const setPhaseStatus = useStore((s) => s.setPhaseStatus)
  const { runPhaseA } = usePhaseRunner()

  // Form state
  const [repoPath, setRepoPath] = useState('')
  const [skipAi, setSkipAi] = useState(false)
  const [language, setLanguage] = useState('')
  const [promptEncoding, setPromptEncoding] = useState('utf-8')
  const [error, setError] = useState('')

  // On mount, check if we already have a result
  useEffect(() => {
    if (sessionId && !phaseResult && phaseStatus !== 'running') {
      getPhaseAStatus(sessionId).then((s) => {
        if (s.status === 'completed' && s.result) {
          setPhaseStatus('a', 'completed')
          setPhaseAResult(s.result as unknown as PhaseAResult)
        }
      }).catch(() => {})
    }
  }, [sessionId, phaseResult, phaseStatus, setPhaseStatus, setPhaseAResult])

  const handleRun = async () => {
    setError('')
    if (!repoPath) {
      setError('Please select a repository path')
      return
    }
    try {
      let sid = sessionId
      if (!sid) {
        const session = await createSession()
        sid = session.session_id
        setSessionId(sid)
      }
      await runPhaseA({
        session_id: sid,
        repo_path: repoPath,
        skip_ai: skipAi,
        language: language || null,
        prompt_encoding: promptEncoding,
      })
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-pearl">Phase A: Analyze</h1>
          <p className="text-sm text-smoke mt-0.5">Scan an agent codebase to produce a structured Agent Map</p>
        </div>
        {phaseStatus === 'completed' && (
          <button
            onClick={() => navigate('/phase-b')}
            className="px-4 py-2 bg-platinum text-bg rounded-lg text-sm font-medium hover:bg-pearl transition-colors duration-200"
          >
            Continue to Phase B &rarr;
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Controls */}
        <div className="space-y-6">
          <RepoSelector repoPath={repoPath} onPathChange={setRepoPath} />
          <AnalysisOptions
            skipAi={skipAi}
            language={language}
            promptEncoding={promptEncoding}
            onSkipAiChange={setSkipAi}
            onLanguageChange={setLanguage}
            onEncodingChange={setPromptEncoding}
          />

          {error && (
            <div className="px-3 py-2 bg-graphite border border-border-light rounded-lg text-sm text-smoke">
              {error}
            </div>
          )}

          {/* Run button */}
          <button
            onClick={handleRun}
            disabled={phaseStatus === 'running'}
            className="w-full px-4 py-3 bg-platinum text-bg rounded-lg font-medium hover:bg-pearl transition-colors duration-200 disabled:opacity-50"
          >
            {phaseStatus === 'running' ? 'Analyzing...' : 'Run Phase A'}
          </button>

          {/* Animated progress */}
          {phaseStatus === 'running' && (
            <PhaseProgress
              steps={PHASE_A_STEPS}
              currentPct={progress.pct}
              currentMessage={progress.message}
            />
          )}
        </div>

        {/* Right: Results */}
        <div>
          {phaseStatus === 'completed' && phaseResult ? (
            <AgentMapViewer result={phaseResult} sessionId={sessionId!} />
          ) : phaseStatus === 'idle' ? (
            <div className="flex items-center justify-center h-64 bg-bg-card border border-border rounded-lg">
              <p className="text-text-muted text-sm">Results will appear here after analysis</p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
