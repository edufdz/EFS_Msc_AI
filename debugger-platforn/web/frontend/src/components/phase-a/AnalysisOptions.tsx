import { Toggle, Select } from '../shared/ControlPanel'

interface AnalysisOptionsProps {
  skipAi: boolean
  language: string
  promptEncoding: string
  useTraces: boolean
  onSkipAiChange: (v: boolean) => void
  onLanguageChange: (v: string) => void
  onEncodingChange: (v: string) => void
  onUseTracesChange: (v: boolean) => void
}

export default function AnalysisOptions({
  skipAi, language, promptEncoding, useTraces,
  onSkipAiChange, onLanguageChange, onEncodingChange, onUseTracesChange,
}: AnalysisOptionsProps) {
  return (
    <div className="space-y-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Analysis Options
      </h3>
      <Toggle
        label="Skip AI Analysis"
        checked={skipAi}
        onChange={onSkipAiChange}
        description="Offline mode — no API key needed"
      />
      <Toggle
        label="Use Langfuse Traces"
        checked={useTraces}
        onChange={onUseTracesChange}
        description="Ingest runtime traces for dynamic analysis"
      />
      <Select
        label="Language Filter"
        value={language}
        options={[
          { value: '', label: 'All Languages' },
          { value: 'python', label: 'Python' },
          { value: 'javascript', label: 'JavaScript' },
          { value: 'typescript', label: 'TypeScript' },
        ]}
        onChange={onLanguageChange}
      />
      <Select
        label="Prompt Encoding"
        value={promptEncoding}
        options={[
          { value: 'utf-8', label: 'UTF-8' },
          { value: 'latin-1', label: 'Latin-1' },
        ]}
        onChange={onEncodingChange}
      />
    </div>
  )
}
