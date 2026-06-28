import { useState } from 'react'

interface DiagnosisControlsProps {
  skipAi: boolean
  onSkipAiChange: (v: boolean) => void
  useEmbeddings: boolean
  onUseEmbeddingsChange: (v: boolean) => void
  maxRetries: number
  onMaxRetriesChange: (v: number) => void
}

export default function DiagnosisControls({
  skipAi, onSkipAiChange,
  useEmbeddings, onUseEmbeddingsChange,
  maxRetries, onMaxRetriesChange,
}: DiagnosisControlsProps) {
  return (
    <div className="bg-bg-card border border-border rounded-lg p-4 space-y-4">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Diagnosis Configuration
      </div>

      {/* Skip AI toggle */}
      <label className="flex items-center justify-between cursor-pointer">
        <div>
          <div className="text-sm text-pearl">Use AI Analysis</div>
          <div className="text-[11px] text-text-muted">Use Claude for root cause analysis and fix proposals</div>
        </div>
        <button
          onClick={() => onSkipAiChange(!skipAi)}
          className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${!skipAi ? 'bg-platinum' : 'bg-graphite'}`}
        >
          <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-bg transition-transform duration-200 ${!skipAi ? 'translate-x-5' : 'translate-x-0.5'}`} />
        </button>
      </label>

      {/* Embeddings toggle */}
      <label className="flex items-center justify-between cursor-pointer">
        <div>
          <div className="text-sm text-pearl">Embedding Clustering</div>
          <div className="text-[11px] text-text-muted">Use sentence embeddings for better failure clustering</div>
        </div>
        <button
          onClick={() => onUseEmbeddingsChange(!useEmbeddings)}
          className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${useEmbeddings ? 'bg-platinum' : 'bg-graphite'}`}
        >
          <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-bg transition-transform duration-200 ${useEmbeddings ? 'translate-x-5' : 'translate-x-0.5'}`} />
        </button>
      </label>

      {/* Max retries */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-sm text-pearl">Max API Retries</span>
          <span className="text-xs font-mono text-smoke tabular-nums">{maxRetries}</span>
        </div>
        <input
          type="range"
          min={1}
          max={10}
          value={maxRetries}
          onChange={(e) => onMaxRetriesChange(Number(e.target.value))}
          className="w-full h-1 bg-border rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-platinum"
        />
      </div>
    </div>
  )
}
