import { Toggle, Select } from '../shared/ControlPanel'

interface AnalysisOptionsProps {
  skipAi: boolean
  language: string
  promptEncoding: string
  onSkipAiChange: (v: boolean) => void
  onLanguageChange: (v: string) => void
  onEncodingChange: (v: string) => void
}

export default function AnalysisOptions({
  skipAi, language, promptEncoding,
  onSkipAiChange, onLanguageChange, onEncodingChange,
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
