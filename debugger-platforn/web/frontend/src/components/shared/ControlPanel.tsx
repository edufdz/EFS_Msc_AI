import { type ReactNode } from 'react'

// Reusable form controls

interface SliderProps {
  label: string
  value: number
  min: number
  max: number
  step?: number
  onChange: (v: number) => void
}

export function Slider({ label, value, min, max, step = 1, onChange }: SliderProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-sm">
        <span className="text-smoke">{label}</span>
        <span className="font-mono text-pearl tabular-nums">{value}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full cursor-pointer"
      />
    </div>
  )
}

interface ToggleProps {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  description?: string
  disabled?: boolean
}

export function Toggle({ label, checked, onChange, description, disabled }: ToggleProps) {
  return (
    <label className={`flex items-center justify-between gap-3 ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}>
      <div>
        <span className="text-sm text-pearl">{label}</span>
        {description && <p className="text-[11px] text-text-muted">{description}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${checked ? 'bg-platinum' : 'bg-graphite'} ${disabled ? 'cursor-not-allowed' : ''}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full transition-transform duration-200 ${checked ? 'translate-x-5 bg-bg' : 'bg-smoke'}`}
        />
      </button>
    </label>
  )
}

interface SelectProps {
  label: string
  value: string
  options: Array<{ value: string; label: string }>
  onChange: (v: string) => void
}

export function Select({ label, value, options, onChange }: SelectProps) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm text-smoke">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 text-sm bg-bg-card border border-border rounded-lg text-pearl focus:outline-none focus:border-platinum transition-colors"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

interface NumberInputProps {
  label: string
  value: number | null
  onChange: (v: number | null) => void
  placeholder?: string
}

export function NumberInput({ label, value, onChange, placeholder }: NumberInputProps) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm text-smoke">{label}</label>
      <input
        type="number"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        placeholder={placeholder || 'Optional'}
        className="w-full px-3 py-2 text-sm bg-bg-card border border-border rounded-lg text-pearl font-mono focus:outline-none focus:border-platinum transition-colors"
      />
    </div>
  )
}

interface TextInputProps {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}

export function TextInput({ label, value, onChange, placeholder }: TextInputProps) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm text-smoke">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder || ''}
        className="w-full px-3 py-2 text-sm bg-bg-card border border-border rounded-lg text-pearl font-mono focus:outline-none focus:border-platinum transition-colors"
      />
    </div>
  )
}

interface SectionProps {
  title: string
  children: ReactNode
}

export function Section({ title, children }: SectionProps) {
  return (
    <div className="space-y-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">{title}</h3>
      {children}
    </div>
  )
}
