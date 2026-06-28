import type { FailureCluster } from '../../api/types'

interface ToolFailureHeatmapProps {
  clusters: FailureCluster[]
}

export default function ToolFailureHeatmap({ clusters }: ToolFailureHeatmapProps) {
  // Collect all unique tools and root causes
  const toolSet = new Set<string>()
  const rootCauseSet = new Set<string>()
  const matrix: Record<string, Record<string, number>> = {}

  for (const cluster of clusters) {
    const rc = cluster.root_cause_type.replace(/_/g, ' ')
    rootCauseSet.add(rc)
    for (const tool of cluster.affected_tools) {
      toolSet.add(tool)
      if (!matrix[tool]) matrix[tool] = {}
      matrix[tool][rc] = (matrix[tool][rc] || 0) + cluster.failure_count
    }
  }

  const tools = Array.from(toolSet).sort()
  const rootCauses = Array.from(rootCauseSet).sort()

  // Only show if meaningful
  if (tools.length < 2 || rootCauses.length < 2) return null

  // Find max for opacity scaling
  let maxVal = 0
  for (const tool of tools) {
    for (const rc of rootCauses) {
      const val = matrix[tool]?.[rc] || 0
      if (val > maxVal) maxVal = val
    }
  }

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4 space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Tool x Root Cause Heatmap
      </div>

      <div className="overflow-x-auto">
        <div
          className="grid gap-px bg-border"
          style={{
            gridTemplateColumns: `120px repeat(${rootCauses.length}, minmax(80px, 1fr))`,
          }}
        >
          {/* Header row */}
          <div className="bg-bg-card p-2" />
          {rootCauses.map((rc) => (
            <div key={rc} className="bg-bg-card p-2 text-[10px] font-mono text-text-muted text-center truncate">
              {rc}
            </div>
          ))}

          {/* Data rows */}
          {tools.map((tool) => (
            <>
              <div key={`label-${tool}`} className="bg-bg-card p-2 text-[11px] font-mono text-smoke truncate">
                {tool}
              </div>
              {rootCauses.map((rc) => {
                const val = matrix[tool]?.[rc] || 0
                const opacity = maxVal > 0 ? val / maxVal : 0
                return (
                  <div
                    key={`${tool}-${rc}`}
                    className="bg-bg-card p-2 flex items-center justify-center"
                    title={`${tool} x ${rc}: ${val}`}
                  >
                    {val > 0 ? (
                      <div
                        className="w-full h-6 rounded"
                        style={{
                          backgroundColor: `rgba(215, 215, 210, ${Math.max(opacity, 0.15)})`,
                        }}
                      >
                        <div className="flex items-center justify-center h-full text-[10px] font-mono text-bg tabular-nums">
                          {val}
                        </div>
                      </div>
                    ) : (
                      <div className="w-full h-6 rounded bg-border/20" />
                    )}
                  </div>
                )
              })}
            </>
          ))}
        </div>
      </div>
    </div>
  )
}
