import { Select, TextInput, Section } from './ControlPanel'

const PROVIDER_DEFAULTS: Record<string, string> = {
  ollama: 'mistral',
  groq: 'llama-3.1-8b-instant',
  openai: 'gpt-4o-mini',
  together: 'meta-llama/Llama-3.1-8B-Instruct-Turbo',
}

interface LlmProviderSelectProps {
  provider: string
  model: string
  baseUrl: string
  onProviderChange: (v: string) => void
  onModelChange: (v: string) => void
  onBaseUrlChange: (v: string) => void
}

export default function LlmProviderSelect(props: LlmProviderSelectProps) {
  const handleProviderChange = (v: string) => {
    props.onProviderChange(v)
    if (v && PROVIDER_DEFAULTS[v]) {
      props.onModelChange(PROVIDER_DEFAULTS[v])
    } else {
      props.onModelChange('')
    }
  }

  return (
    <Section title="LLM Provider">
      <Select
        label="Provider"
        value={props.provider}
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
      {props.provider && (
        <TextInput
          label="Model"
          value={props.model}
          onChange={props.onModelChange}
          placeholder={PROVIDER_DEFAULTS[props.provider] || 'model-name'}
        />
      )}
      {props.provider === 'custom' && (
        <TextInput
          label="Base URL"
          value={props.baseUrl}
          onChange={props.onBaseUrlChange}
          placeholder="http://localhost:1234/v1"
        />
      )}
    </Section>
  )
}
