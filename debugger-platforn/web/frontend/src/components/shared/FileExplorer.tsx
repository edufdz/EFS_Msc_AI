import { useState } from 'react'
import { resolveDirectory } from '../../api/client'

interface FileExplorerProps {
  onSelect: (path: string) => void
  selectedPath: string
}

// Collect filenames from a directory handle for path resolution
async function listHandleEntries(handle: FileSystemDirectoryHandle): Promise<string[]> {
  const names: string[] = []
  try {
    // .entries() returns [name, handle] pairs
    // @ts-expect-error — entries() async iterator not in TS lib
    for await (const [name] of handle.entries()) {
      names.push(name)
      if (names.length >= 10) break
    }
  } catch {
    // If entries() fails, try values()
    try {
      // @ts-expect-error — values() not in TS lib
      for await (const entry of handle.values()) {
        names.push(entry.name)
        if (names.length >= 10) break
      }
    } catch {
      // Could not iterate — return empty list, backend will still try to find by name
    }
  }
  return names
}

export default function FileExplorer({ onSelect, selectedPath }: FileExplorerProps) {
  const [picking, setPicking] = useState(false)
  const [manualPath, setManualPath] = useState(selectedPath)
  const [error, setError] = useState('')

  const handleBrowse = async () => {
    setError('')
    setPicking(true)

    try {
      // Check if browser supports showDirectoryPicker
      if (!('showDirectoryPicker' in window)) {
        setError('Folder picker not supported in this browser. Use Chrome or Edge, or type the path manually.')
        return
      }

      // Opens the native Finder / Explorer dialog directly from the browser
      // @ts-expect-error — showDirectoryPicker not in TS lib
      const handle: FileSystemDirectoryHandle = await window.showDirectoryPicker({ mode: 'read' })

      const dirName = handle.name

      // Collect sample filenames so the backend can locate the absolute path
      const files = await listHandleEntries(handle)

      // Ask backend to resolve the full absolute path
      const res = await resolveDirectory(dirName, files)

      if (res.path) {
        setManualPath(res.path)
        onSelect(res.path)
      } else {
        setError(`Selected "${dirName}" but couldn't resolve the full path. Type the path manually below.`)
      }
    } catch (e: unknown) {
      // User cancelled the dialog — not an error
      if (e instanceof DOMException && e.name === 'AbortError') {
        // cancelled, do nothing
      } else if (e instanceof TypeError || (e instanceof DOMException && e.name === 'SecurityError')) {
        setError('Folder picker not supported in this browser. Use Chrome or Edge, or type the path manually.')
      } else {
        const msg = e instanceof Error ? e.message : 'Unknown error'
        setError(`Folder picker failed: ${msg}. You can type the path manually instead.`)
      }
    } finally {
      setPicking(false)
    }
  }

  const handleManualSubmit = () => {
    if (manualPath.trim()) {
      onSelect(manualPath.trim())
    }
  }

  return (
    <div className="space-y-3">
      <label className="text-sm text-smoke">Repository Path</label>

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={manualPath}
          onChange={(e) => setManualPath(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleManualSubmit()
          }}
          onBlur={handleManualSubmit}
          placeholder="/path/to/agent/repo"
          className="flex-1 px-3 py-2.5 text-sm bg-bg-card border border-border rounded-lg text-pearl font-mono focus:outline-none focus:border-platinum transition-colors"
        />
        <button
          onClick={handleBrowse}
          disabled={picking}
          className="flex items-center gap-2 px-4 py-2.5 text-sm bg-platinum text-bg rounded-lg hover:bg-pearl transition-colors duration-200 disabled:opacity-50 whitespace-nowrap font-medium"
        >
          {picking ? <Spinner /> : <FolderIcon />}
          {picking ? 'Opening...' : 'Browse...'}
        </button>
      </div>

      {error && (
        <p className="text-xs text-smoke">{error}</p>
      )}

      {selectedPath && selectedPath === manualPath && !error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-pearl/5 border border-pearl/10 rounded-lg">
          <span className="text-pearl text-sm">&#10003;</span>
          <span className="text-sm text-smoke font-mono truncate">{selectedPath}</span>
        </div>
      )}
    </div>
  )
}

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="flex-shrink-0">
      <path
        d="M2 3.5A1.5 1.5 0 013.5 2h2.879a1.5 1.5 0 011.06.44l.622.621a.5.5 0 00.353.147H12.5A1.5 1.5 0 0114 4.707V12.5a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 12.5v-9z"
        fill="currentColor"
      />
    </svg>
  )
}

function Spinner() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" className="animate-spin flex-shrink-0">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="28" strokeDashoffset="8" strokeLinecap="round" />
    </svg>
  )
}
