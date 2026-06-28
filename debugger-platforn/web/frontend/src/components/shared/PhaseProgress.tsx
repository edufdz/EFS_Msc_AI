import { useEffect, useState } from 'react'

interface Step {
  key: string
  label: string
  pctThreshold: number
}

interface PhaseProgressProps {
  steps: Step[]
  currentPct: number
  currentMessage: string
}

export default function PhaseProgress({ steps, currentPct, currentMessage }: PhaseProgressProps) {
  const [animatedPct, setAnimatedPct] = useState(0)

  // Smooth progress animation
  useEffect(() => {
    if (currentPct > animatedPct) {
      const timer = setTimeout(() => {
        setAnimatedPct((prev) => Math.min(prev + 1, currentPct))
      }, 20)
      return () => clearTimeout(timer)
    }
  }, [currentPct, animatedPct])

  // Reset on new run
  useEffect(() => {
    if (currentPct === 0) setAnimatedPct(0)
  }, [currentPct])

  // Determine step states
  const getStepState = (step: Step, idx: number): 'completed' | 'active' | 'pending' => {
    const nextStep = steps[idx + 1]
    if (nextStep && currentPct >= nextStep.pctThreshold) return 'completed'
    if (currentPct >= step.pctThreshold) return 'active'
    return 'pending'
  }

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4 space-y-4">
      {/* Progress bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-widest font-medium text-text-muted">Progress</span>
          <span className="text-xs font-mono text-pearl tabular-nums">{Math.round(animatedPct)}%</span>
        </div>
        <div className="h-1 bg-border rounded-full overflow-hidden">
          <div
            className="h-full bg-platinum rounded-full transition-all duration-300 ease-out"
            style={{ width: `${animatedPct}%` }}
          >
            <div className="h-full w-full bg-white/10 animate-shimmer" />
          </div>
        </div>
      </div>

      {/* Step list */}
      <div className="space-y-0.5">
        {steps.map((step, idx) => {
          const state = getStepState(step, idx)
          return (
            <div
              key={step.key}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-300 ${
                state === 'active'
                  ? 'bg-graphite/50'
                  : state === 'completed'
                    ? ''
                    : 'opacity-30'
              }`}
            >
              {/* Status icon */}
              <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center">
                {state === 'completed' ? (
                  <CheckIcon />
                ) : state === 'active' ? (
                  <Spinner />
                ) : (
                  <PendingDot />
                )}
              </div>

              {/* Step label */}
              <span
                className={`text-sm transition-colors duration-300 ${
                  state === 'active'
                    ? 'text-pearl font-medium'
                    : state === 'completed'
                      ? 'text-smoke'
                      : 'text-text-muted'
                }`}
              >
                {state === 'active' ? currentMessage || step.label : step.label}
              </span>

              {/* Active indicator */}
              {state === 'active' && (
                <div className="ml-auto flex items-center gap-1.5">
                  <span className="inline-block w-1 h-1 rounded-full bg-platinum animate-pulse" />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-smoke">
      <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1" fill="currentColor" fillOpacity="0.05" />
      <path d="M5 8.5L7 10.5L11 6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Spinner() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" className="animate-spin text-platinum">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="28" strokeDashoffset="8" strokeLinecap="round" opacity="0.8" />
    </svg>
  )
}

function PendingDot() {
  return (
    <div className="w-1.5 h-1.5 rounded-full bg-graphite" />
  )
}
