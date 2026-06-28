interface PersonaContextInputProps {
  value: string
  onChange: (v: string) => void
}

export default function PersonaContextInput({ value, onChange }: PersonaContextInputProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-text-muted">
        Persona Context
      </h3>
      <p className="text-xs text-smoke">
        Provide business context for AI personas (e.g., product details, pricing, policies).
        This replaces the CLI input() prompt.
      </p>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Enter persona context here... (optional)"
        rows={5}
        className="w-full px-3 py-2 text-sm bg-bg-card border border-border rounded-lg text-pearl font-mono focus:outline-none focus:border-platinum resize-y transition-colors"
      />
    </div>
  )
}
