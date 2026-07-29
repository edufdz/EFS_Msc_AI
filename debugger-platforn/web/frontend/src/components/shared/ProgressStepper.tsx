import { useStore } from '../../store'

const steps = [
  { key: 'a' as const, label: 'Analyze' },
  { key: 'b' as const, label: 'Generate' },
  { key: 'c' as const, label: 'Execute' },
]

export default function ProgressStepper() {
  const phaseA = useStore((s) => s.phaseA)
  const phaseB = useStore((s) => s.phaseB)
  const phaseC = useStore((s) => s.phaseC)
  const statuses = { a: phaseA, b: phaseB, c: phaseC }

  return (
    <div className="flex items-center justify-center gap-2">
      {steps.map((step, i) => {
        const status = statuses[step.key]
        const isCompleted = status === 'completed'
        const isRunning = status === 'running'
        return (
          <div key={step.key} className="flex items-center gap-2">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-300 ${
                isCompleted
                  ? 'bg-pearl text-bg'
                  : isRunning
                    ? 'bg-accent text-bg animate-pulse-soft'
                    : 'bg-border text-text-muted'
              }`}
            >
              {isCompleted ? '\u2713' : step.key.toUpperCase()}
            </div>
            <span className={`text-sm transition-colors ${isRunning ? 'text-pearl font-medium' : isCompleted ? 'text-pearl' : 'text-text-muted'}`}>
              {step.label}
            </span>
            {i < steps.length - 1 && (
              <div className={`w-8 h-px ${isCompleted ? 'bg-accent' : 'bg-border'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}
