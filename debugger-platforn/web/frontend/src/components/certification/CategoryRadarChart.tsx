import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip } from 'recharts'

interface CategoryRadarChartProps {
  data: Record<string, number>
  tier: string
}

const TIER_COLORS: Record<string, string> = {
  platinum: '#3B82F6',
  gold: '#F59E0B',
  silver: '#9CA3AF',
  not_certified: '#EF4444',
}

const THRESHOLD_TIERS = [
  { name: 'Platinum', value: 90, color: '#3B82F6', opacity: 0.08 },
  { name: 'Gold', value: 75, color: '#F59E0B', opacity: 0.08 },
  { name: 'Silver', value: 60, color: '#9CA3AF', opacity: 0.08 },
]

const SHORT_LABELS: Record<string, string> = {
  'Safety & Trust': 'Safety',
  'Reliability': 'Reliability',
  'Tool Competency': 'Tools',
  'Conversation Quality': 'Conversation',
  'Efficiency': 'Efficiency',
}

export default function CategoryRadarChart({ data, tier }: CategoryRadarChartProps) {
  const color = TIER_COLORS[tier] || TIER_COLORS.not_certified
  const chartData = Object.entries(data).map(([key, value]) => ({
    category: SHORT_LABELS[key] || key,
    fullName: key,
    score: value,
    platinum: 90,
    gold: 75,
    silver: 60,
  }))

  return (
    <div className="w-full">
      <div className="flex items-center gap-4 mb-2">
        <h3 className="text-lg font-medium text-pearl">Performance Radar</h3>
        <div className="flex items-center gap-3 text-xs text-text-muted">
          {THRESHOLD_TIERS.map((t) => (
            <span key={t.name} className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: t.color }} />
              {t.name} ({t.value})
            </span>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <RadarChart cx="50%" cy="50%" outerRadius="75%" data={chartData}>
          <PolarGrid stroke="#E2E8F0" />
          <PolarAngleAxis
            dataKey="category"
            tick={{ fontSize: 12, fill: '#475569' }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 100]}
            tick={{ fontSize: 10, fill: '#94A3B8' }}
            tickCount={6}
          />

          {/* Threshold reference areas */}
          <Radar name="Platinum" dataKey="platinum" stroke="#3B82F6" fill="#3B82F6"
            fillOpacity={0.05} strokeOpacity={0.3} strokeDasharray="4 4" />
          <Radar name="Gold" dataKey="gold" stroke="#F59E0B" fill="#F59E0B"
            fillOpacity={0.05} strokeOpacity={0.3} strokeDasharray="4 4" />
          <Radar name="Silver" dataKey="silver" stroke="#9CA3AF" fill="#9CA3AF"
            fillOpacity={0.05} strokeOpacity={0.3} strokeDasharray="4 4" />

          {/* Actual score */}
          <Radar name="Score" dataKey="score" stroke={color} fill={color}
            fillOpacity={0.2} strokeWidth={2} dot={{ r: 4, fill: color }} />

          <Tooltip
            content={({ payload }) => {
              if (!payload?.length) return null
              const d = payload[0].payload
              return (
                <div className="bg-white border border-border rounded-lg shadow-lg p-3 text-sm">
                  <div className="font-medium text-pearl">{d.fullName}</div>
                  <div className="text-text-dim mt-1">Score: <span className="font-mono font-bold">{d.score.toFixed(1)}</span></div>
                  <div className="text-text-muted text-xs mt-1">
                    {d.score >= 90 ? 'Platinum level' : d.score >= 75 ? 'Gold level' : d.score >= 60 ? 'Silver level' : 'Below certification'}
                  </div>
                </div>
              )
            }}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  )
}
