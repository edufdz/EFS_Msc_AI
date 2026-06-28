import { useState } from 'react'
import type { FileEntry } from '../api/types'
import { downloadFile, downloadZip } from '../utils/download'

interface Props {
  files: FileEntry[]
  selectedFile: FileEntry | null
}

export default function DownloadBar({ files, selectedFile }: Props) {
  const [copied, setCopied] = useState(false)

  const doneFiles = files.filter((f) => f.status === 'done')
  if (!selectedFile?.result && doneFiles.length === 0) return null

  const handleDownload = () => {
    if (!selectedFile?.result) return
    const name = selectedFile.file.name.replace(/\.(txt|json)$/i, '_anonymized.$1')
    downloadFile(name, selectedFile.result.anonymized_text)
  }

  const handleCopy = async () => {
    if (!selectedFile?.result) return
    await navigator.clipboard.writeText(selectedFile.result.anonymized_text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleZip = () => downloadZip(files)

  return (
    <div className="flex gap-3">
      {selectedFile?.result && (
        <>
          <button
            onClick={handleDownload}
            className="px-4 py-2 bg-accent text-white text-sm font-medium rounded hover:bg-accent-dim transition-colors"
          >
            Download
          </button>
          <button
            onClick={handleCopy}
            className="px-4 py-2 bg-bg-card text-text-primary text-sm font-medium rounded border border-border hover:bg-bg-surface transition-colors"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </>
      )}
      {doneFiles.length > 1 && (
        <button
          onClick={handleZip}
          className="px-4 py-2 bg-bg-card text-text-primary text-sm font-medium rounded border border-border hover:bg-bg-surface transition-colors"
        >
          Download All (ZIP)
        </button>
      )}
    </div>
  )
}
