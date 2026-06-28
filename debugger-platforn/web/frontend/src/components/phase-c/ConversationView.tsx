import StatusBadge from '../shared/StatusBadge'

interface ConversationViewProps {
  test: {
    test_id: string
    test_number: number
    scenario: string
    persona: string
    difficulty: string
    status: string
    turns: Array<{ turn: number; role: string; message: string; duration_ms: number }>
    tool_calls: Array<{ tool_name: string; status: string }>
  }
}

export default function ConversationView({ test }: ConversationViewProps) {
  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-bg-card border border-border rounded-lg p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="font-mono text-smoke text-sm">{test.test_id}</span>
          <StatusBadge status={test.status} />
        </div>
        <div className="text-pearl font-medium">{test.scenario}</div>
        <div className="text-xs text-text-muted mt-1">Persona: {test.persona} | Difficulty: {test.difficulty}</div>
      </div>

      {/* Conversation turns — WhatsApp style: green (user) / white (agent) */}
      <div className="space-y-2">
        {test.turns.map((turn, i) => (
          <div
            key={i}
            className={`flex ${turn.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 shadow-sm ${
                turn.role === 'user'
                  ? 'bg-[#D9FDD3] text-[#111B21] rounded-br-none'
                  : 'bg-white text-[#111B21] rounded-bl-none border border-[#E9EDEF]'
              }`}
            >
              <div className="flex items-center justify-between mb-1 gap-2">
                <span className={`text-xs font-bold ${turn.role === 'user' ? 'text-[#0D8050]' : 'text-[#54656F]'}`}>
                  {turn.role === 'user' ? 'User (Persona)' : 'Agent'}
                </span>
                <span className="text-[10px] text-[#667781] font-mono">Turn {turn.turn}</span>
              </div>
              <div className="text-sm whitespace-pre-wrap">{turn.message}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Tool calls summary */}
      {test.tool_calls.length > 0 && (
        <div className="bg-bg-card border border-border rounded-lg p-3">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted mb-2">
            Tool Calls ({test.tool_calls.length})
          </div>
          <div className="flex flex-wrap gap-1">
            {test.tool_calls.map((tc, i) => (
              <span
                key={i}
                className={`text-xs px-2 py-1 rounded font-mono ${
                  tc.status === 'success' ? 'bg-pearl/10 text-smoke' : 'bg-text-muted/10 text-text-muted'
                }`}
              >
                {tc.tool_name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
