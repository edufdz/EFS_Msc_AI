import { useState } from 'react'
import type { FailureCluster, FailureExample, FixProposal, TraceData, TraceToolCall, TraceTurn } from '../../api/types'
import { getTrace } from '../../api/client'
import MinimalReproViewer from './MinimalReproViewer'

interface PriorityClusterListProps {
  clusters: FailureCluster[]
  fixProposals: FixProposal[]
  priorityRanking: string[]
  sessionId: string
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-pearl text-bg',
  high: 'bg-smoke text-bg',
  medium: 'bg-text-muted text-bg',
  low: 'bg-graphite text-smoke',
}

// --------------- Markdown export helpers ---------------

function buildClusterMarkdown(cluster: FailureCluster, fixes: FixProposal[]): string {
  const lines: string[] = []
  lines.push(`## [${cluster.severity.toUpperCase()}] Root Cause: ${cluster.root_cause_type.replace(/_/g, ' ')}`)
  lines.push('')
  lines.push(cluster.root_cause_description)
  if (cluster.common_pattern) {
    lines.push('')
    lines.push(`**Pattern:** ${cluster.common_pattern}`)
  }
  if (cluster.key_indicators.length > 0) {
    lines.push('')
    lines.push(`**Key Indicators:** ${cluster.key_indicators.join(', ')}`)
  }

  if (cluster.affected_scenarios.length > 0 || cluster.affected_tools.length > 0) {
    lines.push('')
    lines.push('### Affected Scenarios / Tools')
    for (const s of cluster.affected_scenarios) lines.push(`- ${s}`)
    for (const t of cluster.affected_tools) lines.push(`- Tool: ${t}`)
  }

  if (cluster.minimal_reproduction) {
    lines.push('')
    lines.push('### Minimal Reproduction')
    cluster.minimal_reproduction.steps.forEach((step, i) => {
      lines.push(`${i + 1}. **${step.role}**: ${step.content}`)
    })
    if (cluster.minimal_reproduction.expected_behavior) {
      lines.push('')
      lines.push(`**Expected:** ${cluster.minimal_reproduction.expected_behavior}`)
    }
    if (cluster.minimal_reproduction.actual_behavior) {
      lines.push(`**Actual:** ${cluster.minimal_reproduction.actual_behavior}`)
    }
  }

  if (cluster.failure_examples.length > 0) {
    lines.push('')
    lines.push('### Sample Failures')
    for (const ex of cluster.failure_examples.slice(0, 3)) {
      lines.push(`- **${ex.test_id}** (${ex.difficulty}): ${ex.failure_reason}`)
    }
  }

  if (fixes.length > 0) {
    lines.push('')
    lines.push('### Proposed Fixes')
    for (const fix of fixes) {
      lines.push(`- **${fix.fix_type.replace(/_/g, ' ')}** (${(fix.estimated_fix_rate * 100).toFixed(0)}% fix rate, ${fix.estimated_effort} effort): ${fix.description}`)
    }
  }

  return lines.join('\n')
}

function CopyMarkdownButton({ cluster, fixes }: { cluster: FailureCluster; fixes: FixProposal[] }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    const md = buildClusterMarkdown(cluster, fixes)
    navigator.clipboard.writeText(md).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <button
      onClick={handleCopy}
      className="p-1 rounded hover:bg-graphite/40 transition-colors duration-150"
      title="Copy as Markdown"
    >
      {copied ? (
        <svg className="w-4 h-4 text-pearl" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="w-4 h-4 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
        </svg>
      )}
    </button>
  )
}

// --------------- Trace viewer components ---------------

function ToolCallCard({ toolCall }: { toolCall: TraceToolCall }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-graphite/30 border border-border rounded-lg overflow-hidden my-1">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-graphite/50 transition-colors duration-150"
      >
        <svg className="w-3 h-3 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
        </svg>
        <span className="text-xs font-mono text-smoke">{toolCall.tool_name}</span>
        <svg
          className={`w-3 h-3 text-text-muted ml-auto transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded && (
        <div className="px-3 pb-2 space-y-1.5">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-text-muted mb-0.5">Arguments</div>
            <pre className="text-[11px] text-smoke bg-bg-surface rounded p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono">
              {JSON.stringify(toolCall.arguments, null, 2)}
            </pre>
          </div>
          {toolCall.result != null && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest text-text-muted mb-0.5">Result</div>
              <pre className="text-[11px] text-smoke bg-bg-surface rounded p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono">
                {typeof toolCall.result === 'string' ? toolCall.result : JSON.stringify(toolCall.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TraceConversation({ trace }: { trace: TraceData }) {
  const totalToolCalls = trace.turns.reduce((sum, t) => sum + (t.tool_calls?.length || 0), 0)

  return (
    <div className="space-y-2">
      {/* Header stats */}
      <div className="flex flex-wrap gap-3 text-[11px] text-text-muted px-1">
        <span>{trace.turns.length} turns</span>
        <span>{trace.duration_sec.toFixed(1)}s</span>
        <span>{totalToolCalls} tool calls</span>
        {trace.total_cost_usd > 0 && <span>${trace.total_cost_usd.toFixed(4)}</span>}
      </div>

      {/* Turn-by-turn conversation */}
      <div className="max-h-[500px] overflow-y-auto space-y-2 pr-1">
        {trace.turns.map((turn) => (
          <div key={turn.turn_number}>
            {/* Message bubble */}
            {turn.message && (
              <div className={`flex ${turn.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[85%] rounded-lg px-3 py-2 shadow-sm ${
                    turn.role === 'user'
                      ? 'bg-[#D9FDD3] text-[#111B21] rounded-br-none'
                      : 'bg-white text-[#111B21] rounded-bl-none border border-[#E9EDEF]'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1 gap-2">
                    <span className={`text-xs font-bold ${turn.role === 'user' ? 'text-[#0D8050]' : 'text-[#54656F]'}`}>
                      {turn.role === 'user' ? 'User' : 'Agent'}
                    </span>
                    <span className="text-[10px] text-[#667781] font-mono flex items-center gap-1.5">
                      Turn {turn.turn_number}
                      {turn.duration_ms > 0 && <span>{(turn.duration_ms / 1000).toFixed(1)}s</span>}
                    </span>
                  </div>
                  <div className="text-sm whitespace-pre-wrap break-words">{turn.message}</div>
                </div>
              </div>
            )}
            {/* Tool calls */}
            {turn.tool_calls && turn.tool_calls.length > 0 && (
              <div className="pl-2">
                {turn.tool_calls.map((tc, i) => (
                  <ToolCallCard key={`${turn.turn_number}-tc-${i}`} toolCall={tc} />
                ))}
              </div>
            )}
          </div>
        ))}

        {/* Failure reason footer */}
        {trace.failure_reason && (
          <div className="bg-bg-surface border border-border rounded-lg p-3 mt-2">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-text-muted mb-1">Failure Reason</div>
            <div className="text-sm text-smoke">{trace.failure_reason}</div>
          </div>
        )}
      </div>
    </div>
  )
}

function FailureExampleCard({ example, sessionId }: { example: FailureExample; sessionId: string }) {
  const [expanded, setExpanded] = useState(false)
  const [trace, setTrace] = useState<TraceData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleToggle = async () => {
    const willExpand = !expanded
    setExpanded(willExpand)

    if (willExpand && !trace && !loading && example.trace_file) {
      const filename = example.trace_file.split('/').pop()
      if (!filename) return
      setLoading(true)
      setError(null)
      try {
        const data = await getTrace(sessionId, filename)
        setTrace(data)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load trace')
      } finally {
        setLoading(false)
      }
    }
  }

  return (
    <div className="bg-bg-surface border border-border rounded-lg overflow-hidden">
      <button
        onClick={handleToggle}
        className="w-full text-left p-2.5 hover:bg-graphite/20 transition-colors duration-150"
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono text-smoke">{example.test_id}</span>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-text-muted">{example.difficulty}</span>
            {example.trace_file && (
              <svg
                className={`w-3 h-3 text-text-muted transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            )}
          </div>
        </div>
        <div className="text-xs text-text-muted mt-1 truncate">{example.scenario}</div>
        <div className="text-xs text-smoke mt-1">{example.failure_reason}</div>
      </button>

      {expanded && (
        <div className="border-t border-border p-3">
          {loading && (
            <div className="flex items-center justify-center py-6 gap-2 text-text-muted">
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" />
                <path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" className="opacity-75" />
              </svg>
              <span className="text-xs">Loading trace...</span>
            </div>
          )}
          {error && (
            <div className="text-xs text-text-muted py-4 text-center">
              {error}
            </div>
          )}
          {trace && <TraceConversation trace={trace} />}
          {!loading && !error && !trace && (
            <div className="text-xs text-text-muted py-4 text-center">
              No trace file available
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// --------------- Main components ---------------

export default function PriorityClusterList({ clusters, fixProposals, priorityRanking, sessionId }: PriorityClusterListProps) {
  const sorted = priorityRanking
    .map((id) => clusters.find((c) => c.cluster_id === id))
    .filter(Boolean) as FailureCluster[]

  // Include any clusters not in ranking
  const rankedIds = new Set(priorityRanking)
  const unranked = clusters.filter((c) => !rankedIds.has(c.cluster_id))
  const allClusters = [...sorted, ...unranked]

  if (allClusters.length === 0) return null

  return (
    <div className="space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Priority Clusters ({allClusters.length})
      </div>
      {allClusters.map((cluster, i) => (
        <ClusterCard
          key={cluster.cluster_id}
          cluster={cluster}
          rank={i + 1}
          fixes={fixProposals.filter((f) => f.cluster_id === cluster.cluster_id)}
          sessionId={sessionId}
        />
      ))}
    </div>
  )
}

function ClusterCard({
  cluster,
  rank,
  fixes,
  sessionId,
}: {
  cluster: FailureCluster
  rank: number
  fixes: FixProposal[]
  sessionId: string
}) {
  const [expanded, setExpanded] = useState(false)
  const [activeTab, setActiveTab] = useState<'reproduction' | 'failures' | 'fixes'>('reproduction')
  const severityClass = SEVERITY_COLORS[cluster.severity] || SEVERITY_COLORS.medium

  return (
    <div className="bg-bg-card border border-border rounded-lg overflow-hidden">
      {/* Collapsed header */}
      <div className="flex items-center">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex-1 flex items-center gap-3 px-4 py-3 text-left hover:bg-graphite/20 transition-colors duration-150"
        >
          <span className="text-sm font-mono tabular-nums text-text-muted w-6">#{rank}</span>
          <span className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded ${severityClass}`}>
            {cluster.severity}
          </span>
          <span className="text-sm text-pearl font-medium flex-1 truncate">
            {cluster.root_cause_type.replace(/_/g, ' ')}
          </span>
          <span className="text-xs font-mono tabular-nums text-smoke">
            {cluster.failure_count} failures
          </span>
          <svg
            className={`w-4 h-4 text-text-muted transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        <CopyMarkdownButton cluster={cluster} fixes={fixes} />
        <div className="w-2" />
      </div>

      {/* Expanded content */}
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-border">
          {/* Description & pattern */}
          <div className="pt-3 space-y-2">
            <p className="text-sm text-smoke">{cluster.root_cause_description}</p>
            {cluster.common_pattern && (
              <div className="text-xs text-text-muted">
                <span className="font-semibold">Pattern:</span> {cluster.common_pattern}
              </div>
            )}
          </div>

          {/* Key indicators */}
          {cluster.key_indicators.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {cluster.key_indicators.map((ind, i) => (
                <span key={i} className="text-[11px] px-2 py-0.5 rounded bg-graphite text-smoke font-mono">
                  {ind}
                </span>
              ))}
            </div>
          )}

          {/* Affected scenarios & tools */}
          <div className="flex flex-wrap gap-3 text-[11px] text-text-muted">
            {cluster.affected_scenarios.length > 0 && (
              <span>{cluster.affected_scenarios.length} scenarios affected</span>
            )}
            {cluster.affected_tools.length > 0 && (
              <span>{cluster.affected_tools.length} tools affected</span>
            )}
          </div>

          {/* Tabs */}
          <div className="flex gap-4 border-b border-border">
            {(['reproduction', 'failures', 'fixes'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`pb-2 text-xs font-medium capitalize transition-colors duration-150 border-b-2 ${
                  activeTab === tab
                    ? 'border-platinum text-pearl'
                    : 'border-transparent text-text-muted hover:text-smoke'
                }`}
              >
                {tab === 'fixes' ? `Fixes (${fixes.length})` : tab === 'failures' ? `Failures (${cluster.failure_examples.length})` : 'Reproduction'}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="pt-1">
            {activeTab === 'reproduction' && (
              cluster.minimal_reproduction ? (
                <MinimalReproViewer reproduction={cluster.minimal_reproduction} />
              ) : (
                <div className="text-sm text-text-muted py-4 text-center">
                  No minimal reproduction available
                </div>
              )
            )}

            {activeTab === 'failures' && (
              <div className="space-y-2 max-h-[600px] overflow-y-auto">
                {cluster.failure_examples.map((ex) => (
                  <FailureExampleCard key={ex.test_id} example={ex} sessionId={sessionId} />
                ))}
              </div>
            )}

            {activeTab === 'fixes' && (
              fixes.length > 0 ? (
                <div className="space-y-2">
                  {fixes.map((fix) => (
                    <FixPreview key={fix.fix_id} fix={fix} />
                  ))}
                </div>
              ) : (
                <div className="text-sm text-text-muted py-4 text-center">
                  No fix proposals for this cluster
                </div>
              )
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function FixPreview({ fix }: { fix: FixProposal }) {
  const effortColors: Record<string, string> = {
    low: 'bg-pearl/10 text-pearl',
    medium: 'bg-smoke/10 text-smoke',
    high: 'bg-text-muted/10 text-text-muted',
  }
  const riskColors: Record<string, string> = {
    low: 'text-pearl',
    medium: 'text-smoke',
    high: 'text-text-muted',
  }

  return (
    <div className="bg-bg-surface border border-border rounded-lg p-3 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-graphite text-smoke">
          {fix.fix_type.replace(/_/g, ' ')}
        </span>
        <span className="text-xs font-mono tabular-nums text-pearl">
          {(fix.estimated_fix_rate * 100).toFixed(0)}% fix rate
        </span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${effortColors[fix.estimated_effort] || ''}`}>
          {fix.estimated_effort} effort
        </span>
        <span className={`text-[10px] ${riskColors[fix.risk_level] || ''}`}>
          {fix.risk_level} risk
        </span>
      </div>
      <p className="text-sm text-smoke">{fix.description}</p>
    </div>
  )
}
