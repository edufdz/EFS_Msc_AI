const colorMap: Record<string, string> = {
  passed: 'bg-pearl/10 text-pearl border-pearl/20',
  failed: 'bg-text-muted/10 text-smoke border-text-muted/20',
  error: 'bg-text-muted/10 text-text-muted border-text-muted/20',
  timeout: 'bg-border text-text-muted border-border',
  running: 'bg-accent/10 text-accent border-accent/20',
  idle: 'bg-border/50 text-text-muted border-border',
  completed: 'bg-pearl/10 text-pearl border-pearl/20',
  low: 'bg-pearl/5 text-smoke border-pearl/10',
  medium: 'bg-smoke/10 text-smoke border-smoke/20',
  high: 'bg-text-muted/15 text-pearl border-text-muted/30',
  critical: 'bg-pearl/15 text-pearl border-pearl/30',
  easy: 'bg-pearl/5 text-smoke border-pearl/10',
  hard: 'bg-text-muted/10 text-pearl border-text-muted/20',
}

export default function StatusBadge({ status }: { status: string }) {
  const classes = colorMap[status] || colorMap.idle
  return (
    <span className={`inline-flex px-2 py-0.5 text-[11px] font-medium rounded border uppercase tracking-wider ${classes}`}>
      {status}
    </span>
  )
}
