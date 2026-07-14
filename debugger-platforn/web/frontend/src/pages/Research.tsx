import { useState, useEffect, useCallback } from 'react'
import {
  previewGroundTruth,
  runResearchAnonymize,
  runResearchExperiment,
  listResearchRuns,
  getResearchRun,
  researchChartUrl,
} from '../api/client'
import type {
  GroundTruthPreview,
  ResearchRun,
  ResearchResults,
} from '../api/types'

const DEFAULT_INPUT_PATH = '../docs/tech_repair-conversations-export.json'
const DEFAULT_ANON_PATH = '../docs/tech_repair-conversations-anonymized.json'
const DEFAULT_AGENT_MAP = 'tech_repair_whatsapp_map.json'

const CHART_NAMES = [
  { name: 'rq1_per_category_recall.png', label: 'RQ1 · Per-category recall' },
  { name: 'rq4_recall_vs_budget.png', label: 'RQ4 · Recall vs budget' },
  { name: 'rq3_arm_comparison.png', label: 'RQ3 · Arm comparison' },
  { name: 'ground_truth_categories.png', label: 'Ground truth categories' },
]

const STATIC_MODE_CAVEAT =
  'Static mode matches generated test definitions against ground-truth signals without executing conversations; recall is a lower-bound estimate.'

// ---------- Small building blocks ----------

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="p-6 bg-bg-surface border border-border rounded-xl space-y-4">
      <h3 className="text-sm font-medium text-pearl uppercase tracking-wider">{title}</h3>
      {children}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-text-muted uppercase tracking-wider">{label}</span>
      {children}
    </label>
  )
}

const inputClass =
  'w-full px-3 py-2 text-sm font-mono bg-bg border border-border rounded-lg text-text-primary focus:outline-none focus:border-accent transition-colors'

function ErrorBox({ message }: { message: string }) {
  return <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{message}</div>
}

function ProgressFeed({ run }: { run: ResearchRun }) {
  const lines = run.progress.slice(-10)
  return (
    <div className="p-3 bg-bg-card border border-border rounded-lg space-y-1 font-mono text-xs text-text-dim max-h-48 overflow-y-auto">
      {lines.length === 0 && <div className="text-text-muted">Waiting for progress...</div>}
      {lines.map((l, i) => (
        <div key={i} className="flex gap-2">
          <span className="text-text-muted shrink-0">{new Date(l.at).toLocaleTimeString()}</span>
          <span>{l.message}</span>
        </div>
      ))}
      {run.status === 'running' && (
        <div className="flex items-center gap-2 text-accent">
          <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          running...
        </div>
      )}
    </div>
  )
}

function RunStatusPill({ status }: { status: ResearchRun['status'] }) {
  const cls =
    status === 'completed'
      ? 'bg-green-50 border-green-200 text-green-700'
      : status === 'running'
        ? 'bg-accent/10 border-accent/20 text-accent'
        : 'bg-red-50 border-red-200 text-red-700'
  return (
    <span className={`inline-flex px-2 py-0.5 text-[11px] font-medium rounded border uppercase tracking-wider ${cls}`}>
      {status}
    </span>
  )
}

function StatCard({ label, value, sub, title }: { label: string; value: React.ReactNode; sub?: React.ReactNode; title?: string }) {
  return (
    <div className="p-4 bg-bg-surface border border-border rounded-xl" title={title}>
      <div className="text-[11px] text-text-muted uppercase tracking-wider">{label}</div>
      <div className="text-xl font-bold font-mono text-pearl mt-1">{value}</div>
      {sub && <div className="text-xs text-text-dim mt-1">{sub}</div>}
    </div>
  )
}

function recallCellClass(recall: number): string {
  if (recall < 0.25) return 'bg-red-50 text-red-700'
  if (recall < 0.5) return 'bg-yellow-50 text-yellow-700'
  return 'bg-green-50 text-green-700'
}

function pct(v: number | undefined | null, digits = 1): string {
  if (v === undefined || v === null || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function ChartImage({ runId, name, label }: { runId: string; name: string; label: string }) {
  const [hidden, setHidden] = useState(false)
  // Reset visibility when the selected run changes
  useEffect(() => setHidden(false), [runId, name])
  if (hidden) return null
  return (
    <div className="p-4 bg-bg-surface border border-border rounded-xl space-y-2">
      <div className="text-xs text-text-muted uppercase tracking-wider">{label}</div>
      <img
        src={researchChartUrl(runId, name)}
        alt={label}
        className="w-full rounded-lg border border-border bg-white"
        onError={() => setHidden(true)}
      />
    </div>
  )
}

// ---------- Results section ----------

function ResultsSection({ results, runId }: { results: ResearchResults; runId: string }) {
  const rq1 = results.rq1_predictive_validity
  const rq3 = results.rq3_production_feedback
  const rq4 = results.rq4_recall_vs_budget

  const comparison = rq3.available ? rq3.comparison : undefined
  const blind = comparison?.arms?.blind
  const feedback = comparison?.arms?.feedback
  const test = comparison?.tests?.feedback_vs_blind
  const significant = test !== undefined && test.p_value < 0.05

  const perCategory = Object.entries(rq1.per_category).sort(
    (a, b) => b[1].n_production_signals - a[1].n_production_signals,
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-pearl">Results</h3>
        <span className="font-mono text-xs text-text-muted">{runId}</span>
      </div>

      {/* Headline stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label={`RQ1 · Recall (${rq1.arm})`}
          value={pct(rq1.overall.recall)}
          sub={
            <>
              CI [{pct(rq1.recall_ci.ci_low)} – {pct(rq1.recall_ci.ci_high)}] · precision {pct(rq1.overall.precision)}
            </>
          }
        />
        <StatCard
          label="RQ3 · Blind → Feedback"
          value={
            blind && feedback ? (
              <>
                {pct(blind.recall)} <span className="text-text-muted">→</span> {pct(feedback.recall)}
              </>
            ) : (
              'N/A'
            )
          }
          sub={
            test ? (
              <span className={significant ? 'text-green-700 font-medium' : undefined}>
                Δ {test.delta >= 0 ? '+' : ''}{pct(test.delta)} · p = {test.p_value}
                {significant ? ' · significant' : ''}
              </span>
            ) : (
              'Holdout comparison unavailable'
            )
          }
        />
        <StatCard
          label="RQ4 · Budget ranking"
          value={<span className="text-base">{rq4.ranking.join(' > ')}</span>}
          sub={rq4.note}
        />
        <StatCard
          label="Setup"
          value={
            <span className="inline-flex items-center gap-2 text-base">
              {results.anonymisation_level}
              <span
                className="px-2 py-0.5 text-[11px] font-medium rounded border uppercase tracking-wider bg-accent/10 border-accent/20 text-accent"
                title={results.config.mode === 'static' ? STATIC_MODE_CAVEAT : undefined}
              >
                {results.config.mode}
              </span>
            </span>
          }
          sub={
            <>
              taxonomy {results.taxonomy_version}
              {results.config.mode === 'static' && (
                <div className="text-[11px] text-text-muted mt-1">{STATIC_MODE_CAVEAT}</div>
              )}
            </>
          }
        />
      </div>

      {/* Ground truth summary */}
      <div className="p-4 bg-bg-surface border border-border rounded-xl">
        <div className="flex gap-6 text-sm text-text-dim flex-wrap">
          <span>Ground-truth failures: <strong className="text-pearl font-mono">{results.ground_truth.n_failures}</strong></span>
          <span>Train: <strong className="text-pearl font-mono">{results.ground_truth.n_train}</strong></span>
          <span>Holdout: <strong className="text-pearl font-mono">{results.ground_truth.n_holdout}</strong></span>
          {rq3.available && rq3.n_holdout_signals !== undefined && (
            <span>Holdout signals: <strong className="text-pearl font-mono">{rq3.n_holdout_signals}</strong></span>
          )}
          <span>Budget: <strong className="text-pearl font-mono">{results.config.budget}</strong></span>
        </div>
      </div>

      {/* RQ1 per-category table */}
      <SectionCard title="RQ1 · Per-category predictive validity">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-text-muted uppercase tracking-wider border-b border-border">
                <th className="py-2 pr-4">Category</th>
                <th className="py-2 pr-4">Severity</th>
                <th className="py-2 pr-4 text-right">Prod. signals</th>
                <th className="py-2 pr-4 text-right">Recall</th>
                <th className="py-2 text-right">Precision</th>
              </tr>
            </thead>
            <tbody>
              {perCategory.map(([cat, m]) => (
                <tr key={cat} className="border-b border-border/60 last:border-0">
                  <td className="py-2 pr-4 font-mono text-text-primary">{cat}</td>
                  <td className="py-2 pr-4 text-text-dim">{m.severity}</td>
                  <td className="py-2 pr-4 text-right font-mono text-text-dim">{m.n_production_signals}</td>
                  <td className="py-2 pr-4 text-right">
                    <span className={`inline-block px-2 py-0.5 rounded font-mono ${recallCellClass(m.recall)}`}>
                      {pct(m.recall)}
                    </span>
                  </td>
                  <td className="py-2 text-right font-mono text-text-dim">{pct(m.precision)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* RQ2 coverage gaps */}
      <SectionCard title="RQ2 · Coverage gaps">
        {results.rq2_coverage_gaps.gaps.length === 0 ? (
          <p className="text-sm text-text-muted">No coverage gaps below the recall threshold.</p>
        ) : (
          <div className="space-y-3">
            {results.rq2_coverage_gaps.gaps.map((g) => (
              <div key={g.category} className="p-3 bg-bg-card border border-border rounded-lg">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm text-pearl">{g.category}</span>
                    <span className="text-[11px] px-2 py-0.5 rounded border bg-bg border-border text-text-muted uppercase tracking-wider">
                      {g.severity}
                    </span>
                  </div>
                  <div className="text-xs text-text-dim">
                    {g.n_production_signals} signals ·{' '}
                    <span className={`px-1.5 py-0.5 rounded font-mono ${recallCellClass(g.recall)}`}>
                      recall {pct(g.recall)}
                    </span>
                  </div>
                </div>
                {g.characterisation && (
                  <div className="mt-2 flex gap-4 flex-wrap text-[11px] text-text-muted">
                    <span>conversations: <span className="font-mono text-text-dim">{g.characterisation.n_conversations}</span></span>
                    <span>avg messages: <span className="font-mono text-text-dim">{g.characterisation.avg_message_count.toFixed(1)}</span></span>
                    <span>max messages: <span className="font-mono text-text-dim">{g.characterisation.max_message_count}</span></span>
                    <span>long-horizon: <span className="font-mono text-text-dim">{pct(g.characterisation.long_horizon_share, 0)}</span></span>
                    <span>escalated: <span className="font-mono text-text-dim">{pct(g.characterisation.escalated_share, 0)}</span></span>
                    <span>avg failure score: <span className="font-mono text-text-dim">{g.characterisation.avg_failure_score.toFixed(2)}</span></span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {CHART_NAMES.map((c) => (
          <ChartImage key={`${runId}-${c.name}`} runId={runId} name={c.name} label={c.label} />
        ))}
      </div>
    </div>
  )
}

// ---------- Page ----------

export default function Research() {
  // 1. Anonymize
  const [inputPath, setInputPath] = useState(DEFAULT_INPUT_PATH)
  const [outputPath, setOutputPath] = useState(DEFAULT_ANON_PATH)
  const [anonRun, setAnonRun] = useState<ResearchRun | null>(null)
  const [anonError, setAnonError] = useState('')
  const [anonStarting, setAnonStarting] = useState(false)

  // 2. Ground truth preview
  const [gtExportPath, setGtExportPath] = useState(DEFAULT_ANON_PATH)
  const [minScore, setMinScore] = useState(3.0)
  const [gtPreview, setGtPreview] = useState<GroundTruthPreview | null>(null)
  const [gtLoading, setGtLoading] = useState(false)
  const [gtError, setGtError] = useState('')

  // 3. Experiment
  const [expExportPath, setExpExportPath] = useState(DEFAULT_ANON_PATH)
  const [agentMapPath, setAgentMapPath] = useState(DEFAULT_AGENT_MAP)
  const [budget, setBudget] = useState(100)
  const [holdoutFraction, setHoldoutFraction] = useState(0.3)
  const [mode, setMode] = useState<'static' | 'execute'>('static')
  const [connector, setConnector] = useState('')
  const [expRun, setExpRun] = useState<ResearchRun | null>(null)
  const [expError, setExpError] = useState('')
  const [expStarting, setExpStarting] = useState(false)

  // Results
  const [results, setResults] = useState<ResearchResults | null>(null)
  const [resultsRunId, setResultsRunId] = useState<string | null>(null)

  // Run history
  const [runs, setRuns] = useState<ResearchRun[]>([])
  const [runsError, setRunsError] = useState('')

  const refreshRuns = useCallback(() => {
    listResearchRuns()
      .then((r) => { setRuns(r.runs); setRunsError('') })
      .catch((e) => setRunsError(String(e)))
  }, [])

  useEffect(() => { refreshRuns() }, [refreshRuns])

  // Poll anonymize run
  useEffect(() => {
    if (!anonRun || anonRun.status !== 'running') return
    const t = setInterval(() => {
      getResearchRun(anonRun.run_id)
        .then((r) => {
          setAnonRun(r)
          if (r.status !== 'running') refreshRuns()
        })
        .catch(() => {})
    }, 1500)
    return () => clearInterval(t)
  }, [anonRun, refreshRuns])

  // Poll experiment run
  useEffect(() => {
    if (!expRun || expRun.status !== 'running') return
    const t = setInterval(() => {
      getResearchRun(expRun.run_id)
        .then((r) => {
          setExpRun(r)
          if (r.status !== 'running') {
            refreshRuns()
            if (r.status === 'completed' && r.results) {
              setResults(r.results)
              setResultsRunId(r.run_id)
            }
          }
        })
        .catch(() => {})
    }, 1500)
    return () => clearInterval(t)
  }, [expRun, refreshRuns])

  const handleAnonymize = async () => {
    setAnonError('')
    setAnonStarting(true)
    try {
      const { run_id } = await runResearchAnonymize({ input_path: inputPath, output_path: outputPath })
      setAnonRun(await getResearchRun(run_id))
      refreshRuns()
    } catch (e) {
      setAnonError(String(e))
    } finally {
      setAnonStarting(false)
    }
  }

  const handlePreview = async () => {
    setGtError('')
    setGtLoading(true)
    setGtPreview(null)
    try {
      setGtPreview(await previewGroundTruth(gtExportPath, minScore))
    } catch (e) {
      setGtError(String(e))
    } finally {
      setGtLoading(false)
    }
  }

  const handleRunExperiment = async () => {
    setExpError('')
    setExpStarting(true)
    try {
      const { run_id } = await runResearchExperiment({
        export_path: expExportPath,
        agent_map_path: agentMapPath,
        budget,
        holdout_fraction: holdoutFraction,
        min_score: minScore,
        mode,
        ...(mode === 'execute' && connector ? { connector } : {}),
      })
      setExpRun(await getResearchRun(run_id))
      refreshRuns()
    } catch (e) {
      setExpError(String(e))
    } finally {
      setExpStarting(false)
    }
  }

  const handleSelectRun = async (run: ResearchRun) => {
    if (run.kind !== 'experiment' || run.status !== 'completed') return
    try {
      const full = await getResearchRun(run.run_id)
      if (full.results) {
        setResults(full.results)
        setResultsRunId(full.run_id)
      }
    } catch (e) {
      setRunsError(String(e))
    }
  }

  const gtMaxCount = gtPreview ? Math.max(1, ...Object.values(gtPreview.by_category)) : 1

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-pearl">Research</h1>
        <p className="text-sm text-smoke mt-0.5">
          Offline research workflow: anonymize a production export, preview ground truth, run RQ1–RQ4 experiments
        </p>
      </div>

      {/* 1. Anonymize */}
      <SectionCard title="1 · Anonymize export">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Field label="Input path">
            <input className={inputClass} value={inputPath} onChange={(e) => setInputPath(e.target.value)} />
          </Field>
          <Field label="Output path">
            <input className={inputClass} value={outputPath} onChange={(e) => setOutputPath(e.target.value)} />
          </Field>
        </div>
        {anonError && <ErrorBox message={anonError} />}
        <div className="flex items-center gap-3">
          <button
            onClick={handleAnonymize}
            disabled={anonStarting || anonRun?.status === 'running'}
            className="px-5 py-2 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {anonRun?.status === 'running' ? 'Anonymizing...' : 'Run Anonymization'}
          </button>
          {anonRun && <RunStatusPill status={anonRun.status} />}
        </div>
        {anonRun && anonRun.status === 'running' && <ProgressFeed run={anonRun} />}
        {anonRun?.status === 'completed' && (
          <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
            Anonymization complete.
            {anonRun.output_dir && <span className="font-mono"> Output: {anonRun.output_dir}</span>}
            {anonRun.progress.length > 0 && (
              <div className="text-xs text-green-600/80 mt-1">{anonRun.progress[anonRun.progress.length - 1].message}</div>
            )}
          </div>
        )}
        {anonRun?.status === 'error' && <ErrorBox message={anonRun.error || 'Anonymization failed'} />}
      </SectionCard>

      {/* 2. Ground truth preview */}
      <SectionCard title="2 · Ground truth preview">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <Field label="Export path">
              <input className={inputClass} value={gtExportPath} onChange={(e) => setGtExportPath(e.target.value)} />
            </Field>
          </div>
          <Field label="Min failure score">
            <input
              type="number" step="0.5" min="0"
              className={inputClass}
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
            />
          </Field>
        </div>
        {gtError && <ErrorBox message={gtError} />}
        <button
          onClick={handlePreview}
          disabled={gtLoading}
          className="px-5 py-2 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          {gtLoading ? 'Loading...' : 'Preview Ground Truth'}
        </button>

        {gtPreview && (
          <div className="space-y-4">
            <div className="flex gap-6 text-sm text-text-dim flex-wrap">
              <span>Conversations analysed: <strong className="text-pearl font-mono">{gtPreview.n_conversations_analysed}</strong></span>
              <span>Failures: <strong className="text-pearl font-mono">{gtPreview.n_failures}</strong></span>
              <span>Min score: <strong className="text-pearl font-mono">{gtPreview.min_score}</strong></span>
            </div>

            {/* Per-category bars */}
            <div className="space-y-1.5">
              <div className="text-xs text-text-muted uppercase tracking-wider mb-2">Failures by production category</div>
              {Object.entries(gtPreview.by_category)
                .sort((a, b) => b[1] - a[1])
                .map(([cat, count]) => (
                  <div key={cat} className="flex items-center gap-3">
                    <div className="w-44 text-xs font-mono text-text-dim truncate shrink-0">{cat}</div>
                    <div className="flex-1 h-4 bg-bg-card rounded overflow-hidden">
                      <div
                        className="h-full bg-accent/70 rounded"
                        style={{ width: `${(count / gtMaxCount) * 100}%` }}
                      />
                    </div>
                    <div className="w-12 text-right text-xs font-mono text-pearl shrink-0">{count}</div>
                  </div>
                ))}
            </div>

            {/* Worst conversations */}
            <div>
              <div className="text-xs text-text-muted uppercase tracking-wider mb-2">Top 10 worst conversations</div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] text-text-muted uppercase tracking-wider border-b border-border">
                      <th className="py-2 pr-4">Conversation</th>
                      <th className="py-2 pr-4 text-right">Score</th>
                      <th className="py-2 pr-4">Categories</th>
                      <th className="py-2 text-right">Messages</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gtPreview.worst.slice(0, 10).map((w) => (
                      <tr key={w.conversation_id} className="border-b border-border/60 last:border-0">
                        <td className="py-2 pr-4 font-mono text-xs text-text-primary">{w.conversation_id}</td>
                        <td className="py-2 pr-4 text-right font-mono text-pearl">{w.failure_score.toFixed(1)}</td>
                        <td className="py-2 pr-4">
                          <div className="flex flex-wrap gap-1">
                            {w.production_categories.map((c) => (
                              <span key={c} className="px-1.5 py-0.5 text-[10px] font-mono bg-bg-card border border-border rounded text-text-dim">
                                {c}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-2 text-right font-mono text-text-dim">{w.message_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </SectionCard>

      {/* 3. Run experiment */}
      <SectionCard title="3 · Run experiment">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Field label="Export path">
            <input className={inputClass} value={expExportPath} onChange={(e) => setExpExportPath(e.target.value)} />
          </Field>
          <Field label="Agent map path">
            <input className={inputClass} value={agentMapPath} onChange={(e) => setAgentMapPath(e.target.value)} />
          </Field>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Field label="Budget">
            <input
              type="number" min="1"
              className={inputClass}
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
            />
          </Field>
          <Field label="Holdout fraction">
            <input
              type="number" step="0.05" min="0" max="0.9"
              className={inputClass}
              value={holdoutFraction}
              onChange={(e) => setHoldoutFraction(Number(e.target.value))}
            />
          </Field>
          <Field label="Mode">
            <select
              className={inputClass}
              value={mode}
              onChange={(e) => setMode(e.target.value as 'static' | 'execute')}
            >
              <option value="static">static</option>
              <option value="execute">execute</option>
            </select>
          </Field>
          {mode === 'execute' && (
            <Field label="Connector">
              <input
                className={inputClass}
                value={connector}
                placeholder="e.g. mock"
                onChange={(e) => setConnector(e.target.value)}
              />
            </Field>
          )}
        </div>
        {mode === 'static' && (
          <p className="text-xs text-text-muted">{STATIC_MODE_CAVEAT}</p>
        )}
        {expError && <ErrorBox message={expError} />}
        <div className="flex items-center gap-3">
          <button
            onClick={handleRunExperiment}
            disabled={expStarting || expRun?.status === 'running'}
            className="px-5 py-2 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {expRun?.status === 'running' ? 'Running...' : 'Run Experiment'}
          </button>
          {expRun && <RunStatusPill status={expRun.status} />}
        </div>
        {expRun && expRun.status === 'running' && <ProgressFeed run={expRun} />}
        {expRun?.status === 'error' && <ErrorBox message={expRun.error || 'Experiment failed'} />}
      </SectionCard>

      {/* Results */}
      {results && resultsRunId && <ResultsSection results={results} runId={resultsRunId} />}

      {/* Run history */}
      <SectionCard title="Run history">
        <div className="flex items-center justify-between -mt-2">
          <p className="text-xs text-text-muted">Click a completed experiment run to load its results above.</p>
          <button
            onClick={refreshRuns}
            className="px-3 py-1.5 text-xs border border-border rounded-lg text-text-dim hover:bg-bg-card hover:text-text-primary transition-colors"
          >
            Refresh
          </button>
        </div>
        {runsError && <ErrorBox message={runsError} />}
        {runs.length === 0 ? (
          <p className="text-sm text-text-muted">No runs yet.</p>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => {
              const clickable = run.kind === 'experiment' && run.status === 'completed'
              const selected = run.run_id === resultsRunId
              return (
                <button
                  key={run.run_id}
                  onClick={() => handleSelectRun(run)}
                  disabled={!clickable}
                  className={`w-full flex items-center gap-3 p-3 rounded-lg border text-left transition-colors ${
                    selected
                      ? 'bg-accent/5 border-accent/40'
                      : 'bg-bg-card border-border'
                  } ${clickable ? 'hover:border-accent/40 cursor-pointer' : 'cursor-default'}`}
                >
                  <RunStatusPill status={run.status} />
                  <span className="text-[11px] px-2 py-0.5 rounded border bg-bg border-border text-text-muted uppercase tracking-wider shrink-0">
                    {run.kind}
                  </span>
                  <span className="font-mono text-xs text-text-primary truncate">{run.run_id}</span>
                  <span className="text-xs text-text-muted ml-auto shrink-0">
                    {run.started_at ? new Date(run.started_at).toLocaleString() : ''}
                  </span>
                  {run.error && <span className="text-xs text-red-600 truncate max-w-[200px]">{run.error}</span>}
                </button>
              )
            })}
          </div>
        )}
      </SectionCard>
    </div>
  )
}
