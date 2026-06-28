import { useState } from 'react'
import { useStore } from '../../store'
import ConversationView from './ConversationView'
import StatusBadge from '../shared/StatusBadge'

export default function SimulationCards() {
  const activeTests = useStore((s) => s.activeTests)
  const phaseCStatus = useStore((s) => s.phaseC)
  const [selectedTestId, setSelectedTestId] = useState<string | null>(null)
  const [tab, setTab] = useState<'active' | 'conversations'>('active')

  const tests = Array.from(activeTests.values())
  const runningTests = tests.filter((t) => t.status === 'running')
  const completedTestsList = tests.filter((t) => t.status !== 'running')
  const isLoadingSimulations = phaseCStatus === 'running' && runningTests.length === 0 && completedTestsList.length === 0

  if (selectedTestId) {
    const test = activeTests.get(selectedTestId)
    if (test) {
      return (
        <div>
          <button
            onClick={() => setSelectedTestId(null)}
            className="text-sm text-smoke hover:text-pearl transition-colors mb-3"
          >
            &larr; Back to simulations
          </button>
          <ConversationView test={test} />
        </div>
      )
    }
  }

  return (
    <div className="space-y-4">
      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        <button
          onClick={() => setTab('active')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === 'active' ? 'border-platinum text-pearl' : 'border-transparent text-text-muted hover:text-smoke'
          }`}
        >
          Active Simulations ({runningTests.length})
        </button>
        <button
          onClick={() => setTab('conversations')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === 'conversations' ? 'border-platinum text-pearl' : 'border-transparent text-text-muted hover:text-smoke'
          }`}
        >
          Conversations ({completedTestsList.length})
        </button>
      </div>

      {/* Active simulations */}
      {tab === 'active' && (
        <div className="grid grid-cols-2 gap-3">
          {isLoadingSimulations && (
            <div className="col-span-2 flex flex-col items-center justify-center py-12 text-center">
              <div className="w-10 h-10 border-2 border-platinum/30 border-t-platinum rounded-full animate-spin mb-3" />
              <p className="text-sm font-medium text-pearl">Loading simulations…</p>
              <p className="text-xs text-text-muted mt-1">Starting tests — simulations will appear here as they run</p>
            </div>
          )}
          {!isLoadingSimulations && runningTests.length === 0 && (
            <div className="col-span-2 text-center py-8 text-text-muted text-sm">
              No active simulations
            </div>
          )}
          {runningTests.map((test) => (
            <div
              key={test.test_id}
              onClick={() => setSelectedTestId(test.test_id)}
              className="bg-bg-card border border-accent/40 rounded-lg p-3 cursor-pointer hover:border-platinum/30 transition-all duration-200"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono text-smoke">{test.test_id}</span>
                <StatusBadge status="running" />
              </div>
              <div className="text-sm text-pearl truncate">{test.scenario}</div>
              <div className="text-xs text-text-muted mt-1">{test.persona}</div>
              {/* Last messages — WhatsApp style: green (user) / white (agent) */}
              <div className="mt-2 space-y-1">
                {test.turns.slice(-2).map((turn, i) => (
                  <div
                    key={i}
                    className={`text-[11px] px-2 py-1 rounded max-w-full ${
                      turn.role === 'user'
                        ? 'bg-[#D9FDD3] text-[#111B21] ml-auto rounded-br-none'
                        : 'bg-white text-[#111B21] border border-[#E9EDEF] rounded-bl-none'
                    }`}
                  >
                    <span className="font-bold">{turn.role}: </span>
                    <span className="truncate">{turn.message.slice(0, 60)}</span>
                  </div>
                ))}
              </div>
              {/* Tool call pills */}
              {test.tool_calls.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {test.tool_calls.slice(-3).map((tc, i) => (
                    <span
                      key={i}
                      className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                        tc.status === 'success' ? 'bg-pearl/10 text-smoke' : 'bg-text-muted/10 text-text-muted'
                      }`}
                    >
                      {tc.tool_name}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Conversations list */}
      {tab === 'conversations' && (
        <div className="space-y-1">
          {completedTestsList.length === 0 && (
            <div className="text-center py-8 text-text-muted text-sm">
              No completed conversations yet
            </div>
          )}
          {completedTestsList.map((test) => {
            const borderColor =
              test.status === 'passed' ? 'border-l-emerald-500' :
              test.status === 'failed' ? 'border-l-red-500' :
              test.status === 'error' ? 'border-l-amber-500' :
              test.status === 'timeout' ? 'border-l-yellow-500' : ''
            return (
            <button
              key={test.test_id}
              onClick={() => setSelectedTestId(test.test_id)}
              className={`w-full flex items-center gap-3 px-3 py-2 bg-bg-card border border-border rounded-lg hover:border-border-light transition-all duration-200 ${borderColor ? `border-l-4 ${borderColor}` : ''}`}
            >
              <span className="text-xs font-mono text-text-muted w-16">{test.test_id}</span>
              <span className="text-sm text-pearl flex-1 truncate text-left">{test.scenario}</span>
              <span className="text-xs text-text-muted">{test.turns.length} turns</span>
              <StatusBadge status={test.status} />
            </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
