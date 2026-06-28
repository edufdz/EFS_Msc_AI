import type { PhaseBResult } from '../../api/types'
import StatusBadge from '../shared/StatusBadge'

interface TestSuitePreviewProps {
  result: PhaseBResult
}

export default function TestSuitePreview({ result }: TestSuitePreviewProps) {
  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3">
        <SummaryCard label="Total Tests" value={String(result.total_tests)} />
        <SummaryCard label="Personas" value={String(result.persona_count)} />
        <SummaryCard label="Scenarios" value={String(result.scenario_count)} />
        {result.tokens_used !== undefined && (
          <SummaryCard label="Tokens Used" value={result.tokens_used.toLocaleString()} sub={result.cost_usd ? `$${result.cost_usd.toFixed(4)}` : undefined} />
        )}
      </div>

      {/* Persona library */}
      {result.personas && result.personas.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
            Persona Library ({result.persona_count})
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {result.personas.map((p, i) => (
              <div key={i} className="bg-bg-card border border-border rounded-lg p-3">
                <div className="text-sm font-medium text-pearl">{p.name}</div>
                <div className="text-[11px] text-text-muted">{p.agent_type}</div>
                <div className="text-[11px] text-smoke mt-1">Source: {p.source}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Scenario catalog */}
      {result.scenarios && result.scenarios.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
            Scenario Catalog ({result.scenario_count})
          </h4>
          <div className="space-y-1">
            {result.scenarios.map((s, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2 bg-bg-card border border-border rounded-lg">
                <span className="text-sm text-pearl flex-1">{s.title}</span>
                <StatusBadge status={s.difficulty} />
                <span className="text-[11px] text-text-muted font-mono">
                  {s.required_tools.length} tools
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function SummaryCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-bg-card border border-border rounded-lg p-3">
      <div className="text-[11px] text-text-muted uppercase tracking-wider">{label}</div>
      <div className="text-lg font-bold font-mono text-pearl tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-smoke">{sub}</div>}
    </div>
  )
}
