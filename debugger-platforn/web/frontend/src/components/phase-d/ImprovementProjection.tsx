import type { PhaseDResult } from '../../api/types'

interface ImprovementProjectionProps {
  result: PhaseDResult
}

export default function ImprovementProjection({ result }: ImprovementProjectionProps) {
  const { summary, clusters, fix_proposals } = result
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

  const improvement = totalTests > 0 ? (estimatedFixedFailures / totalTests) * 100 : 0
  const projectedPassRate = Math.min(currentPassRate + improvement, 100)

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4 space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Improvement Projection
      </div>

      <div className="space-y-3">
        {/* Current */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted">Current</span>
            <span className="text-sm font-mono tabular-nums text-smoke">{currentPassRate.toFixed(1)}%</span>
          </div>
          <div className="h-4 bg-border/30 rounded-full overflow-hidden">
            <div
              className="h-full bg-text-muted rounded-full transition-all duration-700"
              style={{ width: `${currentPassRate}%` }}
            />
          </div>
        </div>

        {/* Projected */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted">Projected</span>
            <div className="flex items-center gap-2">
              <span className="text-sm font-mono tabular-nums text-pearl">~{projectedPassRate.toFixed(1)}%</span>
              {improvement > 0 && (
                <span className="text-xs font-mono text-pearl bg-pearl/10 px-1.5 py-0.5 rounded">
                  +{improvement.toFixed(1)}%
                </span>
              )}
            </div>
          </div>
          <div className="h-4 bg-border/30 rounded-full overflow-hidden">
            <div
              className="h-full bg-platinum rounded-full transition-all duration-700"
              style={{ width: `${projectedPassRate}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
