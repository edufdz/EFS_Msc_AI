import { Slider, Toggle, NumberInput, Select, Section } from '../shared/ControlPanel'

interface ExecutionControlsProps {
  workers: number
  count: number
  aiPersonas: boolean
  traces: boolean
  seed: number | null
  language: string
  validate: boolean
  forceAiPersonas?: boolean
  onWorkersChange: (v: number) => void
  onCountChange: (v: number) => void
  onAiPersonasChange: (v: boolean) => void
  onTracesChange: (v: boolean) => void
  onSeedChange: (v: number | null) => void
  onLanguageChange: (v: string) => void
  onValidateChange: (v: boolean) => void
}

export default function ExecutionControls(props: ExecutionControlsProps) {
  return (
    <div className="space-y-6">
      <Section title="Execution">
        <Slider label="Workers" value={props.workers} min={1} max={50} onChange={props.onWorkersChange} />
        <Slider label="Test Count Limit" value={props.count} min={0} max={500} step={10} onChange={props.onCountChange} />
        <Toggle label="AI Personas" checked={props.aiPersonas} onChange={props.onAiPersonasChange} description={props.forceAiPersonas ? "Required — no template personas available" : "Use AI for persona messages (costs $)"} disabled={props.forceAiPersonas} />
        <Toggle label="Enable Traces" checked={props.traces} onChange={props.onTracesChange} description="Save per-test trace files" />
        <Toggle label="Validate Failures" checked={props.validate} onChange={props.onValidateChange} description="AI triage: filter persona/chaos failures before diagnosis" />
      </Section>

      <Section title="Options">
        <NumberInput label="Random Seed" value={props.seed} onChange={props.onSeedChange} />
        <Select
          label="Language"
          value={props.language}
          options={[
            { value: '', label: 'Auto (from Agent Map)' },
            { value: 'English', label: 'English' },
            { value: 'Spanish', label: 'Spanish' },
          ]}
          onChange={props.onLanguageChange}
        />
      </Section>
    </div>
  )
}
