import { useState } from 'react'
import type { AnonymizeConfig } from '../api/types'

interface Props {
  config: AnonymizeConfig
  onChange: (config: AnonymizeConfig) => void
}

const PII_CATEGORIES = [
  'PHONE',
  'EMAIL',
  'PERSON',
  'LOCATION',
  'ORDER_ID',
  'ACCOUNT_NUMBER',
  'ADDRESS',
  'URL',
]

export default function ConfigPanel({ config, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const [brandInput, setBrandInput] = useState(
    (config.custom_brand_terms ?? []).join(', '),
  )

  const activeCategories = config.categories ?? PII_CATEGORIES

  const toggleCategory = (cat: string) => {
    const current = config.categories ?? PII_CATEGORIES
    const next = current.includes(cat)
      ? current.filter((c) => c !== cat)
      : [...current, cat]
    onChange({ ...config, categories: next })
  }

  const updateBrands = (value: string) => {
    setBrandInput(value)
    const terms = value
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    onChange({ ...config, custom_brand_terms: terms })
  }

  return (
    <div className="border border-border rounded-lg">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-4 py-2 text-sm font-medium text-text-dim text-left flex items-center justify-between hover:bg-bg-surface transition-colors rounded-lg"
      >
        Configuration
        <span className="text-xs">{open ? '\u25B2' : '\u25BC'}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-4">
          <div>
            <label className="text-xs font-semibold text-text-muted uppercase tracking-wide">
              PII Categories
            </label>
            <div className="mt-2 flex flex-wrap gap-2">
              {PII_CATEGORIES.map((cat) => (
                <label
                  key={cat}
                  className="flex items-center gap-1.5 text-sm cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={activeCategories.includes(cat)}
                    onChange={() => toggleCategory(cat)}
                    className="rounded"
                  />
                  {cat}
                </label>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold text-text-muted uppercase tracking-wide">
              Custom Brand Terms
            </label>
            <input
              type="text"
              value={brandInput}
              onChange={(e) => updateBrands(e.target.value)}
              placeholder="e.g. Acme, WidgetCo, SuperApp"
              className="mt-1 w-full px-3 py-1.5 text-sm border border-border rounded bg-bg focus:outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-text-muted uppercase tracking-wide">
              Placeholder Style
            </label>
            <div className="mt-2 flex gap-4">
              {(['numbered', 'generic'] as const).map((style) => (
                <label key={style} className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input
                    type="radio"
                    name="placeholder_style"
                    checked={(config.placeholder_style ?? 'numbered') === style}
                    onChange={() => onChange({ ...config, placeholder_style: style })}
                  />
                  {style === 'numbered' ? '[PHONE_1]' : '[PHONE]'}
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
