import { Slider, Toggle, NumberInput, Select, TextInput, Section } from '../shared/ControlPanel'

const PROVIDER_DEFAULTS: Record<string, string> = {
  ollama: 'mistral',
  groq: 'llama-3.1-8b-instant',
  openai: 'gpt-4o-mini',
  together: 'meta-llama/Llama-3.1-8B-Instruct-Turbo',
}

interface GenerationControlsProps {
  count: number
  personaCount: number
  scenarioCount: number
  variants: number
  includeTemplates: boolean
  seed: number | null
  language: string
  llmProvider: string
  llmModel: string
  llmBaseUrl: string
  onCountChange: (v: number) => void
  onPersonaCountChange: (v: number) => void
  onScenarioCountChange: (v: number) => void
  onVariantsChange: (v: number) => void
  onIncludeTemplatesChange: (v: boolean) => void
  onSeedChange: (v: number | null) => void
  onLanguageChange: (v: string) => void
  onLlmProviderChange: (v: string) => void
  onLlmModelChange: (v: string) => void
  onLlmBaseUrlChange: (v: string) => void
}

export default function GenerationControls(props: GenerationControlsProps) {
  const handleProviderChange = (v: string) => {
    props.onLlmProviderChange(v)
    if (v && PROVIDER_DEFAULTS[v]) {
      props.onLlmModelChange(PROVIDER_DEFAULTS[v])
    } else {
      props.onLlmModelChange('')
    }
  }

  return (
    <div className="space-y-6">
      <Section title="LLM Provider">
        <Select
          label="Provider"
          value={props.llmProvider}
          options={[
            { value: '', label: 'Default (Anthropic)' },
            { value: 'ollama', label: 'Ollama (local)' },
            { value: 'groq', label: 'Groq' },
            { value: 'openai', label: 'OpenAI' },
            { value: 'together', label: 'Together AI' },
            { value: 'custom', label: 'Custom endpoint' },
          ]}
          onChange={handleProviderChange}
        />
        {props.llmProvider && (
          <TextInput
            label="Model"
            value={props.llmModel}
            onChange={props.onLlmModelChange}
            placeholder={PROVIDER_DEFAULTS[props.llmProvider] || 'model-name'}
          />
        )}
        {props.llmProvider === 'custom' && (
          <TextInput
            label="Base URL"
            value={props.llmBaseUrl}
            onChange={props.onLlmBaseUrlChange}
            placeholder="http://localhost:1234/v1"
          />
        )}
      </Section>

      <Section title="Test Generation">
        <Slider label="Test Count" value={props.count} min={10} max={1000} step={10} onChange={props.onCountChange} />
        <Slider label="Persona Count" value={props.personaCount} min={0} max={20} onChange={props.onPersonaCountChange} />
        <Slider label="Scenario Count" value={props.scenarioCount} min={0} max={50} onChange={props.onScenarioCountChange} />
        <Slider label="Variants per Scenario" value={props.variants} min={0} max={10} onChange={props.onVariantsChange} />
      </Section>

      <Section title="Options">
        <Toggle
          label="Include Template Personas"
          checked={props.includeTemplates}
          onChange={props.onIncludeTemplatesChange}
          description="Also create pre-built template personas (default: AI-only)"
        />
        <NumberInput label="Random Seed" value={props.seed} onChange={props.onSeedChange} placeholder="Optional" />
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
