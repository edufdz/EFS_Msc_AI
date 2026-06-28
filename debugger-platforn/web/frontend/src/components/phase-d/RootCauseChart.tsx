import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import type { PhaseDResult } from '../../api/types'

interface RootCauseChartProps {
  result: PhaseDResult
}

export default function RootCauseChart({ result }: RootCauseChartProps) {
  const entries = Object.entries(result.summary.by_root_cause)
    .map(([name, count]) => ({ name: name.replace(/_/g, ' '), count }))
    .sort((a, b) => b.count - a.count)

  if (entries.length === 0) return null

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4 space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Root Cause Distribution
      </div>
      <div style={{ width: '100%', height: Math.max(entries.length * 36, 120) }}>
        <ResponsiveContainer>
          <BarChart data={entries} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 0 }}>
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="name"
              width={130}
              tick={{ fill: '#7A7A78', fontSize: 11, fontFamily: 'monospace' }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#161616',
                border: '1px solid #2A2A28',
                borderRadius: 8,
                fontSize: 12,
                color: '#D7D7D2',
              }}
              cursor={{ fill: 'rgba(215, 215, 210, 0.05)' }}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={20}>
              {entries.map((_, i) => (
                <Cell key={i} fill="#D7D7D2" fillOpacity={0.8} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
