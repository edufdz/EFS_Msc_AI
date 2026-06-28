import { useStore } from '../../store'
import SimulationCards from './SimulationCards'
import EventFeed from './EventFeed'
import FailureInbox from './FailureInbox'

export default function LiveMonitor() {
  const totalTests = useStore((s) => s.totalTests)
  const completedTests = useStore((s) => s.completedTests)
  const passedTests = useStore((s) => s.passedTests)
  const failedTests = useStore((s) => s.failedTests)
  const errorTests = useStore((s) => s.errorTests)
  const timeoutTests = useStore((s) => s.timeoutTests)
  const passRate = useStore((s) => s.passRate)
  const totalCost = useStore((s) => s.totalCost)
  const toolsCalled = useStore((s) => s.toolsCalled)
  const allTools = useStore((s) => s.allTools)

  const progressPct = totalTests > 0 ? (completedTests / totalTests) * 100 : 0

  return (
    <div className="flex h-full gap-0 -m-6">
      {/* Left Panel — Stats */}
      <div className="w-[280px] min-w-[280px] border-r border-border p-4 overflow-y-auto">
        {/* Progress bar */}
        <div className="mb-5">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted mb-2">Progress</div>
          <div className="h-1 bg-border rounded-full overflow-hidden mb-1.5">
            <div
              className="h-full bg-platinum rounded-full transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="text-xs font-mono text-smoke">
            {completedTests} / {totalTests}
          </div>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-2 gap-2 mb-4">
          <StatCard label="Passed" value={passedTests} color="emerald" />
          <StatCard label="Failed" value={failedTests} color="red" />
          <StatCard label="Errors" value={errorTests} color="amber" />
          <StatCard label="Timeouts" value={timeoutTests} color="yellow" />
        </div>

        {/* Pass rate */}
        <div className="text-center mb-5">
          <div className={`text-4xl font-bold font-mono tabular-nums ${passRate >= 80 ? 'text-pearl' : passRate >= 50 ? 'text-smoke' : 'text-text-muted'}`}>
            {passRate.toFixed(1)}%
          </div>
          <div className="text-[11px] text-text-muted uppercase tracking-wider">Pass Rate</div>
        </div>

        {/* Tool coverage */}
        <div className="mb-4">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted mb-2">Tool Coverage</div>
          <div className="space-y-1">
            {allTools.map((tool) => (
              <div key={tool} className="flex items-center gap-2 text-xs font-mono">
                <span className={`w-1.5 h-1.5 rounded-full transition-colors ${toolsCalled.has(tool) ? 'bg-pearl' : 'bg-graphite'}`} />
                <span className={toolsCalled.has(tool) ? 'text-pearl' : 'text-text-muted'}>{tool}</span>
              </div>
            ))}
          </div>
          <div className="text-xs text-text-muted mt-2 pt-2 border-t border-border">
            {toolsCalled.size}/{allTools.length} tools covered
          </div>
        </div>

        {/* Cost & Duration */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs">
            <span className="text-text-muted">Cost</span>
            <span className="font-mono text-pearl tabular-nums">${totalCost.toFixed(4)}</span>
          </div>
        </div>
      </div>

      {/* Center Panel — Simulations */}
      <div className="flex-1 min-w-0 overflow-y-auto p-4">
        <SimulationCards />
      </div>

      {/* Right Panel — Events & Failures */}
      <div className="w-[340px] min-w-[340px] border-l border-border flex flex-col">
        <div className="flex-1 overflow-y-auto p-4">
          <EventFeed />
        </div>
        <div className="border-t border-border overflow-y-auto p-4 max-h-[40%]">
          <FailureInbox />
        </div>
      </div>
    </div>
  )
}

const statCardStyles: Record<string, { border: string; bg: string; bgActive: string }> = {
  emerald: { border: 'border-l-emerald-500', bg: 'bg-emerald-500/5', bgActive: 'bg-emerald-500/10' },
  red:     { border: 'border-l-red-500',     bg: 'bg-red-500/5',     bgActive: 'bg-red-500/10' },
  amber:   { border: 'border-l-amber-500',   bg: 'bg-amber-500/5',   bgActive: 'bg-amber-500/10' },
  yellow:  { border: 'border-l-yellow-500',  bg: 'bg-yellow-500/5',  bgActive: 'bg-yellow-500/10' },
}

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  const style = statCardStyles[color]
  const bgClass = value > 0 ? style.bgActive : style.bg
  return (
    <div className={`border border-border border-l-4 ${style.border} ${bgClass} rounded-lg p-3 text-center`}>
      <div className="text-2xl font-bold font-mono text-pearl tabular-nums">{value}</div>
      <div className="text-[11px] text-text-muted uppercase tracking-wider">{label}</div>
    </div>
  )
}
