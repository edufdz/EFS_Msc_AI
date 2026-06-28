import type { PhaseAResult } from '../../api/types'
import StatusBadge from '../shared/StatusBadge'
import JsonViewer from '../shared/JsonViewer'

interface AgentMapViewerProps {
  result: PhaseAResult
  sessionId: string
}

export default function AgentMapViewer({ result, sessionId }: AgentMapViewerProps) {
  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3">
        <SummaryCard label="Framework" value={result.framework} sub={`${(result.framework_confidence * 100).toFixed(0)}% confidence`} />
        <SummaryCard label="Files Scanned" value={String(result.files_scanned)} />
        <SummaryCard label="Tools Found" value={String(result.tools_count)} />
        <SummaryCard label="Prompts Found" value={String(result.prompts_count)} />
        <SummaryCard label="Risks" value={String(result.risks_count)} />
        <SummaryCard label="Language" value={result.language} />
      </div>

      {/* Tools list */}
      {result.tools.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">Tools</h4>
          <div className="space-y-1">
            {result.tools.map((t) => (
              <div key={t.name} className="flex items-center gap-2 px-3 py-2 bg-bg-card border border-border rounded-lg">
                <span className="text-sm font-medium text-pearl">{t.name}</span>
                <span className="text-xs text-text-muted flex-1 truncate">{t.description}</span>
                <StatusBadge status={t.risk_level} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Risks table */}
      {result.risks.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">Risks</h4>
          <div className="space-y-1">
            {result.risks.map((r, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2 bg-bg-card border border-border rounded-lg">
                <span className="text-sm text-smoke font-mono">{r.tool}</span>
                <span className="text-xs text-text-muted flex-1">{r.description}</span>
                <StatusBadge status={r.severity} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Agent Map Graph */}
      {result.graph_path && (
        <div className="space-y-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">Agent Map Graph</h4>
          <div className="bg-bg-card border border-border rounded-lg p-4">
            <img
              src={`/api/artifacts/${sessionId}/graph-png`}
              alt="Agent Map Graph"
              className="max-w-full rounded"
            />
          </div>
        </div>
      )}

      {/* Raw JSON */}
      <JsonViewer data={result} title="Raw Result Data" collapsed />
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
