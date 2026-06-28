import { useRef, useCallback } from 'react'
import type { AnonymizeResponse } from '../api/types'
import { buildSegments, buildFallbackSegments, getCategoryColor } from '../utils/highlights'
import type { Segment } from '../utils/highlights'

interface Props {
  result: AnonymizeResponse | null
}

function SegmentedText({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((seg, i) =>
        seg.category ? (
          <mark
            key={i}
            className={`${getCategoryColor(seg.category)} rounded px-0.5`}
          >
            {seg.text}
          </mark>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </>
  )
}

export default function DiffViewer({ result }: Props) {
  const leftRef = useRef<HTMLDivElement>(null)
  const rightRef = useRef<HTMLDivElement>(null)
  const syncing = useRef(false)

  const syncScroll = useCallback(
    (source: HTMLDivElement | null, target: HTMLDivElement | null) => {
      if (!source || !target || syncing.current) return
      syncing.current = true
      const ratio = source.scrollTop / (source.scrollHeight - source.clientHeight || 1)
      target.scrollTop = ratio * (target.scrollHeight - target.clientHeight || 1)
      requestAnimationFrame(() => {
        syncing.current = false
      })
    },
    [],
  )

  if (!result) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
        Upload and anonymize a file to see the before/after comparison
      </div>
    )
  }

  const hasReplacements = result.replacements && result.replacements.length > 0
  const leftSegments = hasReplacements
    ? buildSegments(result.original_text, result.replacements, true)
    : [{ text: result.original_text, category: null } as Segment]
  const rightSegments = hasReplacements
    ? buildSegments(result.original_text, result.replacements, false)
    : buildFallbackSegments(result.anonymized_text)

  return (
    <div className="flex-1 grid grid-cols-2 gap-4 min-h-0">
      <div className="flex flex-col min-h-0">
        <h3 className="text-sm font-semibold text-text-dim mb-2">Original</h3>
        <div
          ref={leftRef}
          className="flex-1 overflow-auto bg-bg-card rounded-lg p-4 border border-border"
          onScroll={() => syncScroll(leftRef.current, rightRef.current)}
        >
          <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed">
            <SegmentedText segments={leftSegments} />
          </pre>
        </div>
      </div>
      <div className="flex flex-col min-h-0">
        <h3 className="text-sm font-semibold text-text-dim mb-2">Anonymized</h3>
        <div
          ref={rightRef}
          className="flex-1 overflow-auto bg-bg-card rounded-lg p-4 border border-border"
          onScroll={() => syncScroll(rightRef.current, leftRef.current)}
        >
          <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed">
            <SegmentedText segments={rightSegments} />
          </pre>
        </div>
      </div>
    </div>
  )
}
