import { useState } from 'react'
import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, ZAxis, Cell } from 'recharts'
import type { FixProposal, FailureCluster } from '../../api/types'

interface FixRoadmapProps {
  fixProposals: FixProposal[]
  clusters: FailureCluster[]
}

const EFFORT_MAP: Record<string, number> = { low: 1, medium: 2, high: 3 }

export default function FixRoadmap({ fixProposals, clusters }: FixRoadmapProps) {
  const [expandedFix, setExpandedFix] = useState<string | null>(null)

  if (fixProposals.length === 0) return null

  // Build scatter data
  const clusterMap = new Map(clusters.map((c) => [c.cluster_id, c]))
  const scatterData = fixProposals.map((fix) => {
    const cluster = clusterMap.get(fix.cluster_id)
    return {
      x: EFFORT_MAP[fix.estimated_effort] || 2,
      y: fix.estimated_fix_rate * 100,
      z: cluster?.failure_count || 1,
      name: fix.description.slice(0, 50),
      fix_id: fix.fix_id,
      fix_type: fix.fix_type,
      effort: fix.estimated_effort,
      risk: fix.risk_level,
    }
  })

  // Sort fixes by bang-for-buck
  const sortedFixes = [...fixProposals].sort((a, b) => {
    const scoreA = a.estimated_fix_rate / (EFFORT_MAP[a.estimated_effort] || 2)
    const scoreB = b.estimated_fix_rate / (EFFORT_MAP[b.estimated_effort] || 2)
    return scoreB - scoreA
  })

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
    <div className="space-y-4">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Fix Roadmap
      </div>

      {/* Scatter chart */}
      <div className="bg-bg-card border border-border rounded-lg p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] text-text-muted">Effort vs. Fix Rate (dot size = failure count)</span>
          <span className="text-[10px] text-pearl bg-pearl/10 px-1.5 py-0.5 rounded">QUICK WINS = top-left</span>
        </div>
        <div style={{ width: '100%', height: 240 }}>
          <ResponsiveContainer>
            <ScatterChart margin={{ top: 10, right: 10, bottom: 10, left: 10 }}>
              <XAxis
                type="number"
                dataKey="x"
                domain={[0.5, 3.5]}
                ticks={[1, 2, 3]}
                tickFormatter={(v) => ['', 'Low', 'Med', 'High'][v] || ''}
                tick={{ fill: '#7A7A78', fontSize: 11 }}
                axisLine={{ stroke: '#2A2A28' }}
                tickLine={false}
                label={{ value: 'Effort', position: 'bottom', fill: '#7A7A78', fontSize: 10, offset: -5 }}
              />
              <YAxis
                type="number"
                dataKey="y"
                domain={[0, 100]}
                tick={{ fill: '#7A7A78', fontSize: 11 }}
                axisLine={{ stroke: '#2A2A28' }}
                tickLine={false}
                label={{ value: 'Fix Rate %', angle: -90, position: 'insideLeft', fill: '#7A7A78', fontSize: 10 }}
              />
              <ZAxis type="number" dataKey="z" range={[40, 200]} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#161616',
                  border: '1px solid #2A2A28',
                  borderRadius: 8,
                  fontSize: 12,
                  color: '#D7D7D2',
                }}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={((value: any, name: any) => {
                  const v = Number(value) || 0
                  const n = String(name || '')
                  if (n === 'y') return [`${v.toFixed(0)}%`, 'Fix Rate']
                  if (n === 'x') return [['', 'Low', 'Medium', 'High'][v] || '', 'Effort']
                  if (n === 'z') return [v, 'Failures']
                  return [v, n]
                }) as any}
              />
              <Scatter data={scatterData}>
                {scatterData.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={entry.x === 1 && entry.y > 50 ? '#D7D7D2' : '#9A9A96'}
                    fillOpacity={0.8}
                  />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Ordered fix cards */}
      <div className="space-y-2">
        {sortedFixes.map((fix, i) => {
          const cluster = clusterMap.get(fix.cluster_id)
          const bangForBuck = fix.estimated_fix_rate / (EFFORT_MAP[fix.estimated_effort] || 2)
          const isExpanded = expandedFix === fix.fix_id

          return (
            <div
              key={fix.fix_id}
              className="bg-bg-card border border-border rounded-lg overflow-hidden"
            >
              <button
                onClick={() => setExpandedFix(isExpanded ? null : fix.fix_id)}
                className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-graphite/20 transition-colors duration-150"
              >
                <span className="text-xs font-mono tabular-nums text-text-muted w-5">#{i + 1}</span>
                <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-graphite text-smoke">
                  {fix.fix_type.replace(/_/g, ' ')}
                </span>
                <span className="flex-1 text-sm text-pearl truncate">{fix.description}</span>
                <span className="text-xs font-mono tabular-nums text-pearl">
                  {(fix.estimated_fix_rate * 100).toFixed(0)}%
                </span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${effortColors[fix.estimated_effort] || ''}`}>
                  {fix.estimated_effort}
                </span>
                <svg
                  className={`w-3.5 h-3.5 text-text-muted transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {isExpanded && (
                <div className="px-4 pb-3 border-t border-border space-y-2 pt-3">
                  <div className="flex items-center gap-3 text-[11px] text-text-muted">
                    <span className={riskColors[fix.risk_level] || ''}>{fix.risk_level} risk</span>
                    <span>Score: {bangForBuck.toFixed(2)}</span>
                    {cluster && <span>Cluster: {cluster.root_cause_type.replace(/_/g, ' ')}</span>}
                  </div>
                  <p className="text-sm text-smoke">{fix.description}</p>
                  {fix.changes && Object.keys(fix.changes).length > 0 && (
                    <details className="text-xs">
                      <summary className="text-text-muted cursor-pointer hover:text-smoke">
                        View changes
                      </summary>
                      <pre className="mt-2 p-2 bg-bg-surface border border-border rounded text-text-muted overflow-x-auto font-mono text-[11px]">
                        {JSON.stringify(fix.changes, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
