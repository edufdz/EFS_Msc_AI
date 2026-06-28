import type { PhaseDResult } from '../../api/types'

interface TriageSummaryBarProps {
  result: PhaseDResult
}

export default function TriageSummaryBar({ result }: TriageSummaryBarProps) {
  const { summary, clusters, fix_proposals } = result

  // Calculate estimated improvement
  const totalFailures = summary.total_failures_analyzed
  const totalTests = summary.total_tests || 1
  const currentPassRate = 100 - summary.failure_rate

  let estimatedFixedFailures = 0
  for (const cluster of clusters) {
    const clusterFixes = fix_proposals.filter((f) => f.cluster_id === cluster.cluster_id)
    const bestFixRate = clusterFixes.length > 0
      ? Math.max(...clusterFixes.map((f) => f.estimated_fix_rate))
      : 0
    estimatedFixedFailures += cluster.failure_count * bestFixRate
  }
  const estimatedImprovement = totalTests > 0
    ? (estimatedFixedFailures / totalTests) * 100
    : 0

  // Top root cause
  const rootCauseEntries = Object.entries(summary.by_root_cause)
  rootCauseEntries.sort((a, b) => b[1] - a[1])
  const topRootCause = rootCauseEntries.length > 0
    ? rootCauseEntries[0][0].replace(/_/g, ' ')
    : 'N/A'

  const cards = [
    // Row 1: Core stats
    { label: 'Failures Analyzed', value: String(totalFailures), sub: `of ${totalTests} tests` },
    { label: 'Failure Rate', value: `${summary.failure_rate.toFixed(1)}%`, sub: `${totalFailures} failures` },
    { label: 'Top Root Cause', value: topRootCause, sub: `${rootCauseEntries[0]?.[1] || 0} clusters` },
    // Row 2: Performance metrics
    { label: 'Bug Discovery', value: summary.bug_discovery_rate != null ? `${summary.bug_discovery_rate.toFixed(1)}%` : '--', sub: 'unique bugs per test' },
    { label: 'Redundancy', value: summary.redundancy_rate != null ? `${summary.redundancy_rate.toFixed(1)}%` : '--', sub: 'duplicate failures' },
    { label: 'Severity Score', value: summary.severity_weighted_score != null ? summary.severity_weighted_score.toFixed(2) : '--', sub: 'weighted avg (1-5)' },
    // Row 3: Actionable
    { label: 'Clusters Found', value: String(summary.clusters_count), sub: 'failure groups' },
    { label: 'Fix Proposals', value: String(summary.fixes_count), sub: 'actionable fixes' },
    { label: 'Est. Improvement', value: `+${estimatedImprovement.toFixed(1)}%`, sub: `to ~${(currentPassRate + estimatedImprovement).toFixed(1)}%` },
  ]

  return (
    <div className="grid grid-cols-3 gap-3">
      {cards.map((card) => (
        <div key={card.label} className="bg-bg-card border border-border rounded-lg p-3">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
            {card.label}
          </div>
          <div className="text-xl font-mono tabular-nums text-pearl mt-1">
            {card.value}
          </div>
          <div className="text-[11px] text-text-muted mt-0.5">{card.sub}</div>
        </div>
      ))}
    </div>
  )
}
