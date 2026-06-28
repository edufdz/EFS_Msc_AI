import type { CertificationConfidence } from '../../api/types'

interface ConfidenceMeterProps {
  confidence: CertificationConfidence
  overallScore: number
}

export default function ConfidenceMeter({ confidence, overallScore }: ConfidenceMeterProps) {
  const low = Math.max(0, overallScore - confidence.margin_of_error)
  const high = Math.min(100, overallScore + confidence.margin_of_error)

  // Tier boundaries
  const tiers = [
    { label: 'Not Certified', min: 0, max: 60, color: '#FEE2E2', border: '#EF4444' },
    { label: 'Silver', min: 60, max: 75, color: '#F3F4F6', border: '#9CA3AF' },
    { label: 'Gold', min: 75, max: 90, color: '#FEF3C7', border: '#F59E0B' },
    { label: 'Platinum', min: 90, max: 100, color: '#DBEAFE', border: '#3B82F6' },
  ]

  const samplePct = Math.min(100, (confidence.total_simulations / 100) * 100)

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-medium text-pearl">Confidence Analysis</h3>

      {/* Score range visualization */}
      <div className="p-4 bg-bg-surface border border-border rounded-lg space-y-3">
        <div className="flex items-center justify-between text-sm">
          <span className="text-text-dim">Score Range (95% CI)</span>
          <span className="font-mono text-pearl font-medium">{low.toFixed(1)} - {high.toFixed(1)}</span>
        </div>

        <div className="relative h-8 rounded-lg overflow-hidden">
          {/* Tier zones */}
          {tiers.map((t) => (
            <div key={t.label}
              className="absolute top-0 h-full"
              style={{
                left: `${t.min}%`,
                width: `${t.max - t.min}%`,
                backgroundColor: t.color,
                borderRight: t.max < 100 ? `1px dashed ${t.border}` : 'none',
              }}
            />
          ))}

          {/* Confidence interval bar */}
          <div className="absolute top-1.5 h-5 rounded-full bg-accent/30 border border-accent"
            style={{ left: `${low}%`, width: `${high - low}%` }}
          />

          {/* Point estimate marker */}
          <div className="absolute top-0 h-full w-0.5 bg-pearl"
            style={{ left: `${overallScore}%` }}
          />
          <div className="absolute -top-1 w-3 h-3 rounded-full bg-pearl border-2 border-white shadow"
            style={{ left: `${overallScore}%`, transform: 'translateX(-50%)' }}
          />
        </div>

        {/* Tier labels */}
        <div className="relative h-4 text-[10px] text-text-muted">
          {tiers.map((t) => (
            <span key={t.label} className="absolute" style={{ left: `${(t.min + t.max) / 2}%`, transform: 'translateX(-50%)' }}>
              {t.label}
            </span>
          ))}
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-3">
        <div className="p-3 bg-bg-surface border border-border rounded-lg">
          <div className="text-xs text-text-muted mb-1">Simulations</div>
          <div className="text-xl font-bold text-pearl font-mono">{confidence.total_simulations}</div>
        </div>
        <div className="p-3 bg-bg-surface border border-border rounded-lg">
          <div className="text-xs text-text-muted mb-1">Confidence Level</div>
          <div className="text-xl font-bold text-pearl font-mono">{confidence.confidence_level.toFixed(1)}%</div>
        </div>
        <div className="p-3 bg-bg-surface border border-border rounded-lg">
          <div className="text-xs text-text-muted mb-1">Margin of Error</div>
          <div className="text-xl font-bold text-pearl font-mono">+/- {confidence.margin_of_error.toFixed(1)}%</div>
        </div>
        <div className="p-3 bg-bg-surface border border-border rounded-lg">
          <div className="text-xs text-text-muted mb-1">Sample Sufficiency</div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 bg-bg-card rounded-full overflow-hidden">
              <div className={`h-full rounded-full transition-all ${samplePct >= 100 ? 'bg-green-500' : samplePct >= 50 ? 'bg-yellow-500' : 'bg-red-500'}`}
                style={{ width: `${Math.min(100, samplePct)}%` }} />
            </div>
            <span className={`text-xs font-medium ${confidence.sample_sufficient ? 'text-green-600' : 'text-yellow-600'}`}>
              {confidence.sample_sufficient ? 'Sufficient' : 'Needs more'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
