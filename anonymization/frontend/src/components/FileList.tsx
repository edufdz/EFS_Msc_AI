import type { FileEntry } from '../api/types'

interface Props {
  files: FileEntry[]
  selectedIndex: number | null
  onSelect: (i: number) => void
  onRemove: (i: number) => void
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const STATUS_ICON: Record<string, string> = {
  pending: '\u23F3',
  processing: '\u2699\uFE0F',
  done: '\u2705',
  error: '\u274C',
}

export default function FileList({ files, selectedIndex, onSelect, onRemove }: Props) {
  return (
    <div className="space-y-1">
      {files.map((f, i) => (
        <div
          key={i}
          className={`flex items-center gap-3 px-3 py-2 rounded cursor-pointer transition-colors ${
            selectedIndex === i
              ? 'bg-blue-50 border border-accent'
              : 'bg-bg-card hover:bg-bg-card border border-transparent'
          }`}
          onClick={() => onSelect(i)}
        >
          <span className="text-sm">{STATUS_ICON[f.status]}</span>
          <span className="flex-1 text-sm font-medium truncate">
            {f.file.name}
          </span>
          <span className="text-xs text-text-muted">{formatSize(f.file.size)}</span>
          <button
            className="text-text-muted hover:text-red-500 text-sm px-1"
            onClick={(e) => {
              e.stopPropagation()
              onRemove(i)
            }}
          >
            x
          </button>
        </div>
      ))}
    </div>
  )
}
