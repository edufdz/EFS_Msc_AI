import type { PhaseDResult } from '../../api/types'

interface SeverityOverviewProps {
  result: PhaseDResult
}

const SEVERITY_CONFIG: Record<string, { color: string; label: string }> = {
  critical: { color: 'bg-pearl', label: 'CRITICAL' },
  high: { color: 'bg-smoke', label: 'HIGH' },
  medium: { color: 'bg-text-muted', label: 'MEDIUM' },
  low: { color: 'bg-graphite', label: 'LOW' },
}

export default function SeverityOverview({ result }: SeverityOverviewProps) {
  const bySeverity = result.summary.by_severity
  const maxCount = Math.max(...Object.values(bySeverity), 1)
  const severityOrder = ['critical', 'high', 'medium', 'low']

  const entries = severityOrder
    .filter((s) => bySeverity[s] != null)
    .map((s) => ({ key: s, count: bySeverity[s] || 0 }))

  if (entries.length === 0) return null

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4 space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Severity Breakdown
      </div>
      <div className="space-y-2">
        {entries.map((entry) => {
          const cfg = SEVERITY_CONFIG[entry.key] || SEVERITY_CONFIG.medium
          const widthPct = (entry.count / maxCount) * 100
          return (
            <div key={entry.key} className="flex items-center gap-3">
              <span className="text-[11px] font-mono uppercase tracking-wider text-text-muted w-16 text-right">
                {cfg.label}
              </span>
              <div className="flex-1 h-5 bg-border/30 rounded overflow-hidden">
                <div
                  className={`h-full ${cfg.color} rounded transition-all duration-500`}
                  style={{ width: `${Math.max(widthPct, 4)}%` }}
                />
              </div>
              <span className="text-sm font-mono tabular-nums text-pearl w-6 text-right">
                {entry.count}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
