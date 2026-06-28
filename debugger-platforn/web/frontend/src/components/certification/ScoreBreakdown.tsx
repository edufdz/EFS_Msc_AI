import { useState } from 'react'
import type { CertificationCategoryScore } from '../../api/types'

interface ScoreBreakdownProps {
  categories: CertificationCategoryScore[]
}

const CATEGORY_ICONS: Record<string, string> = {
  'Safety & Trust': 'shield',
  'Reliability': 'activity',
  'Tool Competency': 'wrench',
  'Conversation Quality': 'message',
  'Efficiency': 'zap',
}

function getScoreColor(score: number) {
  if (score >= 85) return { bar: 'bg-green-500', text: 'text-green-600', bg: 'bg-green-50', border: 'border-green-200' }
  if (score >= 70) return { bar: 'bg-yellow-500', text: 'text-yellow-600', bg: 'bg-yellow-50', border: 'border-yellow-200' }
  if (score >= 50) return { bar: 'bg-orange-500', text: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-200' }
  return { bar: 'bg-red-500', text: 'text-red-600', bg: 'bg-red-50', border: 'border-red-200' }
}

function IconSvg({ name }: { name: string }) {
  const paths: Record<string, string> = {
    shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
    activity: 'M22 12h-4l-3 9L9 3l-3 9H2',
    wrench: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z',
    message: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
    zap: 'M13 2L3 14h9l-1 10 10-12h-9l1-10z',
  }
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={paths[name] || paths.activity} />
    </svg>
  )
}

export default function ScoreBreakdown({ categories }: ScoreBreakdownProps) {
  const [selected, setSelected] = useState<string | null>(null)

  // Sort by weight descending
  const sorted = [...categories].sort((a, b) => b.weight - a.weight)
  const selectedCat = sorted.find((c) => c.category === selected)

  return (
    <div className="space-y-3">
      <h3 className="text-lg font-medium text-pearl">Score Breakdown</h3>

      <div className="flex gap-4">
        {/* Bar chart panel */}
        <div className="flex-1 space-y-2">
          {sorted.map((cs) => {
            const colors = getScoreColor(cs.score)
            const isActive = selected === cs.category
            return (
              <button
                key={cs.category}
                onClick={() => setSelected(isActive ? null : cs.category)}
                className={`w-full text-left p-3 rounded-lg border transition-all ${
                  isActive ? `${colors.bg} ${colors.border}` : 'bg-white border-border hover:border-border-light'
                }`}
              >
                <div className="flex items-center gap-3 mb-2">
                  <span className={`${colors.text}`}>
                    <IconSvg name={CATEGORY_ICONS[cs.category] || 'activity'} />
                  </span>
                  <span className="text-sm font-medium text-pearl flex-1">{cs.category}</span>
                  <span className="text-xs text-text-muted">{(cs.weight * 100).toFixed(0)}% weight</span>
                  <span className={`text-sm font-mono font-bold ${colors.text}`}>{cs.score.toFixed(1)}</span>
                </div>
                <div className="h-2 bg-bg-card rounded-full overflow-hidden">
                  <div className={`h-full ${colors.bar} rounded-full transition-all duration-700`}
                    style={{ width: `${cs.score}%` }} />
                </div>
              </button>
            )
          })}
        </div>

        {/* Detail panel */}
        {selectedCat && (
          <div className="w-72 shrink-0 p-4 bg-bg-surface border border-border rounded-lg space-y-3 animate-slide-in">
            <div className="flex items-center justify-between">
              <h4 className="font-medium text-pearl text-sm">{selectedCat.category}</h4>
              <button onClick={() => setSelected(null)} className="text-text-muted hover:text-pearl text-xs">Close</button>
            </div>

            <div className="space-y-2">
              <div className="text-xs text-text-muted uppercase tracking-wider">Metrics</div>
              {Object.entries(selectedCat.breakdown).map(([key, val]) => (
                <div key={key} className="flex justify-between items-center text-sm">
                  <span className="text-text-dim">{key.replace(/_/g, ' ')}</span>
                  <span className="font-mono text-pearl">{typeof val === 'number' ? val.toFixed(2) : val}</span>
                </div>
              ))}
            </div>

            {selectedCat.notes.length > 0 && (
              <div className="space-y-1 pt-2 border-t border-border">
                <div className="text-xs text-text-muted uppercase tracking-wider">Notes</div>
                {selectedCat.notes.map((n, i) => (
                  <div key={i} className="text-xs text-text-dim leading-relaxed">
                    {n}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
