import type { Replacement } from '../api/types'

export interface Segment {
  text: string
  category: string | null
}

export const CATEGORY_COLORS: Record<string, string> = {
  PERSON: 'bg-hl-name',
  PHONE: 'bg-hl-phone',
  EMAIL: 'bg-hl-email',
  BRAND: 'bg-hl-brand',
  DEVICE: 'bg-hl-brand',
  PRODUCT: 'bg-hl-brand',
  SERVICE: 'bg-hl-brand',
}

const DEFAULT_COLOR = 'bg-hl-other'

export function getCategoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? DEFAULT_COLOR
}

export function buildSegments(
  fullText: string,
  replacements: Replacement[],
  useOriginal: boolean,
): Segment[] {
  if (!replacements.length) return [{ text: fullText, category: null }]

  const sorted = [...replacements].sort((a, b) => a.start - b.start)
  const segments: Segment[] = []
  let cursor = 0

  for (const r of sorted) {
    if (r.start > cursor) {
      segments.push({ text: fullText.slice(cursor, r.start), category: null })
    }
    segments.push({
      text: useOriginal ? r.original : r.placeholder,
      category: r.category,
    })
    cursor = r.end
  }

  if (cursor < fullText.length) {
    segments.push({ text: fullText.slice(cursor), category: null })
  }

  return segments
}

export function buildFallbackSegments(anonymizedText: string): Segment[] {
  const regex = /\[([A-Z_]+?)(?:_\d+)?\]/g
  const segments: Segment[] = []
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = regex.exec(anonymizedText)) !== null) {
    if (match.index > cursor) {
      segments.push({ text: anonymizedText.slice(cursor, match.index), category: null })
    }
    segments.push({ text: match[0], category: match[1] })
    cursor = match.index + match[0].length
  }

  if (cursor < anonymizedText.length) {
    segments.push({ text: anonymizedText.slice(cursor), category: null })
  }

  return segments
}
