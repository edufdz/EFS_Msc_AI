import { useState, useCallback } from 'react'
import type { FileEntry, AnonymizeConfig } from './api/types'
import { previewFile } from './api/client'
import UploadZone from './components/UploadZone'
import FileList from './components/FileList'
import DiffViewer from './components/DiffViewer'
import StatsBar from './components/StatsBar'
import DownloadBar from './components/DownloadBar'
import ConfigPanel from './components/ConfigPanel'

export default function App() {
  const [files, setFiles] = useState<FileEntry[]>([])
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [processing, setProcessing] = useState(false)
  const [config, setConfig] = useState<AnonymizeConfig>({})

  const handleFilesAdded = useCallback((newFiles: File[]) => {
    setFiles((prev) => [
      ...prev,
      ...newFiles.map((file) => ({ file, status: 'pending' as const })),
    ])
  }, [])

  const handleRemove = useCallback(
    (index: number) => {
      setFiles((prev) => prev.filter((_, i) => i !== index))
      if (selectedIndex === index) setSelectedIndex(null)
      else if (selectedIndex !== null && selectedIndex > index)
        setSelectedIndex(selectedIndex - 1)
    },
    [selectedIndex],
  )

  const handleAnonymize = async () => {
    setProcessing(true)
    const updated = [...files]

    for (let i = 0; i < updated.length; i++) {
      if (updated[i].status !== 'pending') continue

      updated[i] = { ...updated[i], status: 'processing' }
      setFiles([...updated])

      try {
        const result = await previewFile(updated[i].file, config)
        updated[i] = { ...updated[i], status: 'done', result }
      } catch (e) {
        updated[i] = {
          ...updated[i],
          status: 'error',
          error: e instanceof Error ? e.message : String(e),
        }
      }
      setFiles([...updated])
    }

    setProcessing(false)
    const firstDone = updated.findIndex((f) => f.status === 'done')
    if (firstDone >= 0 && selectedIndex === null) setSelectedIndex(firstDone)
  }

  const selectedFile = selectedIndex !== null ? files[selectedIndex] ?? null : null
  const hasPending = files.some((f) => f.status === 'pending')

  return (
    <div className="h-full flex flex-col p-6 max-w-7xl mx-auto gap-4">
      {/* Header */}
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Anonymization Tool</h1>
        {files.length > 0 && (
          <button
            onClick={handleAnonymize}
            disabled={processing || !hasPending}
            className="px-5 py-2 bg-accent text-white font-medium rounded hover:bg-accent-dim disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {processing ? 'Processing...' : 'Anonymize'}
          </button>
        )}
      </header>

      {/* Upload or File List */}
      {files.length === 0 ? (
        <UploadZone onFilesAdded={handleFilesAdded} />
      ) : (
        <div className="flex gap-4 items-start">
          <div className="flex-1">
            <FileList
              files={files}
              selectedIndex={selectedIndex}
              onSelect={setSelectedIndex}
              onRemove={handleRemove}
            />
          </div>
          <UploadZone onFilesAdded={handleFilesAdded} />
        </div>
      )}

      {/* Config */}
      <ConfigPanel config={config} onChange={setConfig} />

      {/* Stats */}
      <StatsBar stats={selectedFile?.result?.stats ?? null} />

      {/* Diff Viewer */}
      <DiffViewer result={selectedFile?.result ?? null} />

      {/* Download */}
      <DownloadBar files={files} selectedFile={selectedFile} />
    </div>
  )
}
