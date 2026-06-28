import type { MinimalReproduction } from '../../api/types'

interface MinimalReproViewerProps {
  reproduction: MinimalReproduction
}

export default function MinimalReproViewer({ reproduction }: MinimalReproViewerProps) {
  return (
    <div className="space-y-3">
      {/* Steps as WhatsApp-style bubbles */}
      {reproduction.steps && reproduction.steps.length > 0 && (
        <div className="space-y-2">
          {reproduction.steps.map((step, i) => (
            <div
              key={i}
              className={`flex ${step.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 shadow-sm ${
                  step.role === 'user'
                    ? 'bg-[#D9FDD3] text-[#111B21] rounded-br-none'
                    : 'bg-white text-[#111B21] rounded-bl-none border border-[#E9EDEF]'
                }`}
              >
                <div className="flex items-center justify-between mb-1 gap-2">
                  <span className={`text-xs font-bold ${step.role === 'user' ? 'text-[#0D8050]' : 'text-[#54656F]'}`}>
                    {step.role === 'user' ? 'User' : 'Agent'}
                  </span>
                  <span className="text-[10px] text-[#667781] font-mono">Step {i + 1}</span>
                </div>
                <div className="text-sm whitespace-pre-wrap">{step.content}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Expected vs Actual */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {reproduction.expected_behavior && (
          <div className="bg-bg-surface border border-border rounded-lg p-3">
            <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted mb-1.5">
              Expected Behavior
            </div>
            <div className="text-sm text-smoke whitespace-pre-wrap">{reproduction.expected_behavior}</div>
          </div>
        )}
        {reproduction.actual_behavior && (
          <div className="bg-bg-surface border border-border rounded-lg p-3">
            <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted mb-1.5">
              Actual Behavior
            </div>
            <div className="text-sm text-smoke whitespace-pre-wrap">{reproduction.actual_behavior}</div>
          </div>
        )}
      </div>

      {/* Key trigger */}
      {reproduction.key_trigger && (
        <div className="bg-bg-surface border border-border rounded-lg p-3">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted mb-1.5">
            Key Trigger
          </div>
          <div className="text-sm text-pearl font-mono">{reproduction.key_trigger}</div>
        </div>
      )}
    </div>
  )
}
