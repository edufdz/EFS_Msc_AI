import { useState } from 'react'
import { useStore } from '../../store'
import StatusBadge from '../shared/StatusBadge'

export default function FailureInbox() {
  const failures = useStore((s) => s.failures)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
          Failure Inbox
        </div>
        <span className="text-xs text-smoke font-mono tabular-nums">{failures.length}</span>
      </div>

      {failures.length === 0 && (
        <div className="text-sm text-text-muted text-center py-4">
          No failures yet
        </div>
      )}

      {failures.map((f, i) => {
        const testId = (f.test_id as string) || `fail-${i}`
        const isExpanded = expandedId === testId
        return (
          <div
            key={i}
            className="bg-bg-card border border-border rounded-lg overflow-hidden"
          >
            <button
              onClick={() => setExpandedId(isExpanded ? null : testId)}
              className="w-full flex items-center gap-2 px-3 py-2 hover:bg-bg-card-hover transition-colors"
            >
              <span className="text-xs font-mono text-text-muted">
                #{f.test_number as number}
              </span>
              <span className="text-sm text-pearl flex-1 truncate text-left">
                {(f.scenario as string) || 'Unknown scenario'}
              </span>
              <StatusBadge status={(f.status as string) || 'failed'} />
            </button>
            {isExpanded && (
              <div className="px-3 pb-3 border-t border-border/50">
                <div className="text-xs text-text-muted mt-2">
                  <strong>Persona:</strong> {(f.persona as string) || 'N/A'}
                </div>
                {typeof f.failure_reason === 'string' && f.failure_reason && (
                  <div className="text-xs text-smoke mt-1">
                    <strong>Reason:</strong> {f.failure_reason}
                  </div>
                )}
                {Array.isArray(f.tools_called) && f.tools_called.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {(f.tools_called as string[]).map((t: string, j: number) => (
                      <span key={j} className="text-[10px] px-1.5 py-0.5 rounded bg-graphite text-text-muted font-mono">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
