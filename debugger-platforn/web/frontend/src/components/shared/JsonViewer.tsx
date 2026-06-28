import { useState } from 'react'

interface JsonViewerProps {
  data: unknown
  title?: string
  collapsed?: boolean
}

export default function JsonViewer({ data, title, collapsed = true }: JsonViewerProps) {
  const [expanded, setExpanded] = useState(!collapsed)

  return (
    <div className="bg-bg-card border border-border rounded-lg overflow-hidden">
      {title && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between px-3 py-2 text-sm text-text-primary hover:bg-bg-card-hover transition-colors"
        >
          <span className="font-medium">{title}</span>
          <span className="text-text-muted text-xs">{expanded ? '\u25BC' : '\u25B6'}</span>
        </button>
      )}
      {expanded && (
        <pre className="px-3 py-2 text-xs font-mono text-text-dim overflow-x-auto max-h-96 border-t border-border">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}
