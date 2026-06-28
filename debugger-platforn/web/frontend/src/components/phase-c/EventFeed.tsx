import { useRef, useEffect } from 'react'
import { useStore } from '../../store'

const iconMap: Record<string, string> = {
  rocket: '\uD83D\uDE80',
  chat: '\uD83D\uDCAC',
  tool: '\uD83D\uDD27',
  pass: '\u2705',
  fail: '\u274C',
  finish: '\uD83C\uDFC1',
  chaos: '\u26A1',
}

const colorMap: Record<string, string> = {
  blue: 'text-smoke',
  green: 'text-pearl',
  red: 'text-text-muted',
  orange: 'text-smoke',
  dim: 'text-text-muted',
}

export default function EventFeed() {
  const eventLog = useStore((s) => s.eventLog)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [eventLog.length])

  return (
    <div className="space-y-1">
      <div className="text-[11px] font-semibold uppercase tracking-widest text-text-muted mb-2">
        Event Feed
      </div>
      {eventLog.length === 0 && (
        <div className="text-sm text-text-muted text-center py-4">
          Waiting for events...
        </div>
      )}
      {eventLog.map((entry, i) => (
        <div key={i} className="flex items-start gap-2 text-xs">
          <span className="flex-shrink-0">{iconMap[entry.icon] || '\u2022'}</span>
          <span className={`flex-1 ${colorMap[entry.color] || 'text-text-muted'}`}>
            {entry.text}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
